"""v0.5 slice 3 (multi-tenant hardening): the rate-limiting mechanism.

Uses real Redis, not `memory://` -- per docs/agent-instructions.md's "only
the LLM call gets mocked, not the datastore" rule, and because the
interesting failure modes here (key naming, TTL, cross-process sharing,
whether this is actually hitting Redis at all vs. silently falling back to
in-process counting) only exist against a real backend. Points at a
scratch logical Redis DB so this never touches the Celery broker's db 0 or
any other test's state.
"""

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from structlog.testing import capture_logs

import app.routers.auth as auth_module
from app.rate_limit import RateLimit, _get_limiter, client_ip, rate_limit_key
from app.security import create_access_token

TEST_STORAGE_URI = "redis://localhost:6379/15"


def _make_request(headers=None, client_host="203.0.113.1"):
    encoded_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "headers": encoded_headers,
        "client": (client_host, 12345) if client_host else None,
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _reset_rate_limit_storage():
    storage, _limiter = _get_limiter(TEST_STORAGE_URI)
    storage.reset()
    yield
    storage.reset()


@pytest.fixture()
def rate_limited_app(monkeypatch):
    """A minimal standalone app with one route guarded by a low, explicit
    limit -- RateLimit itself is the unit under test here, not main.py's
    specific 300/minute wiring (that's covered by
    test_app_level_default_rate_limit_dependency_is_present below)."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", TEST_STORAGE_URI)

    app = FastAPI()

    @app.get("/ping")
    def ping(_: None = Depends(RateLimit("3/minute", "test-ping"))):
        return {"ok": True}

    return TestClient(app)


def test_client_ip_takes_last_forwarded_for_entry():
    # Caddy appends the real peer IP -- the leftmost entry is
    # attacker-controlled and must not be trusted.
    request = _make_request(headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.5"})
    assert client_ip(request) == "10.0.0.5"


def test_client_ip_falls_back_to_peer_without_proxy_header():
    request = _make_request(headers={}, client_host="198.51.100.7")
    assert client_ip(request) == "198.51.100.7"


def test_rate_limit_key_prefers_user_id():
    token = create_access_token("11111111-1111-1111-1111-111111111111")
    request = _make_request(headers={"Authorization": f"Bearer {token}"})
    assert rate_limit_key(request) == "user:11111111-1111-1111-1111-111111111111"


def test_rate_limit_key_falls_back_to_ip_when_token_invalid():
    request = _make_request(headers={"Authorization": "Bearer not-a-real-token"}, client_host="198.51.100.9")
    assert rate_limit_key(request) == "ip:198.51.100.9"


def test_default_limit_returns_429_with_retry_after(rate_limited_app):
    for _ in range(3):
        assert rate_limited_app.get("/ping").status_code == 200

    response = rate_limited_app.get("/ping")
    assert response.status_code == 429
    assert response.json()["detail"]  # non-empty, plain-sentence message

    retry_after = int(response.headers["Retry-After"])
    assert retry_after > 0


def test_limits_are_per_key_not_global(monkeypatch):
    """The regression guard for the production Caddy-proxy trap: if
    client_ip ever regressed to trusting request.client.host directly (or
    the leftmost X-Forwarded-For entry), every user behind the same proxy
    -- i.e. everyone in production -- would share one bucket."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", TEST_STORAGE_URI)
    app = FastAPI()

    @app.get("/ping")
    def ping(_: None = Depends(RateLimit("2/minute", "test-per-key"))):
        return {"ok": True}

    client = TestClient(app)

    for _ in range(2):
        assert client.get("/ping", headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
    assert client.get("/ping", headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 429

    # A different (spoofed) client IP gets its own, unspent budget.
    for _ in range(2):
        assert client.get("/ping", headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200
    assert client.get("/ping", headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 429


def test_disabled_by_env_never_limits(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", TEST_STORAGE_URI)
    app = FastAPI()

    @app.get("/ping")
    def ping(_: None = Depends(RateLimit("1/minute", "test-disabled"))):
        return {"ok": True}

    client = TestClient(app)
    for _ in range(5):
        assert client.get("/ping").status_code == 200


def test_fails_open_when_storage_unavailable(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    # Port 1 is privileged and essentially never bound locally -- fails
    # fast with connection-refused rather than hanging on a timeout.
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "redis://localhost:1/0")
    app = FastAPI()

    @app.get("/ping")
    def ping(_: None = Depends(RateLimit("1/minute", "test-fail-open"))):
        return {"ok": True}

    client = TestClient(app)
    with capture_logs() as logs:
        response = client.get("/ping")

    assert response.status_code == 200
    warnings = [entry for entry in logs if entry["event"] == "rate_limit_storage_unavailable"]
    assert len(warnings) == 1
    assert warnings[0]["scope"] == "test-fail-open"


def test_app_level_default_rate_limit_dependency_is_present():
    """Guards main.py's app-level dependencies=[Depends(RateLimit(...))]
    line -- deleting it should fail CI, not silently disable rate limiting
    on every route."""
    from main import app

    assert any(isinstance(d.dependency, RateLimit) for d in app.router.dependencies)


# v0.5 slice 3, Commit 4: app/routers/auth.py's _RATE_LIMIT_LOGIN_IP/
# _RATE_LIMIT_LOGIN_EMAIL/_RATE_LIMIT_REGISTER/_RATE_LIMIT_REFRESH are read
# from the environment once at import time (matching ANALYSIS_INTERVAL_
# SECONDS' pattern), not per-call -- so these tests override them with
# monkeypatch.setattr on the already-imported module, not monkeypatch.
# setenv (which check_rate_limit's own RATE_LIMIT_ENABLED/
# RATE_LIMIT_STORAGE_URI reads dynamically and setenv works fine for).


def _register(client, email="ratelimit@example.com", password="password123"):
    return client.post(
        "/api/v1/auth/register", json={"fullName": "Rate Limit Test", "email": email, "password": password}
    )


def _login(client, email="ratelimit@example.com", password="password123", headers=None):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers=headers or {})


@pytest.fixture()
def _enable_rate_limiting_for_auth(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", TEST_STORAGE_URI)


def test_register_limit_returns_429_after_threshold(client, _enable_rate_limiting_for_auth):
    """Deliberately does NOT monkeypatch _RATE_LIMIT_REGISTER: unlike
    login's checks (a plain function reading the module global at call
    time), register's limit is `Depends(RateLimit(_RATE_LIMIT_REGISTER,
    ...))` -- the spec string is bound into the RateLimit instance once,
    at route-decoration time (module import), matching the same
    read-once-at-startup convention as ANALYSIS_INTERVAL_SECONDS.
    monkeypatch.setattr on the module name afterward can't reach the
    already-constructed instance, so this exercises the real default
    (5/hour) instead."""
    for i in range(5):
        response = client.post(
            "/api/v1/auth/register",
            json={"fullName": "Test", "email": f"user{i}@example.com", "password": "password123"},
        )
        assert response.status_code == 201

    response = client.post(
        "/api/v1/auth/register",
        json={"fullName": "Test", "email": "user-over-limit@example.com", "password": "password123"},
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_login_email_limit_trips_even_across_rotating_ips(client, _enable_rate_limiting_for_auth, monkeypatch):
    """The regression guard for the actual security case: an attacker
    rotating IPs must not be able to evade the per-email brute-force
    limit just because the per-IP limit is generous."""
    monkeypatch.setattr(auth_module, "_RATE_LIMIT_LOGIN_EMAIL", "2/hour")
    monkeypatch.setattr(auth_module, "_RATE_LIMIT_LOGIN_IP", "1000/hour")
    _register(client, "target@example.com")

    for i in range(2):
        response = _login(
            client, email="target@example.com", password="wrong", headers={"X-Forwarded-For": f"10.0.0.{i}"}
        )
        assert response.status_code == 401  # wrong password, not yet limited

    limited = _login(
        client, email="target@example.com", password="wrong", headers={"X-Forwarded-For": "10.0.0.99"}
    )
    assert limited.status_code == 429


def test_login_429_message_is_identical_for_known_and_unknown_email(
    client, _enable_rate_limiting_for_auth, monkeypatch
):
    """Must not regress the existing enumeration defense (auth.py already
    returns an identical 401 for unknown-email vs. wrong-password) -- the
    429 message must carry the same non-distinguishing guarantee."""
    monkeypatch.setattr(auth_module, "_RATE_LIMIT_LOGIN_EMAIL", "2/hour")
    monkeypatch.setattr(auth_module, "_RATE_LIMIT_LOGIN_IP", "1000/hour")
    _register(client, "known@example.com")

    for _ in range(2):
        _login(client, email="known@example.com", password="wrong")
    known_429 = _login(client, email="known@example.com", password="wrong")
    assert known_429.status_code == 429

    for _ in range(2):
        _login(client, email="nobody-at-all@example.com", password="wrong")
    unknown_429 = _login(client, email="nobody-at-all@example.com", password="wrong")
    assert unknown_429.status_code == 429

    # Retry-After's numeric value legitimately differs by a few seconds
    # (real wall-clock time elapsed between the two request sequences) --
    # compare the message with digits normalized out, not byte-for-byte.
    def _template(detail: str) -> str:
        return "".join("N" if ch.isdigit() else ch for ch in detail)

    assert _template(known_429.json()["detail"]) == _template(unknown_429.json()["detail"])


def test_refresh_limit_returns_429_after_threshold(client, _enable_rate_limiting_for_auth):
    """Same read-once-at-import constraint as register above -- the
    default (60/hour) is too many requests to loop directly in a fast
    test, so this pre-exhausts the exact (scope, key) the real route uses
    via check_rate_limit directly, then confirms the real endpoint (same
    underlying Redis counter) is already limited."""
    from app.rate_limit import check_rate_limit

    _register(client)
    refresh_token = _login(client).json()["refreshToken"]

    # TestClient's request.client.host is the fixed string "testclient"
    # (no real socket involved) -- confirmed directly against a throwaway
    # app; with no X-Forwarded-For header sent, this is the key
    # rate_limit_key resolves to for every unauthenticated TestClient
    # request in this test.
    for _ in range(60):
        check_rate_limit(auth_module._RATE_LIMIT_REFRESH, "refresh", "ip:testclient")

    response = client.post("/api/v1/auth/refresh", json={"refreshToken": refresh_token})
    assert response.status_code == 429
