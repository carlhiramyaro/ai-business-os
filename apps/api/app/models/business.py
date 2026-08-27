import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base

# Ledger's market is African SMEs, Ghana first (docs/product-vision.md), so
# an unset currency defaults here rather than staying NULL. This is not
# cosmetic: app/chat_generation.py builds the system prompt from
# business.currency, and a NULL degraded it to "amounts are in the
# business's local currency" -- which made the agent answer "total sales
# amount to 115.0", a bare number with no unit, to an owner making money
# decisions. Found in live v0.6 testing; see docs/decisions.md
# [2026-08-27].
DEFAULT_CURRENCY = "GHS"


class Business(Base):
    __tablename__ = "businesses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    business_name = Column(String, nullable=False)
    industry = Column(String, nullable=True)
    # NOT NULL + both defaults: `default` covers ORM constructions that omit
    # the kwarg (tests, scripts), `server_default` covers raw SQL inserts
    # and the pre-existing rows the migration backfills. Neither helps when
    # a caller passes currency=None EXPLICITLY -- SQLAlchemy treats that as
    # an intentional value, not an omission -- which is exactly what
    # `Business(**payload.model_dump())` in app/routers/business.py does for
    # an omitted optional field, so BusinessCreate defaults it too.
    currency = Column(String, nullable=False, default=DEFAULT_CURRENCY, server_default=DEFAULT_CURRENCY)
    country = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
