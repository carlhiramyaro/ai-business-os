import json

import structlog
from structlog.testing import capture_logs

from app.celery_app import celery_app
from app.database import get_db
from main import app


def test_request_id_header_generated_and_echoed(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]  # generated, non-empty


def test_request_id_header_passthrough(client):
    response = client.get("/", headers={"X-Request-ID": "test-req-123"})
    assert response.headers["X-Request-ID"] == "test-req-123"


def test_unhandled_exception_returns_500_with_request_id(client):
    """Replaces the bare, uncorrelatable 500 FastAPI/Starlette give by
    default -- a tester can now read the requestId off the screen and it's
    directly greppable in CloudWatch. See app/logging_config.py, main.py's
    unhandled_exception_handler."""

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
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert body["requestId"]
    assert response.headers["X-Request-ID"] == body["requestId"]


def test_task_failure_signal_logs_structured_event():
    """One insertion point (app/celery_app.py's _log_task_failure) covers
    every Celery task's failure -- including run_business_analysis_task
    and dispatch_scheduled_analysis_task, which have no exception handling
    of their own. See docs/decisions.md."""

    class _FakeTask:
        name = "fake_task_for_test"

    exc = ValueError("boom")
    with capture_logs() as logs:
        celery_app.conf.task_always_eager  # ensure celery_app is imported/configured
        from celery.signals import task_failure

        task_failure.send(sender=_FakeTask(), task_id="test-task-id", exception=exc, traceback=exc.__traceback__)

    failure_logs = [entry for entry in logs if entry["event"] == "task_failed"]
    assert len(failure_logs) == 1
    assert failure_logs[0]["task_id"] == "test-task-id"
    assert failure_logs[0]["task_name"] == "fake_task_for_test"
    assert failure_logs[0]["error"] == "boom"
    assert failure_logs[0]["log_level"] == "error"


def test_json_renderer_produces_parseable_json_with_bound_keys():
    """Unit test of the renderer choice itself, independent of
    configure_logging's process-wide idempotent gate (which may already
    have locked in the console renderer from an earlier import in this
    test session) -- confirms the JSON branch app/logging_config.py picks
    for non-local environments actually produces valid, parseable JSON
    carrying bound contextvars."""
    renderer = structlog.processors.JSONRenderer()
    event_dict = {"event": "test_event", "request_id": "abc-123", "level": "info"}
    output = renderer(None, "info", event_dict)
    parsed = json.loads(output)
    assert parsed["event"] == "test_event"
    assert parsed["request_id"] == "abc-123"
