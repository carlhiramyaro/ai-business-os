import uuid
from datetime import date, datetime
from typing import Any

from app.schemas.base import CamelModel


class InsightSummary(CamelModel):
    id: uuid.UUID
    insight_type: str
    severity: str
    title: str
    body: str
    metrics: dict[str, Any]
    is_read: bool
    period_start: date | None
    period_end: date | None
    created_at: datetime


class UnreadCountResponse(CamelModel):
    unread_count: int


class InsightUpdateRequest(CamelModel):
    read: bool


class RunAnalysisResponse(CamelModel):
    status: str
