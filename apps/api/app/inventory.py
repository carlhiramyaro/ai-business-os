"""Stock-movement ledger operations (v0.7, roadmap.md "Inventory depth").

Current stock is never a stored, mutable number -- it's derived by summing
StockMovement.quantity_delta for a product, the way a bank balance is
derived from its transactions. Every write here is deterministic
arithmetic (sign-by-reason, recount-to-delta, repack), never an LLM guess
-- same deterministic-vs-LLM rule SaleEntry.totalAmount already follows in
app/schemas/entries.py.

Quantities are Decimal, not int: one shared column across every product,
and some (loose meat/produce/fuel sold by weight or volume) are legitimately
fractional -- see docs/decisions.md [2026-09-14].

This module is the ledger boundary; it does not resolve products (see
app/entities.py's resolve_product) or decide WHEN a movement should be
written -- that's app/ingestion.py's job for sales/inventory rows.
"""

import uuid
from decimal import Decimal
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import PackRelationship, Product, StockMovement

# Reasons whose direction is intrinsic to their meaning: a sale always
# decreases stock, a restock always increases it, and so on. "recount" and
# "repack" are deliberately absent -- neither is sign-inferable from the
# reason alone (see record_recount, record_repack).
_SIGN_BY_REASON = {"sale": -1, "restock": 1, "loss": -1, "damage": -1}

REASONS = (*_SIGN_BY_REASON.keys(), "recount", "repack")


def get_current_stock(db: Session, product_id: uuid.UUID) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(StockMovement.quantity_delta), 0))
        .filter(StockMovement.product_id == product_id)
        .scalar()
    )
    return Decimal(total)


def get_pack_relationship(db: Session, pack_product_id: uuid.UUID) -> PackRelationship | None:
    return db.query(PackRelationship).filter(PackRelationship.pack_product_id == pack_product_id).one_or_none()


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
            "quantity": Decimal(quantity),
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
    source_type: str | None = None,
    source_id=None,
    note: str | None = None,
) -> StockMovement:
    """Appends one signed movement to the ledger, in the product's own
    base_unit -- direction is derived from `reason`, not asked of the
    caller, so a producer can't accidentally restock by passing a negative
    sale quantity.

    Not valid for reason="recount" (an absolute assertion, not a delta) or
    "repack" (a paired movement against TWO products): use record_recount
    or record_repack for those.
    """
    if reason not in _SIGN_BY_REASON:
        raise ValueError(
            f"record_stock_movement can't infer a sign for reason {reason!r}; "
            "use record_recount for recounts, record_repack for a pack/unit "
            f"conversion, or one of {sorted(_SIGN_BY_REASON)} otherwise"
        )

    delta = _SIGN_BY_REASON[reason] * abs(Decimal(str(quantity)))

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
    delta = Decimal(str(new_quantity)) - get_current_stock(db, product.id)

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


def record_repack(
    db: Session,
    business_id: uuid.UUID,
    pack_product: Product,
    quantity,
    *,
    direction: Literal["break", "assemble"],
    source_type: str | None = "manual",
    note: str | None = None,
) -> tuple[StockMovement, StockMovement]:
    """Converts stock between a pack product and its declared unit product
    (see PackRelationship) -- "break" opens `quantity` packs into
    `quantity * units_per_pack` units (a case into cans); "assemble" is the
    reverse (cans back into a sealed case). Always an explicit, deliberate
    action a person takes, never implicit at sale time -- whether to crack
    open a sealed case for one customer or hold it for a bulk buyer is a
    business judgment call, not something to infer. See docs/decisions.md
    [2026-09-14].

    Writes two linked movements in one call, sharing a `source_id` so
    they're traceable as one event -- same "not this row, use the shared
    id" reasoning app.ingestion.py already applies to a whole CSV batch's
    recount. Like every other movement here, this doesn't block on
    insufficient stock (breaking more cases than you have goes negative,
    same as an oversold sale) -- consistent with the rest of the ledger's
    posture, not a new exception.
    """
    relationship = get_pack_relationship(db, pack_product.id)
    if relationship is None:
        raise ValueError(f"product {pack_product.id} has no declared pack relationship")

    unit_product = db.get(Product, relationship.unit_product_id)
    quantity = Decimal(str(quantity))
    unit_magnitude = quantity * relationship.units_per_pack
    if direction == "break":
        pack_delta, unit_delta = -quantity, unit_magnitude
    elif direction == "assemble":
        pack_delta, unit_delta = quantity, -unit_magnitude
    else:
        raise ValueError(f"record_repack direction must be 'break' or 'assemble', got {direction!r}")

    repack_id = uuid.uuid4()
    pack_movement = StockMovement(
        business_id=business_id,
        product_id=pack_product.id,
        quantity_delta=pack_delta,
        reason="repack",
        source_type=source_type,
        source_id=repack_id,
        note=note,
    )
    unit_movement = StockMovement(
        business_id=business_id,
        product_id=unit_product.id,
        quantity_delta=unit_delta,
        reason="repack",
        source_type=source_type,
        source_id=repack_id,
        note=note,
    )
    db.add(pack_movement)
    db.add(unit_movement)
    db.flush()
    return pack_movement, unit_movement
