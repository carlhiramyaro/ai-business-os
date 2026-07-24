import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    # 'csv' | 'manual' | 'document' -- v0.3 generalizes this table from
    # "CSV upload session" to "ingestion source" (see docs/decisions.md
    # [2026-07-24]); the table/column names below are retained as-is per
    # the frozen-schema rule even though "upload"/"*_file_url" now read as
    # a slight misnomer for manual/document sessions.
    source_type = Column(String, nullable=False, default="csv")
    sales_file_url = Column(String, nullable=True)
    inventory_file_url = Column(String, nullable=True)
    expenses_file_url = Column(String, nullable=True)
    # S3 key for a photographed receipt/invoice; only set when source_type='document'.
    document_url = Column(String, nullable=True)
    # Set by the ingesting task when any row's content_hash collided with a
    # pre-existing row (or another row in the same batch) -- point-in-time,
    # so persisted rather than derived at read time. See migration
    # bb0084e5c354's docstring.
    duplicate_warning = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="PROCESSING")
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class DatasetProfile(Base):
    __tablename__ = "dataset_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("upload_sessions.id"), nullable=False, index=True)
    dataset_type = Column(String, nullable=False)
    total_rows = Column(Integer, nullable=False)
    duplicate_rows = Column(Integer, nullable=False)
    missing_values = Column(Integer, nullable=False)
    date_range_start = Column(Date, nullable=True)
    date_range_end = Column(Date, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ColumnMapping(Base):
    __tablename__ = "column_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("upload_sessions.id"), nullable=False, index=True)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    dataset_type = Column(String, nullable=False)
    source_column_name = Column(String, nullable=False)
    target_field = Column(String, nullable=False)
    confidence_score = Column(Numeric, nullable=False)
    mapping_method = Column(String, nullable=False)
    header_set_hash = Column(String, nullable=False, index=True)
    sample_values = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DocumentExtraction(Base):
    """The document-era sibling of ColumnMapping -- holds a photographed
    receipt/invoice's vision-extracted rows pending user review, before
    they become real sales/inventory/expenses rows via app.ingestion's
    ingest_rows (v0.3, see docs/decisions.md [2026-07-24]). One row per
    document upload_session (a document has exactly one dataset_type,
    chosen by the user at upload time -- unlike a CSV upload's three
    parallel datasets). Deliberately has no independent `status` column,
    mirroring ColumnMapping's precedent: upload_sessions.status
    (PROCESSING -> NEEDS_REVIEW -> COMPLETED/FAILED) is the single source
    of truth for where a session is in its lifecycle."""

    __tablename__ = "document_extractions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_session_id = Column(
        UUID(as_uuid=True), ForeignKey("upload_sessions.id"), nullable=False, unique=True, index=True
    )
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    dataset_type = Column(String, nullable=False)
    # List of canonical camelCase-field dicts (e.g. {"saleDate": "2026-07-24",
    # "productName": "Rice", ...}) -- the same target-field naming
    # column_mappings uses, editable by the user before confirm. Raw
    # (uncast) values; casting happens in ingest_rows at confirm time, same
    # deterministic-vs-LLM split as the CSV path.
    extracted_rows = Column(JSONB, nullable=False)
    overall_confidence = Column(Numeric, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
