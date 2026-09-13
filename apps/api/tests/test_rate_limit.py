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

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from structlog.testing import capture_logs

from app.rate_limit import RateLimit, _get_limiter, client_ip, rate_limit_key
from tests.auth_helpers import mint_token

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
    token = mint_token("11111111-1111-1111-1111-111111111111", "ratelimit@example.com")
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


# v0.5 slice 3, Commit 4 originally added rate limits on /auth/register,
# /auth/login, /auth/refresh -- removed along with those endpoints when
# auth moved to Clerk (docs/decisions.md's Clerk-migration entry). Clerk
# owns registration/login abuse protection now. This fixture is kept: the
# LLM/expensive-endpoint tests below still use it.


@pytest.fixture()
def _enable_rate_limiting_for_auth(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", TEST_STORAGE_URI)


# v0.5 slice 3, Commit 5: LLM/expensive-endpoint limits. Same
# read-once-at-decoration-time constraint as register/refresh above --
# each of these five routes' RateLimit instance is constructed once, at
# import time, so the tests below pre-exhaust the exact (spec, scope, key)
# the real route checks via check_rate_limit directly (fast, no need to
# actually exercise the expensive request path -- OpenAI calls, S3
# writes -- N times just to prove the dependency is wired to the right
# scope), then confirm a single real request to the real endpoint is
# already limited. This is what actually proves the wiring: the scope
# name and key resolution used here must exactly match what the route
# itself uses, or this would pass for the wrong reason.

from app.rate_limit import check_rate_limit  # noqa: E402
from tests.auth_helpers import register_and_login as _register_and_login  # noqa: E402


def _create_business(client, token, name="Test Biz"):
    response = client.post(
        "/api/v1/businesses/", json={"businessName": name}, headers={"Authorization": f"Bearer {token}"}
    )
    return response.json()["id"]


def _decode_sub(access_token: str) -> str:
    # Unverified: this token was minted by this same test process (see
    # tests/auth_helpers.py), so there's nothing to verify against --
    # just reading back the `sub` claim it was given.
    return jwt.decode(access_token, options={"verify_signature": False})["sub"]


_FAKE_ID = "00000000-0000-0000-0000-000000000000"


def test_chat_limit_returns_429_after_threshold(client, _enable_rate_limiting_for_auth):
    token = _register_and_login("chat-limit@example.com")
    business_id = _create_business(client, token)

    for _ in range(20):
        check_rate_limit("20/minute;300/day", "chat", f"user:{_decode_sub(token)}")

    response = client.post(
        f"/api/v1/businesses/{business_id}/chat/{_FAKE_ID}/messages",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429


def test_chat_limit_is_shared_across_a_users_businesses_not_per_business(client, _enable_rate_limiting_for_auth):
    """The cost this limit bounds is per-user (real OpenAI spend), not
    per-business -- a user with two businesses shares one chat budget."""
    token = _register_and_login("multi-biz@example.com")
    business_a = _create_business(client, token, "Biz A")
    business_b = _create_business(client, token, "Biz B")

    for _ in range(20):
        check_rate_limit("20/minute;300/day", "chat", f"user:{_decode_sub(token)}")

    response = client.post(
        f"/api/v1/businesses/{business_b}/chat/{_FAKE_ID}/messages",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429  # business_a's usage counted against business_b's request too


def test_chat_limit_is_not_shared_across_users(client, _enable_rate_limiting_for_auth):
    token_a = _register_and_login("user-a@example.com")
    token_b = _register_and_login("user-b@example.com")
    business_b_id = _create_business(client, token_b, "User B's Biz")

    for _ in range(20):
        check_rate_limit("20/minute;300/day", "chat", f"user:{_decode_sub(token_a)}")

    # User A is exhausted, but User B (a different key) is untouched --
    # 403 (not the owner of a fake conversation under their own business)
    # rather than 429 proves the rate limit did NOT trip for User B.
    response = client.post(
        f"/api/v1/businesses/{business_b_id}/chat/{_FAKE_ID}/messages",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404  # real business, fake conversation_id -> 404, not 429


def test_reports_generate_limit_returns_429_after_threshold(client, _enable_rate_limiting_for_auth):
    token = _register_and_login("reports-limit@example.com")
    business_id = _create_business(client, token)

    for _ in range(10):
        check_rate_limit("10/hour", "reports", f"user:{_decode_sub(token)}")

    response = client.post(
        f"/api/v1/businesses/{business_id}/reports/generate",
        json={"periodStart": "2026-01-01", "periodEnd": "2026-01-31"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429


def test_insights_run_limit_returns_429_after_threshold(client, _enable_rate_limiting_for_auth):
    token = _register_and_login("insights-limit@example.com")
    business_id = _create_business(client, token)

    for _ in range(10):
        check_rate_limit("10/hour", "insights", f"user:{_decode_sub(token)}")

    response = client.post(
        f"/api/v1/businesses/{business_id}/insights/run", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 429


def test_uploads_limit_returns_429_after_threshold(client, _enable_rate_limiting_for_auth):
    token = _register_and_login("uploads-limit@example.com")
    business_id = _create_business(client, token)

    for _ in range(30):
        check_rate_limit("30/hour", "uploads", f"user:{_decode_sub(token)}")

    response = client.post(
        f"/api/v1/businesses/{business_id}/uploads/", files={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 429  # would otherwise be 400 (no files provided)


def test_documents_limit_returns_429_after_threshold(client, _enable_rate_limiting_for_auth):
    token = _register_and_login("documents-limit@example.com")
    business_id = _create_business(client, token)

    for _ in range(60):
        check_rate_limit("60/hour", "documents", f"user:{_decode_sub(token)}")

    response = client.post(
        f"/api/v1/businesses/{business_id}/documents/",
        data={"datasetType": "sales"},
        files={"image": ("receipt.jpg", b"fake-image-bytes", "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429
