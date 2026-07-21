import uuid

from sqlalchemy import Column, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Sale(Base):
    __tablename__ = "sales"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("upload_sessions.id"), nullable=False, index=True)
    sale_date = Column(Date, nullable=True)
    product_name = Column(String, nullable=True)
    category = Column(String, nullable=True)
    quantity = Column(Integer, nullable=True)
    unit_price = Column(Numeric, nullable=True)
    discount = Column(Numeric, nullable=True)
    total_amount = Column(Numeric, nullable=True)
    customer_name = Column(String, nullable=True)
    payment_method = Column(String, nullable=True)
    raw_row_number = Column(Integer, nullable=False)


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("upload_sessions.id"), nullable=False, index=True)
    product_name = Column(String, nullable=True)
    category = Column(String, nullable=True)
    quantity = Column(Integer, nullable=True)
    reorder_level = Column(Integer, nullable=True)
    supplier = Column(String, nullable=True)
    cost_price = Column(Numeric, nullable=True)
    selling_price = Column(Numeric, nullable=True)


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("upload_sessions.id"), nullable=False, index=True)
    expense_date = Column(Date, nullable=True)
    category = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
    amount = Column(Numeric, nullable=True)
    description = Column(String, nullable=True)
