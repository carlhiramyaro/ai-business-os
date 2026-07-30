import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("ai_business_os", broker=REDIS_URL, backend=REDIS_URL, include=["app.tasks"])
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]

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
