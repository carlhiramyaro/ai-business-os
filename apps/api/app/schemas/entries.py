import uuid
from datetime import date
from decimal import Decimal

from app.schemas.base import CamelModel


class SaleEntry(CamelModel):
    sale_date: date
    product_name: str
    category: str | None = None
    # Decimal, not int: a loose product sold by weight (2.3 kg) needs a
    # fractional quantity. See docs/decisions.md [2026-09-14].
    quantity: Decimal
    unit_price: Decimal | None = None
    discount: Decimal | None = None
    # If omitted, computed server-side as quantity * unitPrice - discount --
    # a deterministic computation, not an LLM guess (CLAUDE.md's
    # deterministic-vs-LLM rule), so the mobile form can skip asking for it
    # when unitPrice is given.
    total_amount: Decimal | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    payment_method: str | None = None


class ExpenseEntry(CamelModel):
    expense_date: date
    category: str
    vendor: str | None = None
    amount: Decimal
    description: str | None = None


class InventoryEntry(CamelModel):
    product_name: str
    category: str | None = None
    quantity: Decimal
    reorder_level: Decimal | None = None
    supplier: str | None = None
    cost_price: Decimal | None = None
    selling_price: Decimal | None = None


class EntryCreateResponse(CamelModel):
    id: uuid.UUID
    duplicate_warning: bool
