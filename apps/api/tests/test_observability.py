import sentry_sdk

from app import observability


def test_init_observability_is_noop_with_no_dsn(monkeypatch):
    """SENTRY_DSN unset (the default in CI and local dev) must make
    sentry_sdk.init a true no-op -- no exception, and no transport
    constructed to actually send anything. (Client.is_active() is not the
    right check here -- it's hardcoded to always return True as of
    sentry-sdk 2.x; dsn/transport being None is the real signal.)"""
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    observability.init_observability("test")

    client = sentry_sdk.get_client()
    assert client.dsn is None
    assert client.transport is None


def test_init_observability_is_idempotent(monkeypatch):
    """Safe to call from both main.py's module body and Celery's
    worker_process_init/beat_init without double-initializing."""
    monkeypatch.setattr(observability, "_initialized", False)

    observability.init_observability("test")
    first_client = sentry_sdk.get_client()

    observability.init_observability("test")
    second_client = sentry_sdk.get_client()

    assert first_client is second_client
