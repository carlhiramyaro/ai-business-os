import uuid

from app.schemas.base import CamelModel


class DocumentCreateResponse(CamelModel):
    upload_session_id: uuid.UUID
    status: str


class DocumentStatusResponse(CamelModel):
    status: str
    progress: int
    # None until extraction has run (status PROCESSING); populated once
    # NEEDS_REVIEW/COMPLETED. Rows are raw, uncast canonical-field dicts --
    # see app/document_extraction.py.
    dataset_type: str | None = None
    extracted_rows: list[dict] | None = None
    overall_confidence: float | None = None


class DocumentRowsUpdate(CamelModel):
    extracted_rows: list[dict]


class DocumentConfirmResponse(CamelModel):
    status: str
    duplicate_warning: bool
