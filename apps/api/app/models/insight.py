import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class Insight(Base):
    """v0.4 slice 2 (roadmap.md "Proactive intelligence") -- one row per
    detected signal (app/signals.py) after LLM narration
    (app/insights_generation.py). fingerprint is a deterministic dedup key
    (business_id + insight_type + anchor, e.g. an ISO week or a product
    name) so a repeated scheduled run never creates duplicates for a signal
    that's still true -- same idempotency idea as ingestion's content_hash,
    see docs/decisions.md."""

    __tablename__ = "insights"
    __table_args__ = (UniqueConstraint("business_id", "fingerprint", name="uq_insights_business_fingerprint"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    insight_type = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    # The deterministic figures the narration is grounded in -- audit trail,
    # same spirit as messages.tool_calls.
    metrics = Column(JSONB, nullable=False)
    fingerprint = Column(String, nullable=False, index=True)
    is_read = Column(Boolean, nullable=False, default=False)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
