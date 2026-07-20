import uuid
from datetime import date, datetime

from app.schemas.base import CamelModel


class ReportSummary(CamelModel):
    id: uuid.UUID
    created_at: datetime
    period_start: date
    period_end: date
    status: str
    business_health: str


class ReportDetail(CamelModel):
    period_start: date
    period_end: date
    status: str
    summary: str | None
    risks: list[str]
    opportunities: list[str]
    forecast: str | None
    action_plan: list[str]


class ReportGenerateRequest(CamelModel):
    period_start: date
    period_end: date


class ReportGenerateResponse(CamelModel):
    report_id: uuid.UUID
    status: str
