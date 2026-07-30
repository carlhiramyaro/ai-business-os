from structlog.testing import capture_logs

from app.celery_app import celery_app
from app.worker_health import workers_online


def test_workers_online_true_when_task_always_eager(monkeypatch):
    """conftest.py's _celery_eager fixture sets task_always_eager=True for
    the whole test session -- in that mode Celery never touches the broker,
    so workers_online() must short-circuit True rather than pinging a
    broker no worker is actually listening on."""
    assert celery_app.conf.task_always_eager is True
    assert workers_online() is True


def test_workers_online_reflects_ping_replies_when_not_eager(monkeypatch):
    monkeypatch.setattr(celery_app.conf, "task_always_eager", False)

    monkeypatch.setattr(celery_app.control, "ping", lambda timeout=0.5: [{"worker@host": {"ok": "pong"}}])
    assert workers_online() is True

    monkeypatch.setattr(celery_app.control, "ping", lambda timeout=0.5: [])
    assert workers_online() is False


def test_workers_online_false_on_broker_error(monkeypatch):
    """Behavior unchanged (still reports down) -- but this used to be a
    bare `except Exception: return False` with zero trace of the real
    cause, misdiagnosing a broker outage as "worker offline". Now it logs
    the actual reason. See docs/decisions.md."""
    monkeypatch.setattr(celery_app.conf, "task_always_eager", False)

    def _raise(timeout=0.5):
        raise ConnectionError("no broker")

    monkeypatch.setattr(celery_app.control, "ping", _raise)

    with capture_logs() as logs:
        assert workers_online() is False

    assert any(
        entry["event"] == "worker_ping_failed" and entry["error"] == "no broker" and entry["log_level"] == "warning"
        for entry in logs
    )
