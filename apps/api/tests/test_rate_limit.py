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
