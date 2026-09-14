"""Stock-movement ledger operations (v0.7, roadmap.md "Inventory depth").

Current stock is never a stored, mutable number -- it's derived by summing
StockMovement.quantity_delta for a product, the way a bank balance is
derived from its transactions. Every write here is deterministic
arithmetic (unit conversion, sign-by-reason, recount-to-delta), never an
LLM guess -- same deterministic-vs-LLM rule SaleEntry.totalAmount already
follows in app/schemas/entries.py.

This module is the ledger boundary; it does not resolve products (see
app/entities.py's resolve_product) or decide WHEN a movement should be
written -- that's the next v0.7 slice, which wires ingest_rows/data_entry
write paths to call in here the way they already call ingest_rows.
"""

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Product, ProductUnit, StockMovement

# Reasons whose direction is intrinsic to their meaning: a sale always
# decreases stock, a restock always increases it, and so on. "recount" is
# deliberately absent -- it asserts an absolute new count, not a delta, so
# it can't be sign-inferred the same way (see record_recount).
_SIGN_BY_REASON = {"sale": -1, "restock": 1, "loss": -1, "damage": -1}

REASONS = (*_SIGN_BY_REASON.keys(), "recount")


def to_base_quantity(db: Session, product: Product, quantity, unit_name: str | None) -> int:
    """Converts `quantity` in `unit_name` into a whole number of the
    product's base_unit, via that product's declared ProductUnit rows.
    `unit_name=None` (or a value equal to the product's own base_unit)
    means `quantity` is already in base units.

    Rounds to the nearest whole base unit: a fractional conversion factor
    is legitimate (e.g. a "half-carton" unit), a fractional stock count is
    not, and inventory here is always counted in whole units -- same
    posture as Sale.quantity/Inventory.quantity both being Integer. Uses
    Python's round() (round-half-to-even, e.g. round(12.5) == 12) rather
    than round-half-up -- a deliberate default, not an oversight, since a
    fractional conversion factor landing exactly on .5 is a rare input.
    """
    if unit_name is None or unit_name == product.base_unit:
        return round(quantity)

    product_unit = (
        db.query(ProductUnit)
        .filter(ProductUnit.product_id == product.id, ProductUnit.unit_name == unit_name)
        .one_or_none()
    )
    if product_unit is None:
        raise ValueError(f"product {product.id} has no declared unit {unit_name!r}")

    return round(float(quantity) * float(product_unit.conversion_to_base))


def get_current_stock(db: Session, product_id: uuid.UUID) -> int:
    total = (
        db.query(func.coalesce(func.sum(StockMovement.quantity_delta), 0))
        .filter(StockMovement.product_id == product_id)
        .scalar()
    )
    return int(total)


def list_current_stock(db: Session, business_id: uuid.UUID) -> list[dict]:
    """One row per product for the business (even a product with zero
    movements so far -- LEFT JOIN, not INNER), current stock computed with
    one aggregate query rather than get_current_stock called per product.

    The single source of truth for "what does this business have in
    stock" -- backs the `/inventory` page (v0.7 slice 3) and replaces the
    raw, double-counting `Inventory`-row queries chat_tools.py's
    get_inventory_status and report_generation.py previously used (every
    CSV re-upload/re-entry inserted a NEW inventory row with no grouping
    by product; see docs/decisions.md [2026-09-14]).
    """
    rows = (
        db.query(Product, func.coalesce(func.sum(StockMovement.quantity_delta), 0).label("quantity"))
        .outerjoin(StockMovement, StockMovement.product_id == Product.id)
        .filter(Product.business_id == business_id)
        .group_by(Product.id)
        .order_by(Product.name)
        .all()
    )
    return [
        {
            "productId": product.id,
            "productName": product.name,
            "sku": product.sku,
            "category": product.category,
            "quantity": int(quantity),
            "baseUnit": product.base_unit,
            "reorderLevel": product.reorder_level,
            "costPrice": product.cost_price,
            "sellingPrice": product.selling_price,
        }
        for product, quantity in rows
    ]


def record_stock_movement(
    db: Session,
    business_id: uuid.UUID,
    product: Product,
    quantity,
    *,
    reason: str,
    unit_name: str | None = None,
    source_type: str | None = None,
    source_id=None,
    note: str | None = None,
) -> StockMovement:
    """Appends one signed movement to the ledger. `quantity` is a positive
    count in `unit_name` (the product's base_unit if omitted) -- direction
    is derived from `reason`, not asked of the caller, so a producer can't
    accidentally restock by passing a negative sale quantity.

    Not valid for reason="recount" (an absolute assertion, not a delta):
    use record_recount for that.
    """
    if reason not in _SIGN_BY_REASON:
        raise ValueError(
            f"record_stock_movement can't infer a sign for reason {reason!r}; "
            "use record_recount for recounts, or one of "
            f"{sorted(_SIGN_BY_REASON)} otherwise"
        )

    base_quantity = to_base_quantity(db, product, quantity, unit_name)
    delta = _SIGN_BY_REASON[reason] * abs(base_quantity)

    movement = StockMovement(
        business_id=business_id,
        product_id=product.id,
        quantity_delta=delta,
        reason=reason,
        source_type=source_type,
        source_id=source_id,
        note=note,
    )
    db.add(movement)
    db.flush()
    return movement


def record_recount(
    db: Session,
    business_id: uuid.UUID,
    product: Product,
    new_quantity,
    *,
    unit_name: str | None = None,
    source_type: str | None = None,
    source_id=None,
    note: str | None = None,
) -> StockMovement:
    """A recount asserts an absolute new count ("we counted 45"), not a
    delta -- this reads the current ledger-derived stock, computes the
    signed difference, and appends ONE movement for it. A recount that
    matches reality is therefore a correct zero-delta movement (still
    recorded, so "we recounted and confirmed" stays visible in the ledger)
    rather than silently skipped.
    """
    base_new_quantity = to_base_quantity(db, product, new_quantity, unit_name)
    delta = base_new_quantity - get_current_stock(db, product.id)

    movement = StockMovement(
        business_id=business_id,
        product_id=product.id,
        quantity_delta=delta,
        reason="recount",
        source_type=source_type,
        source_id=source_id,
        note=note,
    )
    db.add(movement)
    db.flush()
    return movement
