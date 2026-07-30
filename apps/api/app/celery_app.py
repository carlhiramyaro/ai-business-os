import os

import structlog
from celery import Celery
from celery.signals import (
    beat_init,
    task_failure,
    task_postrun,
    task_prerun,
    worker_process_init,
    worker_process_shutdown,
)
from dotenv import load_dotenv

from app.logging_config import configure_logging
from app.observability import flush_observability, init_observability

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("ai_business_os", broker=REDIS_URL, backend=REDIS_URL, include=["app.tasks"])
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]

# Celery replaces the root logger's handlers at worker startup by default,
# which would silently discard app/logging_config.py's setup. See
# docs/infra-guide.md.
celery_app.conf.worker_hijack_root_logger = False

_logger = structlog.get_logger(__name__)


# Runs post-fork in each prefork worker child (and once in beat), not at
# import time -- import-time init here would run in the API process too
# (main.py transitively imports this module via app.worker_health), and
# separately, Langfuse's OTel BatchSpanProcessor runs on a background
# thread that does not survive Celery's fork(). See docs/infra-guide.md.
@worker_process_init.connect
def _init_worker_observability(**kwargs):
    configure_logging("worker")
    init_observability("worker")


@beat_init.connect
def _init_beat_observability(**kwargs):
    configure_logging("beat")
    init_observability("beat")


@worker_process_shutdown.connect
def _flush_worker_observability(**kwargs):
    flush_observability()


@task_prerun.connect
def _bind_task_context(task_id=None, task=None, **kwargs):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=task_id, task_name=getattr(task, "name", None))


@task_postrun.connect
def _clear_task_context(**kwargs):
    # Prefork children reuse the same process across many tasks -- without
    # this, one task's task_id would leak into every subsequent task's log
    # lines in that worker process.
    structlog.contextvars.clear_contextvars()


@task_failure.connect
def _log_task_failure(task_id=None, exception=None, sender=None, traceback=None, **kwargs):
    """Single insertion point covering all Celery tasks' failures,
    including run_business_analysis_task and dispatch_scheduled_analysis_task,
    which have no exception handling of their own -- a failure there was
    100% silent before this (see docs/decisions.md). Sentry's
    CeleryIntegration (app/observability.py) already auto-captures task
    failures for error tracking; this handler is the structured-logging
    half of that story, not a duplicate of it.

    Passes an explicit (type, exception, traceback) tuple to exc_info
    rather than relying on sys.exc_info() -- this signal handler doesn't
    reliably run inside the original except block, but Celery hands us the
    traceback object directly (app/trace.py's task_failure.send call)."""
    exc_info = (type(exception), exception, traceback) if exception is not None else True
    _logger.error(
        "task_failed",
        task_id=task_id,
        task_name=getattr(sender, "name", None),
        error=str(exception),
        exc_info=exc_info,
    )

# v0.4 slice 2: Celery beat's periodic schedule -- run alongside the worker
# via `celery -A app.celery_app beat` (see agent-instructions.md's run-book).
# Interval is env-overridable so a demo/dev session can shrink it well
# below the 24h production default without a code change.
ANALYSIS_INTERVAL_SECONDS = int(os.getenv("ANALYSIS_INTERVAL_SECONDS", str(24 * 60 * 60)))
celery_app.conf.beat_schedule = {
    "dispatch-scheduled-analysis": {
        "task": "dispatch_scheduled_analysis",
        "schedule": ANALYSIS_INTERVAL_SECONDS,
    },
}
