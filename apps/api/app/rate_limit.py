"""v0.5 slice 3 (multi-tenant hardening): rate limiting.

Uses the `limits` library directly rather than `slowapi` -- slowapi's API
is decorator-centric (`@limiter.limit(...)`, requiring `request: Request`
on every decorated route) and fails silently open on any route someone
forgets to decorate. `limits` is the library slowapi itself wraps
(identical counting/storage code); wrapping it in a plain FastAPI
dependency here matches this codebase's existing `require_worker_online`
pattern (app/dependencies.py) exactly, and keeps a 429 raised *inside*
FastAPI's routing layer, where CORSMiddleware still decorates it -- a 429
raised from outer ASGI middleware would not get CORS headers. See
docs/decisions.md.
"""

import os
import time

import jwt
import limits
import structlog
from fastapi import HTTPException, Request, status
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter

from app.security import decode_access_token

logger = structlog.get_logger(__name__)

# All env-overridable -- tuning a limit in production is an SSM parameter
# change + deploy, never a code change, same precedent as
# ANALYSIS_INTERVAL_SECONDS. RATE_LIMIT_DEFAULT is read once at import
# time (the app-level dependency is constructed once per process, same as
# ANALYSIS_INTERVAL_SECONDS' beat_schedule); RATE_LIMIT_ENABLED and
# RATE_LIMIT_STORAGE_URI are read fresh on every call (see below) so tests
# can flip them per-test with monkeypatch.setenv without reloading this
# module.
DEFAULT_LIMIT_SPEC = os.getenv("RATE_LIMIT_DEFAULT", "300/minute")

# A separate logical Redis DB from the Celery broker (db 0) -- so a
# FLUSHDB while debugging Celery doesn't reset every rate-limit counter,
# and vice versa. Defaults to REDIS_URL for local dev (where a separate
# DB isn't worth the extra env var); production sets this explicitly via
# SSM to redis://redis:6379/1.
_DEFAULT_STORAGE_URI = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_storages: dict[str, tuple] = {}


def _get_limiter(storage_uri: str) -> tuple:
    """Cached per storage URI (not a single global) so tests that point
    RATE_LIMIT_STORAGE_URI at a scratch Redis DB get their own storage
    object without disturbing whatever the app itself is using."""
    cached = _storages.get(storage_uri)
    if cached is not None:
        return cached
    storage = storage_from_string(storage_uri)
    limiter = MovingWindowRateLimiter(storage)
    _storages[storage_uri] = (storage, limiter)
    return storage, limiter


def client_ip(request: Request) -> str:
    """Takes the LAST X-Forwarded-For entry, not the first.

    Caddy *appends* the connecting peer's IP to any inbound
    X-Forwarded-For, so a client sending "X-Forwarded-For: 1.2.3.4"
    produces "1.2.3.4, <real client ip>" on arrival at uvicorn -- the
    leftmost entry is attacker-controlled (anyone can send their own
    X-Forwarded-For header) and would let a per-IP limit be bypassed by
    rotating it. The rightmost entry is the one Caddy itself wrote.

    This is correct for exactly one trusted proxy hop. If an ALB/CDN is
    ever added in front of Caddy (docs/infra-guide.md's ECS migration
    path), this must skip that many entries instead.

    request.client.host is NOT usable as a fallback in production: uvicorn
    runs with no --forwarded-allow-ips (docker-compose.prod.yml), so its
    default trusts nothing, and request.client.host is Caddy's own
    container IP for every request Caddy proxies. It's only meaningful
    here for local dev / tests, where there's no proxy in front at all.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return request.client.host if request.client is not None else "unknown"


def rate_limit_key(request: Request) -> str:
    """Prefers the authenticated user over IP. Matters specifically for
    this product's market: carrier-grade NAT is the norm for African
    mobile users (CLAUDE.md's target audience), so a pure per-IP limit
    would put entire mobile networks in one shared bucket. Falls through
    to IP on a missing/invalid/expired token -- rate limiting an
    unauthenticated or bad-token request by IP is still correct and safe,
    just less precise."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[len("bearer ") :]
        try:
            payload = decode_access_token(token)
        except jwt.PyJWTError:
            payload = None
        if payload is not None:
            user_id = payload.get("sub")
            if user_id:
                return f"user:{user_id}"
    return f"ip:{client_ip(request)}"


class RateLimit:
    """A FastAPI dependency, not a decorator -- see this module's
    docstring for why. Use as `Depends(RateLimit("20/minute", "chat"))`,
    either as an app-level `dependencies=[...]` (applies to every route)
    or a route-level one.

    `scope` is a short name distinguishing this limit's counter bucket
    from any other RateLimit instance that happens to use an identical
    spec string and the same key (e.g. two different endpoints both
    limited to "300/minute" for the same user) -- without it they'd
    silently share one bucket."""

    def __init__(self, spec: str, scope: str, key_fn=rate_limit_key):
        self._spec = spec
        self._scope = scope
        self._key_fn = key_fn
        self._items = limits.parse_many(spec)

    def __call__(self, request: Request) -> None:
        if os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() == "false":
            return

        storage_uri = os.getenv("RATE_LIMIT_STORAGE_URI", _DEFAULT_STORAGE_URI)
        try:
            _storage, limiter = _get_limiter(storage_uri)
            key = self._key_fn(request)
            # Each item in a compound spec ("20/minute;300/day") is hit in
            # sequence; if an earlier item passes but a later one rejects,
            # the earlier item's counter has already been incremented.
            # This is the standard, accepted imprecision for compound
            # limits (the same tradeoff slowapi's own decorator makes) --
            # the alternative (a check-all-then-hit-all two-phase commit)
            # isn't atomic across a compound spec either, for a problem
            # this doesn't need to solve.
            for item in self._items:
                if not limiter.hit(item, self._scope, key):
                    stats = limiter.get_window_stats(item, self._scope, key)
                    retry_after = max(1, int(stats.reset_time - time.time()))
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Too many requests. Please try again in {retry_after} seconds.",
                        headers={"Retry-After": str(retry_after)},
                    )
        except HTTPException:
            raise
        except Exception as exc:
            # Fails open: Redis being down already degrades this system
            # visibly and safely elsewhere (require_worker_online returns
            # 503) -- failing closed here would turn a Redis blip into a
            # full outage of even read-only endpoints, for no security
            # benefit. Deliberate availability-over-strictness call.
            logger.warning("rate_limit_storage_unavailable", scope=self._scope, error=str(exc))
            return
