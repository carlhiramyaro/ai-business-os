import uuid
from datetime import datetime

from app.schemas.base import CamelModel

# progress isn't a stored column (upload_sessions has no such field in
# erd.md) -- derived at read time from status, same precedent as
# businessHealth in decisions.md.
STATUS_PROGRESS = {"PROCESSING": 50, "NEEDS_REVIEW": 40, "COMPLETED": 100, "FAILED": 0}


class UploadCreateResponse(CamelModel):
    upload_session_id: uuid.UUID
    status: str


class UploadSessionSummary(CamelModel):
    id: uuid.UUID
    status: str
    uploaded_at: datetime


class UploadStatusResponse(CamelModel):
    status: str
    progress: int
    pending_review: list[str] | None = None
    # True when ingestion detected rows whose content_hash matched a
    # pre-existing row (or another row in the same batch) for this
    # business+dataset -- v0.3 dedup safeguard, warn-only (see
    # app/ingestion.py, docs/decisions.md [2026-07-24]).
    duplicate_warning: bool = False


class ColumnMappingResponse(CamelModel):
    id: uuid.UUID
    dataset_type: str
    source_column_name: str
    target_field: str
    confidence_score: float
    mapping_method: str
    sample_values: list | None


class ColumnMappingUpdate(CamelModel):
    target_field: str
