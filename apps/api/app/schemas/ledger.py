import uuid
from datetime import date
from decimal import Decimal

from app.schemas.base import CamelModel

# v0.7 slice 3 (roadmap.md "Inventory depth"): plain read-only list views
# for sales/expenses, closing the "I can only see my own data by asking
# chat" gap for the two datasets the new /inventory page doesn't cover.
# Deliberately read-only -- no update/delete here, matching the roadmap's
# "kept deliberately simple... rather than growing into a second
# reporting surface."


class SaleListItem(CamelModel):
    id: uuid.UUID
    sale_date: date | None
    product_name: str | None
    quantity: int | None
    unit_price: Decimal | None
    total_amount: Decimal | None
    customer_name: str | None
    payment_method: str | None


class ExpenseListItem(CamelModel):
    id: uuid.UUID
    expense_date: date | None
    category: str | None
    vendor: str | None
    amount: Decimal | None
    description: str | None
