"""Error tracking (Sentry) and LLM tracing (Langfuse) -- both shared by the
FastAPI process (main.py) and the Celery worker/beat processes
(app/celery_app.py's worker_process_init/beat_init signals). See
docs/infra-guide.md.

Init lives here rather than directly in main.py/celery_app.py because it
needs to run in a specific way per process: main.py can just call it at
import time, but the Celery worker must NOT init at import time -- Celery
forks worker children after importing app.tasks, and Langfuse's OTel
BatchSpanProcessor runs on a background thread that does not survive
fork(). worker_process_init fires post-fork, in each child, which is the
correct place.
"""

import os

import sentry_sdk
from langfuse import Langfuse
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
    _init_langfuse(service)


def flush_observability() -> None:
    """Called from worker_process_shutdown -- Langfuse batches spans on a
    background thread and a Celery prefork child exiting doesn't wait
    around for that thread to drain on its own."""
    if os.getenv("LANGFUSE_PUBLIC_KEY"):
        from langfuse import get_client

        get_client().flush()


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


def _init_langfuse(service: str) -> None:
    # Explicit early return (rather than relying solely on the SDK's own
    # env-var handling) is one of three redundant no-op-safety layers for
    # CI/local dev with no Langfuse project configured -- see
    # LANGFUSE_TRACING_ENABLED below and in tests/conftest.py for the
    # other two. See docs/infra-guide.md.
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return

    tracing_enabled = os.getenv("LANGFUSE_TRACING_ENABLED", "true").lower() != "false"

    Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        environment=os.getenv("SENTRY_ENVIRONMENT", "local"),
        release=os.getenv("IMAGE_TAG"),
        tracing_enabled=tracing_enabled,
    )
