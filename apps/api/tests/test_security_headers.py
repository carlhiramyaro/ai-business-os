"""v0.5 slice 3 (multi-tenant hardening): security response headers.

Set in application code (main.py), not Caddy -- editing Caddyfile forces a
full EC2 instance replacement (baked into infra/ec2.tf's user-data), while
an app-code change ships via the normal fast image-deploy path and is
testable here, which an edge-only Caddy config isn't. See docs/decisions.md.
"""

import main
from app.database import get_db
from main import app

_EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "permissions-policy": "geolocation=(), microphone=(), camera=()",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}


def test_security_headers_present_on_200(client):
    response = client.get("/")
    assert response.status_code == 200
    for header, value in _EXPECTED_HEADERS.items():
        assert response.headers[header] == value


def test_security_headers_present_on_500(client):
    """Same _BrokenSession pattern as test_logging.py's
    test_unhandled_exception_returns_500_with_request_id -- confirms the
    headers land on the middleware-synthesized 500 response too, not just
    successful ones."""

    class _BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("simulated db failure")

    def _broken_get_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = _broken_get_db
    try:
        response = client.get("/health/db")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 500
    for header, value in _EXPECTED_HEADERS.items():
        assert response.headers[header] == value


def test_hsts_absent_when_environment_is_local(client, monkeypatch):
    monkeypatch.setattr(main, "_ENVIRONMENT", "local")
    response = client.get("/")
    assert "strict-transport-security" not in response.headers


def test_hsts_present_when_environment_is_not_local(client, monkeypatch):
    monkeypatch.setattr(main, "_ENVIRONMENT", "prod")
    response = client.get("/")
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
