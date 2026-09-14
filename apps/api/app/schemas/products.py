import uuid
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel

# Reasons a manual adjustment can state -- "sale" is deliberately excluded,
# since a sale's stock movement comes from the sales-entry pipeline
# (app/ingestion.py), not a direct adjustment here. "repack" is also
# excluded -- it's a paired movement against two products, handled by its
# own request/response shape (RepackRequest/RepackResponse) below, not a
# single-product adjustment.
AdjustmentReason = Literal["restock", "recount", "loss", "damage"]


class ProductItem(CamelModel):
    id: uuid.UUID
    name: str
    sku: str | None
    category: str | None
    # Decimal, not int: a loose product sold by weight (2.3 kg) needs a
    # fractional running stock. See docs/decisions.md [2026-09-14].
    quantity: Decimal
    base_unit: str
    reorder_level: Decimal | None
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
    reorder_level: Decimal | None = None
    cost_price: Decimal | None = None
    selling_price: Decimal | None = None


class StockAdjustmentRequest(CamelModel):
    reason: AdjustmentReason
    # For "recount": the new absolute count. For every other reason: a
    # positive count in the product's own base_unit (direction comes from
    # `reason`, not the sign here -- see app/inventory.py.record_stock_movement).
    quantity: Decimal
    note: str | None = Field(default=None, max_length=500)


class StockAdjustmentResponse(CamelModel):
    id: uuid.UUID
    product_id: uuid.UUID
    quantity_delta: Decimal
    reason: str
    current_stock: Decimal


class SuggestedSkuResponse(CamelModel):
    sku: str


# Pack relationships (docs/decisions.md [2026-09-14]) -- "1 Coke Case = 24
# Coke Can" as an explicit link between two independent products, replacing
# ProductUnit's per-transaction unit conversion.


class PackRelationshipRequest(CamelModel):
    unit_product_id: uuid.UUID
    units_per_pack: Decimal = Field(gt=0)


class PackRelationshipItem(CamelModel):
    id: uuid.UUID
    pack_product_id: uuid.UUID
    unit_product_id: uuid.UUID
    unit_product_name: str
    units_per_pack: Decimal


class RepackRequest(CamelModel):
    quantity: Decimal = Field(gt=0)
    direction: Literal["break", "assemble"]
    note: str | None = Field(default=None, max_length=500)


class RepackResponse(CamelModel):
    pack_product_id: uuid.UUID
    pack_current_stock: Decimal
    unit_product_id: uuid.UUID
    unit_current_stock: Decimal
