"""Detects whether any Celery worker is actually listening on the broker.

Every route that calls `some_task.delay(...)` hands work to Redis and trusts
a worker to pick it up. If none is running, the task just sits queued
forever and whatever the route already created (an UploadSession row, S3
objects, a Report row) is stuck in PROCESSING/PENDING with no error anywhere
-- exactly what happened when nothing consumed the queue for the "v0.4 test
shop" upload (see docs/decisions.md). This module lets routes fail fast
instead.
"""

import structlog

from app.celery_app import celery_app

logger = structlog.get_logger(__name__)


def workers_online(timeout: float = 0.5) -> bool:
    """True if at least one Celery worker replies to a broadcast ping.

    In tests (and anywhere `task_always_eager` is set, per
    tests/conftest.py's `_celery_eager` fixture), Celery runs tasks
    synchronously in-process and never touches the broker at all -- there is
    no worker to ping, and none is needed, so that mode always reports
    "online" rather than false-flagging every eager-mode call as down.
    """
    if celery_app.conf.task_always_eager:
        return True
    try:
        replies = celery_app.control.ping(timeout=timeout)
    except Exception as exc:
        # Behavior unchanged (still reports "down") -- but a broker outage
        # used to be indistinguishable from "no worker running" with zero
        # trace of the real cause, and this is the first thing anyone
        # checks during an incident. See docs/decisions.md.
        logger.warning("worker_ping_failed", error=str(exc), exc_info=True)
        return False
    return bool(replies)
