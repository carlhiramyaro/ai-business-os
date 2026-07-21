import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class Customer(Base):
    """First-class customer entity, resolved from sales data at ingestion
    (see app/entities.py). `name` keeps the first-seen display casing;
    `normalized_name` is the dedup key ("Ama Mensah" == "ama  mensah")."""

    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("business_id", "normalized_name", name="uq_customers_business_normalized_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Supplier(Base):
    """First-class supplier entity, resolved from inventory data at
    ingestion. No phone yet — inventory CSVs carry only a supplier name;
    contact fields arrive with a data source for them (additive migration
    then)."""

    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("business_id", "normalized_name", name="uq_suppliers_business_normalized_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
