import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class Product(Base):
    """First-class product entity (v0.7, roadmap.md "Inventory depth"),
    resolved from sale/inventory-entry product names the same way
    Customer/Supplier are -- see app/entities.py's resolve_product. This
    replaces the string-only canonicalize_product_name stopgap
    (docs/decisions.md [2026-08-27]) for every v0.7 write path; that
    function stays as-is for the pre-v0.7 sales/inventory rows that only
    ever carried a product_name string.

    Current stock is deliberately NOT a column here -- it's derived by
    summing StockMovement (see app/inventory.py's get_current_stock), the
    same way a bank balance is derived from its transactions rather than
    trusted as a raw mutable field the ledger could silently drift from.
    """

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("business_id", "normalized_name", name="uq_products_business_normalized_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)
    sku = Column(String, nullable=True)
    category = Column(String, nullable=True)
    # The unit stock is tracked/reported in, e.g. "piece". Every quantity
    # entered in a different (product_units-declared) unit is converted to
    # this one before a StockMovement is written.
    base_unit = Column(String, nullable=False, server_default="unit")
    # Numeric, not Integer: a weight/volume-tracked product (loose meat by
    # the kg) has a fractional reorder point too, e.g. "reorder below 2.5
    # kg" -- see docs/decisions.md [2026-09-14], "pack relationships".
    reorder_level = Column(Numeric, nullable=True)
    cost_price = Column(Numeric, nullable=True)
    selling_price = Column(Numeric, nullable=True)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ProductUnit(Base):
    """DEPRECATED (docs/decisions.md [2026-09-14]): per-transaction unit
    conversion on a single product turned out to be a confusing setup
    flow (declare a conversion factor before you can use it, disconnected
    from the sale/restock you were trying to record) for a mental model
    ("I stock cases, I sell cans") better served by two separate,
    explicitly-linked products -- see PackRelationship below. No
    application code writes or reads this table anymore; kept rather than
    dropped per the schema-frozen rule (docs/agent-instructions.md), not
    because it's still meaningful.
    """

    __tablename__ = "product_units"
    __table_args__ = (UniqueConstraint("product_id", "unit_name", name="uq_product_units_product_unit_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    unit_name = Column(String, nullable=False)
    conversion_to_base = Column(Numeric, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StockMovement(Base):
    """Append-only ledger of every quantity change against a product --
    current stock is SUM(quantity_delta) per product (app/inventory.py's
    get_current_stock), never a mutable field. quantity_delta is signed and
    already in the product's base_unit by the time it's written here; the
    unit the owner actually typed/entered is not retained (matches how
    SaleEntry.totalAmount is computed once at write time rather than kept
    re-derivable).

    source_type/source_id record what produced a movement (e.g.
    source_type="sale", source_id=<sales.id>) without a separate FK per
    producer -- the same shape as content_hash-based dedup, which also
    deliberately avoids a rigid one-FK-per-source design. Both are
    nullable: a bare manual adjustment has nothing else to point at.
    """

    __tablename__ = "stock_movements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    # Numeric, not Integer: a can or a case is always a whole number, but
    # loose meat/produce/fuel sold by weight or volume (2.3 kg) is not --
    # one shared column across every product, so it has to accommodate
    # the fractional case even though most rows will be whole numbers.
    # See docs/decisions.md [2026-09-14].
    quantity_delta = Column(Numeric, nullable=False)
    # 'sale' | 'restock' | 'recount' | 'loss' | 'damage' | 'repack'
    reason = Column(String, nullable=False)
    # what produced this movement: 'sale' | 'upload_session' | 'manual' | 'repack'
    source_type = Column(String, nullable=True)
    source_id = Column(UUID(as_uuid=True), nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PackRelationship(Base):
    """Declares that one product is a sealed pack of another -- "1 Coke
    Case = 24 Coke Can" -- so the two can be sold independently (each its
    own Product, its own stock_movements, its own price/reorder level)
    while still letting an owner convert between them with one explicit
    action (app/inventory.py's record_repack) instead of a disconnected
    per-transaction unit conversion. See docs/decisions.md [2026-09-14]
    for why this replaced ProductUnit.

    `pack_product_id` is unique: a product is a pack of at most one other
    product (a case is a case of cans, not simultaneously a case of two
    different things). Nothing stops a `unit_product` from itself being a
    `pack_product` in a second relationship (a pallet of cases of cans) --
    each repack is still one explicit, independent action; there is no
    multi-level "break a pallet straight into cans" shortcut.
    """

    __tablename__ = "pack_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    pack_product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, unique=True, index=True
    )
    unit_product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    # How many `unit_product` a single `pack_product` contains. Numeric,
    # not Integer -- a box of meat is "10.5 kg", not necessarily a round
    # number, even though the box itself is always sold as one whole box.
    units_per_pack = Column(Numeric, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
