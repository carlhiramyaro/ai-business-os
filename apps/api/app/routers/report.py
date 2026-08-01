import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business, get_owned_report, require_worker_online
from app.embedding_generation import delete_embeddings_for_report
from app.models import AgentOutput, AgentRun, Business, Report, ReportSection
from app.rate_limit import RateLimit
from app.schemas.report import ReportDetail, ReportGenerateRequest, ReportGenerateResponse, ReportSummary
from app.tasks import generate_report_task

router = APIRouter(prefix="/api/v1/businesses/{business_id}/reports", tags=["reports"])

# v0.5 slice 3 (multi-tenant hardening, docs/decisions.md [2026-08-01]): a
# cost circuit-breaker (4 concurrent LLM analyst calls + a manager call
# per report), not a security limit.
_RATE_LIMIT_REPORTS = os.getenv("RATE_LIMIT_REPORTS", "10/hour")


def _business_health(db: Session, report_id) -> str:
    """Derived at read time, same precedent as upload progress -- see
    decisions.md [2026-07-12] #1 and [2026-07-17] (uploads)."""
    risk_count = (
        db.query(ReportSection)
        .filter(ReportSection.report_id == report_id, ReportSection.section_type == "risk")
        .count()
    )
    if risk_count == 0:
        return "Good"
    if risk_count <= 2:
        return "Fair"
    return "Needs Attention"


@router.get("/", response_model=list[ReportSummary])
def list_reports(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    reports = db.query(Report).filter(Report.business_id == business.id).order_by(Report.created_at.desc()).all()
    return [
        ReportSummary(
            id=report.id,
            created_at=report.created_at,
            period_start=report.period_start,
            period_end=report.period_end,
            status=report.status,
            business_health=_business_health(db, report.id),
        )
        for report in reports
    ]


@router.post(
    "/generate",
    response_model=ReportGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(RateLimit(_RATE_LIMIT_REPORTS, "reports"))],
)
def generate_report_endpoint(
    payload: ReportGenerateRequest,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
    _worker_check: None = Depends(require_worker_online),
):
    if payload.period_start > payload.period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="periodStart must be on or before periodEnd"
        )

    report = Report(
        business_id=business.id,
        upload_session_id=None,
        period_start=payload.period_start,
        period_end=payload.period_end,
        status="PENDING",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    generate_report_task.delay(str(report.id))

    return ReportGenerateResponse(report_id=report.id, status=report.status)


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(report: Report = Depends(get_owned_report), db: Session = Depends(get_db)):
    sections = (
        db.query(ReportSection)
        .filter(ReportSection.report_id == report.id)
        .order_by(ReportSection.order_index)
        .all()
    )
    grouped: dict[str, list[str]] = {"risk": [], "opportunity": [], "action_item": []}
    for section in sections:
        grouped[section.section_type].append(section.content)

    return ReportDetail(
        period_start=report.period_start,
        period_end=report.period_end,
        status=report.status,
        summary=report.executive_summary,
        risks=grouped["risk"],
        opportunities=grouped["opportunity"],
        forecast=report.forecast,
        action_plan=grouped["action_item"],
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report: Report = Depends(get_owned_report), db: Session = Depends(get_db)):
    agent_run_ids = [row.id for row in db.query(AgentRun.id).filter(AgentRun.report_id == report.id)]
    if agent_run_ids:
        db.query(AgentOutput).filter(AgentOutput.agent_run_id.in_(agent_run_ids)).delete(synchronize_session=False)
        db.query(AgentRun).filter(AgentRun.id.in_(agent_run_ids)).delete(synchronize_session=False)
    delete_embeddings_for_report(db, report.id)
    db.query(ReportSection).filter(ReportSection.report_id == report.id).delete(synchronize_session=False)
    db.delete(report)
    db.commit()
