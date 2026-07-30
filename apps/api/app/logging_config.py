"""Structured logging (structlog), shared by both processes -- the FastAPI
app (via main.py) and the Celery worker/beat (via app/celery_app.py's
worker_process_init/beat_init signal handlers). See docs/infra-guide.md's
structured logging section for the concepts.

Renders as JSON everywhere except local dev (ENVIRONMENT unset/"local"),
where a human-readable console renderer is used instead. Also routes
stdlib loggers -- uvicorn's access/error logs, Celery's own logging --
through the same JSON formatter via structlog.stdlib.ProcessorFormatter,
so a CloudWatch log group doesn't end up half-JSON, half-plaintext with
Logs Insights queries silently missing the plaintext half.
"""

import logging
import os
import sys

import structlog

_configured = False


def configure_logging(service: str) -> None:
    """Idempotent -- safe to call from multiple entry points (main.py's
    module body, and Celery's worker_process_init/beat_init signals, which
    can both fire in a process that already ran this once)."""
    global _configured
    if _configured:
        return
    _configured = True

    environment = os.getenv("ENVIRONMENT", "local")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Shared by both structlog-native calls and stdlib logging calls routed
    # through ProcessorFormatter's foreign_pre_chain (below) -- this is what
    # makes uvicorn's/Celery's own log lines carry the same shape as ours.
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.dev.ConsoleRenderer() if environment == "local" else structlog.processors.JSONRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # uvicorn and Celery each configure their own loggers at startup --
    # relying on import order alone is fragile (see the module docstring),
    # so explicitly repoint them at our handler rather than their defaults.
    # propagate=False stops them from ALSO going through the root logger's
    # handler a second time (double-logging every line).
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery"):
        lg = logging.getLogger(logger_name)
        lg.handlers = [handler]
        lg.propagate = False

    structlog.get_logger("app.logging_config").info(
        "logging_configured", service=service, environment=environment, log_level=log_level
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
