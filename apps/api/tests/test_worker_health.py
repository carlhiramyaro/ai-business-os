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
    monkeypatch.setattr(celery_app.conf, "task_always_eager", False)

    def _raise(timeout=0.5):
        raise ConnectionError("no broker")

    monkeypatch.setattr(celery_app.control, "ping", _raise)
    assert workers_online() is False
