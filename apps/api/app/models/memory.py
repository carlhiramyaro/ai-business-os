import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class BusinessFact(Base):
    """v0.4 slice 3 (roadmap.md "Business memory v1") -- a durable fact
    about a business (e.g. "December is peak season"), written via the
    chat agent's remember_business_fact tool (app/chat_generation.py) and
    embedded (app/embedding_generation.py, source_type="business_fact") so
    it's retrievable both by chat's existing search_business_context tool
    and by insight narration (app/insights_generation.py). See
    docs/decisions.md."""

    __tablename__ = "business_facts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    # "chat" is the only source in v1 (kept a plain string, not an enum, for
    # future sources like system-detected patterns).
    source = Column(String, nullable=False, default="chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
