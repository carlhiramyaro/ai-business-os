import sentry_sdk

from app import observability


def test_init_observability_is_noop_with_no_dsn(monkeypatch):
    """SENTRY_DSN unset (the default in CI and local dev) must make
    sentry_sdk.init a true no-op -- no exception, and no transport
    constructed to actually send anything. (Client.is_active() is not the
    right check here -- it's hardcoded to always return True as of
    sentry-sdk 2.x; dsn/transport being falsy is the real signal. dsn is ""
    rather than None -- see the next test's docstring for why that
    distinction matters.)"""
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    observability.init_observability("test")

    client = sentry_sdk.get_client()
    assert not client.dsn
    assert client.transport is None


def test_init_observability_is_noop_with_placeholder_dsn(monkeypatch):
    """Regression test for a real production incident: infra/ssm.tf seeds
    SENTRY_DSN with the literal string REPLACE_ME_MANUALLY until it's
    replaced by hand, and that value is always present as a real env var in
    app.env on the box -- unlike the "unset" case above. Passing dsn=None
    to sentry_sdk.init does NOT disable it here, because sentry_sdk's own
    _get_options() re-reads os.environ["SENTRY_DSN"] itself whenever the
    dsn kwarg is exactly None (sentry_sdk/client.py), silently overriding
    app-level gating and crashing with BadDsn since the placeholder isn't a
    valid DSN URL. This crashed the production api container. The fix
    passes "" instead of None so that fallback never triggers."""
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setenv("SENTRY_DSN", "REPLACE_ME_MANUALLY")

    observability.init_observability("test")

    client = sentry_sdk.get_client()
    assert not client.dsn
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
