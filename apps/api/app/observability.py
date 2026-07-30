"""Error tracking (Sentry) and, from a later commit, LLM tracing
(Langfuse) -- both shared by the FastAPI process (main.py) and the Celery
worker/beat processes (app/celery_app.py's worker_process_init/beat_init
signals). See docs/infra-guide.md.

Init lives here rather than directly in main.py/celery_app.py because it
needs to run in a specific way per process: main.py can just call it at
import time, but the Celery worker must NOT init at import time -- Celery
forks worker children after importing app.tasks, and (once Langfuse is
added here) a background-thread-based span exporter does not survive
fork(). worker_process_init fires post-fork, in each child, which is the
correct place.
"""

import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration

_initialized = False


def init_observability(service: str) -> None:
    """Idempotent -- safe to call from multiple entry points (main.py's
    module body, and Celery's worker_process_init/beat_init, which can
    both fire in a process that already ran this once)."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    _init_sentry(service)


def _init_sentry(service: str) -> None:
    dsn = os.getenv("SENTRY_DSN") or None  # unset/"" -> None -> sentry_sdk.init is a full no-op
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "local"),
        release=os.getenv("IMAGE_TAG"),
        # Langfuse (added in a later commit) already owns LLM call latency
        # in detail; performance tracing here would burn free-tier quota
        # for near-zero marginal insight on a single-instance deployment.
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        # This app carries real SME customer names, sale amounts, and
        # expense categories -- Sentry's own docs default this to True in
        # their example; deliberately not copying that here.
        send_default_pii=False,
        # monitor_beat_tasks registers dispatch_scheduled_analysis as a
        # Sentry Cron Monitor -- the only way to detect "beat isn't running
        # at all" rather than just "a task it dispatched failed". FastAPI's
        # own integration auto-enables with no explicit entry needed here.
        integrations=[CeleryIntegration(monitor_beat_tasks=True)],
    )
    sentry_sdk.set_tag("service", service)
