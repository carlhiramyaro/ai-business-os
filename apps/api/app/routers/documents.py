import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business, require_worker_online
from app.ingestion import RECORD_FIELD_MAP, ingest_rows
from app.models import Business, DocumentExtraction, UploadSession
from app.schemas.documents import (
    DocumentConfirmResponse,
    DocumentCreateResponse,
    DocumentRowsUpdate,
    DocumentStatusResponse,
)
from app.schemas.upload import STATUS_PROGRESS
from app.storage import document_key_for, upload_fileobj
from app.tasks import extract_document_task

router = APIRouter(prefix="/api/v1/businesses/{business_id}/documents", tags=["documents"])

VALID_DATASET_TYPES = ("sales", "inventory", "expenses")

# Document processing (v0.3, roadmap.md): photograph a receipt/invoice ->
# vision-LLM extraction -> a review screen (the document-era sibling of the
# column-mapping review) -> confirm -> the same app.ingestion.ingest_rows
# boundary CSV uploads and manual entries use. See docs/decisions.md
# [2026-07-24].


def _get_owned_document_session(
    upload_session_id: uuid.UUID,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
) -> UploadSession:
    session = db.get(UploadSession, upload_session_id)
    if session is None or session.business_id != business.id or session.source_type != "document":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return session


def _get_extraction(db: Session, session: UploadSession) -> DocumentExtraction:
    extraction = (
        db.query(DocumentExtraction).filter(DocumentExtraction.upload_session_id == session.id).one_or_none()
    )
    if extraction is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Extraction is still processing")
    return extraction


@router.post("/", response_model=DocumentCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_document(
    dataset_type: str = Form(..., alias="datasetType"),
    image: UploadFile = File(...),
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
    _worker_check: None = Depends(require_worker_online),
):
    if dataset_type not in VALID_DATASET_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"datasetType must be one of {VALID_DATASET_TYPES}",
        )

    session = UploadSession(business_id=business.id, source_type="document", status="PROCESSING")
    db.add(session)
    db.flush()  # assigns session.id before we build the S3 key

    key = document_key_for(business.id, session.id)
    url = upload_fileobj(image.file, key)
    session.document_url = url
    session.processing_started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)

    extract_document_task.delay(str(session.id), dataset_type, image.content_type or "image/jpeg")

    return DocumentCreateResponse(upload_session_id=session.id, status=session.status)


@router.get("/{upload_session_id}", response_model=DocumentStatusResponse)
def get_document_status(
    session: UploadSession = Depends(_get_owned_document_session),
    db: Session = Depends(get_db),
):
    extraction = (
        db.query(DocumentExtraction).filter(DocumentExtraction.upload_session_id == session.id).one_or_none()
    )
    return DocumentStatusResponse(
        status=session.status,
        progress=STATUS_PROGRESS.get(session.status, 0),
        dataset_type=extraction.dataset_type if extraction else None,
        extracted_rows=extraction.extracted_rows if extraction else None,
        overall_confidence=float(extraction.overall_confidence)
        if extraction is not None and extraction.overall_confidence is not None
        else None,
    )


@router.patch("/{upload_session_id}", response_model=DocumentStatusResponse)
def update_document_rows(
    payload: DocumentRowsUpdate,
    session: UploadSession = Depends(_get_owned_document_session),
    db: Session = Depends(get_db),
):
    extraction = _get_extraction(db, session)
    extraction.extracted_rows = payload.extracted_rows
    db.commit()
    db.refresh(extraction)

    return DocumentStatusResponse(
        status=session.status,
        progress=STATUS_PROGRESS.get(session.status, 0),
        dataset_type=extraction.dataset_type,
        extracted_rows=extraction.extracted_rows,
        overall_confidence=float(extraction.overall_confidence) if extraction.overall_confidence is not None else None,
    )


@router.post("/{upload_session_id}/confirm", response_model=DocumentConfirmResponse)
def confirm_document(
    session: UploadSession = Depends(_get_owned_document_session),
    db: Session = Depends(get_db),
):
    extraction = _get_extraction(db, session)

    field_map = RECORD_FIELD_MAP[extraction.dataset_type]
    rows = [
        {field_map[field]: value for field, value in row.items() if field in field_map}
        for row in extraction.extracted_rows
    ]

    summary = ingest_rows(db, session.business_id, session.id, extraction.dataset_type, rows)
    if summary.duplicate_count:
        session.duplicate_warning = True
    session.status = "COMPLETED"
    session.completed_at = datetime.now(timezone.utc)
    db.commit()

    return DocumentConfirmResponse(status=session.status, duplicate_warning=session.duplicate_warning)
