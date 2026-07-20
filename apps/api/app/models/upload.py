import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    sales_file_url = Column(String, nullable=False)
    inventory_file_url = Column(String, nullable=False)
    expenses_file_url = Column(String, nullable=False)
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
