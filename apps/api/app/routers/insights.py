import os

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business, get_owned_insight, require_worker_online
from app.models import Business, Insight
from app.rate_limit import RateLimit
from app.schemas.insights import InsightSummary, InsightUpdateRequest, RunAnalysisResponse, UnreadCountResponse
from app.tasks import run_business_analysis_task

router = APIRouter(prefix="/api/v1/businesses/{business_id}/insights", tags=["insights"])

# v0.5 slice 3 (multi-tenant hardening, docs/decisions.md [2026-08-01]): a
# cost circuit-breaker, not a security limit -- one narrate_insight LLM
# call per detected signal, unbounded per run.
_RATE_LIMIT_INSIGHTS = os.getenv("RATE_LIMIT_INSIGHTS", "10/hour")


@router.get("/", response_model=list[InsightSummary])
def list_insights(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    return (
        db.query(Insight).filter(Insight.business_id == business.id).order_by(Insight.created_at.desc()).all()
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    count = (
        db.query(Insight).filter(Insight.business_id == business.id, Insight.is_read.is_(False)).count()
    )
    return UnreadCountResponse(unread_count=count)


@router.patch("/{insight_id}", response_model=InsightSummary)
def update_insight(
    payload: InsightUpdateRequest,
    insight: Insight = Depends(get_owned_insight),
    db: Session = Depends(get_db),
):
    insight.is_read = payload.read
    db.commit()
    db.refresh(insight)
    return insight


@router.post(
    "/run",
    response_model=RunAnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(RateLimit(_RATE_LIMIT_INSIGHTS, "insights"))],
)
def run_analysis(
    business: Business = Depends(get_owned_business),
    _worker_check: None = Depends(require_worker_online),
):
    """On-demand trigger, so analysis can be demoed/tested without waiting
    for the next beat tick -- mirrors POST /reports/generate's async
    202-and-poll shape (there's nothing to poll here since results just
    land in the feed, but the same "don't block the request on an LLM
    call" reasoning applies -- see learning-guide.md 2.6)."""
    run_business_analysis_task.delay(str(business.id))
    return RunAnalysisResponse(status="PROCESSING")
