"""v0.5 slice 3 (multi-tenant hardening): turns the businessId audit into a
structural invariant instead of a point-in-time snapshot. Every router in
this codebase was checked by hand at audit time and found to consistently
depend on get_owned_business (or a further-nested get_owned_* dependency
that itself depends on it) -- see docs/decisions.md. That finding has no
shelf life on its own; this file is what makes it true going forward: a
future route added under /businesses/{business_id}/... without the
ownership dependency fails CI here instead of shipping a cross-tenant leak.

FastAPI's own dependency graph is walked directly (via each route's
`.dependant`), not grepped from source -- so a dependency wired in
indirectly (e.g. through another dependency that itself depends on
get_owned_business) is still detected correctly.
"""

from app.dependencies import get_owned_business
from main import app

# Routes not scoped to a specific business -- auth (pre-business by
# definition), the businesses collection endpoints themselves (list/create,
# which can't be business_id-scoped since the business doesn't exist yet on
# create, and list is scoped to the current user instead), and pure
# infrastructure endpoints. Adding a new *unscoped* route requires a
# deliberate edit here, which is the point.
_UNSCOPED_ALLOWLIST = {
    ("GET", "/"),
    ("GET", "/health/db"),
    ("GET", "/health/worker"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/businesses/"),
    ("GET", "/api/v1/businesses/"),
}


def _all_api_routes():
    """FastAPI 0.139's app.routes wraps each include_router() call in an
    _IncludedRouter rather than flattening it -- the actual APIRoute
    objects live on `.original_router.routes`. Confirmed by inspection
    against this exact FastAPI version; if a future FastAPI upgrade
    changes this shape, this function (and only this function) needs
    updating -- the routes below would otherwise silently stop being
    checked at all, which is exactly the failure mode this file exists to
    prevent, so keep this helper's assumptions easy to re-verify."""
    routes = []
    for route in app.routes:
        if type(route).__name__ == "_IncludedRouter":
            routes.extend(route.original_router.routes)
        elif type(route).__name__ == "APIRoute":
            routes.append(route)
    return routes


def _dependency_calls(dependant, seen=None):
    """Recursively collects every `.call` (the actual dependency function)
    reachable from a route's dependant, including dependencies-of-
    dependencies -- get_owned_report etc. depend on get_owned_business
    themselves, so this must not stop at depth 1."""
    if seen is None:
        seen = set()
    calls = []
    for sub_dependant in dependant.dependencies:
        if id(sub_dependant) in seen:
            continue
        seen.add(id(sub_dependant))
        calls.append(sub_dependant.call)
        calls.extend(_dependency_calls(sub_dependant, seen))
    return calls


_ALL_ROUTES = _all_api_routes()
_BUSINESS_SCOPED_ROUTES = [r for r in _ALL_ROUTES if "{business_id}" in r.path]
_UNSCOPED_ROUTES = [r for r in _ALL_ROUTES if "{business_id}" not in r.path]


def test_route_inventory_is_non_empty():
    """Guards the two lists above against the inventory itself silently
    coming back empty (e.g. a future FastAPI upgrade changing the
    _IncludedRouter shape again) -- without this, every test below would
    vacuously "pass" by having nothing to check."""
    assert len(_BUSINESS_SCOPED_ROUTES) >= 30
    assert len(_UNSCOPED_ROUTES) >= 9


def _route_id(route):
    methods = ",".join(sorted(route.methods - {"HEAD"}))
    return f"{methods} {route.path}"


def test_every_business_scoped_route_verifies_ownership():
    violations = []
    for route in _BUSINESS_SCOPED_ROUTES:
        calls = _dependency_calls(route.dependant)
        if get_owned_business not in calls:
            violations.append(_route_id(route))
    assert violations == [], (
        "route(s) under /businesses/{business_id}/... do not depend on "
        "get_owned_business (directly or via a get_owned_* dependency): "
        f"{violations}. Every business-scoped route must verify the "
        "current user owns the business -- see app/dependencies.py."
    )


def test_every_unscoped_route_is_on_the_explicit_allowlist():
    unexpected = []
    for route in _UNSCOPED_ROUTES:
        for method in sorted(route.methods - {"HEAD"}):
            if (method, route.path) not in _UNSCOPED_ALLOWLIST:
                unexpected.append(f"{method} {route.path}")
    assert unexpected == [], (
        f"route(s) not scoped under /businesses/{{business_id}}/... and not "
        f"on the explicit allowlist: {unexpected}. If this route "
        "legitimately doesn't need business ownership scoping, add it to "
        "_UNSCOPED_ALLOWLIST in this file as a deliberate decision -- if it "
        "was meant to be business-scoped, fix the route instead."
    )
