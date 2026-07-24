import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business, get_owned_upload_session
from app.models import (
    AgentOutput,
    AgentRun,
    Business,
    ColumnMapping,
    DatasetProfile,
    Embedding,
    Expense,
    Inventory,
    Report,
    ReportSection,
    Sale,
    UploadSession,
)
from app.schemas.upload import (
    STATUS_PROGRESS,
    ColumnMappingResponse,
    ColumnMappingUpdate,
    UploadCreateResponse,
    UploadSessionSummary,
    UploadStatusResponse,
)
from app.storage import delete_prefix, key_for, upload_fileobj
from app.tasks import MAPPING_CONFIDENCE_THRESHOLD, finalize_upload_task, run_column_mapping_task

router = APIRouter(prefix="/api/v1/businesses/{business_id}/uploads", tags=["uploads"])


def _cascade_delete_upload_session(db: Session, upload_session: UploadSession) -> None:
    """Mirrors endpoints.md's DELETE description ("removes ... parsed data,
    reports, and any associated column mappings"). No ON DELETE CASCADE at
    the DB level (schema is frozen per agent-instructions.md), so children
    are deleted explicitly, deepest first."""
    report_ids = [r.id for r in db.query(Report.id).filter(Report.upload_session_id == upload_session.id)]
    if report_ids:
        agent_run_ids = [
            r.id for r in db.query(AgentRun.id).filter(AgentRun.report_id.in_(report_ids))
        ]
        if agent_run_ids:
            db.query(AgentOutput).filter(AgentOutput.agent_run_id.in_(agent_run_ids)).delete(
                synchronize_session=False
            )
            db.query(AgentRun).filter(AgentRun.id.in_(agent_run_ids)).delete(synchronize_session=False)
        section_ids = [
            s.id for s in db.query(ReportSection.id).filter(ReportSection.report_id.in_(report_ids))
        ]
        # embeddings has no FK to reports/report_sections (source_id is a
        # plain UUID, polymorphic by source_type) -- clean up explicitly so
        # deleted reports don't leave stale chunks feeding chat retrieval.
        db.query(Embedding).filter(Embedding.source_id.in_([*report_ids, *section_ids])).delete(
            synchronize_session=False
        )
        db.query(ReportSection).filter(ReportSection.report_id.in_(report_ids)).delete(synchronize_session=False)
        db.query(Report).filter(Report.id.in_(report_ids)).delete(synchronize_session=False)

    db.query(ColumnMapping).filter(ColumnMapping.upload_session_id == upload_session.id).delete(
        synchronize_session=False
    )
    db.query(DatasetProfile).filter(DatasetProfile.upload_session_id == upload_session.id).delete(
        synchronize_session=False
    )
    db.query(Sale).filter(Sale.upload_session_id == upload_session.id).delete(synchronize_session=False)
    db.query(Inventory).filter(Inventory.upload_session_id == upload_session.id).delete(synchronize_session=False)
    db.query(Expense).filter(Expense.upload_session_id == upload_session.id).delete(synchronize_session=False)


@router.post("/", response_model=UploadCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_upload(
    sales: UploadFile = File(...),
    inventory: UploadFile = File(...),
    expenses: UploadFile = File(...),
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
):
    upload_session = UploadSession(
        business_id=business.id,
        sales_file_url="",
        inventory_file_url="",
        expenses_file_url="",
        status="PROCESSING",
    )
    db.add(upload_session)
    db.flush()  # assigns upload_session.id (default=uuid.uuid4) before we build S3 keys

    for dataset_type, upload_file in (("sales", sales), ("inventory", inventory), ("expenses", expenses)):
        key = key_for(business.id, upload_session.id, dataset_type)
        url = upload_fileobj(upload_file.file, key)
        setattr(upload_session, f"{dataset_type}_file_url", url)

    db.commit()
    db.refresh(upload_session)

    run_column_mapping_task.delay(str(upload_session.id))

    return UploadCreateResponse(upload_session_id=upload_session.id, status=upload_session.status)


@router.get("/", response_model=list[UploadSessionSummary])
def list_uploads(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    return (
        db.query(UploadSession)
        .filter(UploadSession.business_id == business.id)
        .order_by(UploadSession.uploaded_at.desc())
        .all()
    )


@router.get("/{upload_session_id}", response_model=UploadStatusResponse)
def get_upload_status(
    upload_session: UploadSession = Depends(get_owned_upload_session),
    db: Session = Depends(get_db),
):
    pending_review = None
    if upload_session.status == "NEEDS_REVIEW":
        rows = (
            db.query(ColumnMapping.dataset_type)
            .filter(
                ColumnMapping.upload_session_id == upload_session.id,
                ColumnMapping.confidence_score < MAPPING_CONFIDENCE_THRESHOLD,
            )
            .distinct()
            .all()
        )
        pending_review = sorted({row[0] for row in rows})

    return UploadStatusResponse(
        status=upload_session.status,
        progress=STATUS_PROGRESS.get(upload_session.status, 0),
        pending_review=pending_review,
        duplicate_warning=upload_session.duplicate_warning,
    )


@router.delete("/{upload_session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(
    business: Business = Depends(get_owned_business),
    upload_session: UploadSession = Depends(get_owned_upload_session),
    db: Session = Depends(get_db),
):
    delete_prefix(f"businesses/{business.id}/uploads/{upload_session.id}/")
    _cascade_delete_upload_session(db, upload_session)
    db.delete(upload_session)
    db.commit()


@router.get("/{upload_session_id}/column-mappings", response_model=list[ColumnMappingResponse])
def list_column_mappings(
    upload_session: UploadSession = Depends(get_owned_upload_session),
    db: Session = Depends(get_db),
):
    return db.query(ColumnMapping).filter(ColumnMapping.upload_session_id == upload_session.id).all()


@router.patch("/{upload_session_id}/column-mappings/{mapping_id}", response_model=ColumnMappingResponse)
def update_column_mapping(
    mapping_id: uuid.UUID,
    payload: ColumnMappingUpdate,
    upload_session: UploadSession = Depends(get_owned_upload_session),
    db: Session = Depends(get_db),
):
    mapping = db.get(ColumnMapping, mapping_id)
    if mapping is None or mapping.upload_session_id != upload_session.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Column mapping not found")

    mapping.target_field = payload.target_field
    mapping.mapping_method = "user_confirmed"
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/{upload_session_id}/column-mappings/confirm", status_code=status.HTTP_202_ACCEPTED)
def confirm_column_mappings(
    upload_session: UploadSession = Depends(get_owned_upload_session),
    db: Session = Depends(get_db),
):
    upload_session.status = "PROCESSING"
    db.commit()
    finalize_upload_task.delay(str(upload_session.id))
    return {"status": upload_session.status}
