import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel

# Reasons a manual adjustment can state -- "sale" is deliberately excluded,
# since a sale's stock movement comes from the sales-entry pipeline
# (app/ingestion.py), not a direct adjustment here.
AdjustmentReason = Literal["restock", "recount", "loss", "damage"]


class ProductItem(CamelModel):
    id: uuid.UUID
    name: str
    sku: str | None
    category: str | None
    quantity: int
    base_unit: str
    reorder_level: int | None
    cost_price: Decimal | None
    selling_price: Decimal | None
    low_stock: bool


class ProductUpdate(CamelModel):
    """Every field optional -- only what's provided gets changed, the same
    last-non-empty-value-wins shape resolve_product already uses for these
    same fields when a new sale/inventory entry supplies them."""

    sku: str | None = None
    category: str | None = None
    base_unit: str | None = None
    reorder_level: int | None = None
    cost_price: Decimal | None = None
    selling_price: Decimal | None = None


class StockAdjustmentRequest(CamelModel):
    reason: AdjustmentReason
    # For "recount": the new absolute count. For every other reason: a
    # positive count in `unit_name` (direction comes from `reason`, not
    # the sign here -- see app/inventory.py.record_stock_movement).
    quantity: int
    unit_name: str | None = None
    note: str | None = Field(default=None, max_length=500)


class StockAdjustmentResponse(CamelModel):
    id: uuid.UUID
    product_id: uuid.UUID
    quantity_delta: int
    reason: str
    current_stock: int


class ProductUnitRequest(CamelModel):
    unit_name: str = Field(min_length=1)
    conversion_to_base: Decimal


class ProductUnitItem(CamelModel):
    id: uuid.UUID
    unit_name: str
    conversion_to_base: Decimal
    created_at: datetime
