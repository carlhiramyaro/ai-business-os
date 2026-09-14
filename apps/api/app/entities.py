"""Get-or-create resolution of customer/supplier entities from raw
ingested strings ("Ama Mensah", "ama  mensah" → one Customer row).

Deterministic, no LLM involvement. The normalization here MUST stay in
sync with the SQL backfill in migration `add customers suppliers` —
both lowercase, trim, and collapse internal whitespace."""

import re
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Customer, Inventory, Product, Sale, Supplier


def _normalized_sql(column):
    """SQL mirror of normalize_entity_name (trim, collapse internal
    whitespace, lowercase) so a Python-side normalized value and a
    database-side one always agree. Must stay in sync with it, and with the
    backfill in migration `normalize product name casing`."""
    return func.lower(func.regexp_replace(func.btrim(column), r"\s+", " ", "g"))


def normalize_entity_name(name) -> str | None:
    """Trim, collapse whitespace, lowercase. Returns None for empty/blank
    input so callers can skip resolution entirely."""
    if name is None:
        return None
    normalized = " ".join(str(name).split()).lower()
    return normalized or None


def resolve_customer(db: Session, business_id: uuid.UUID, name, phone=None) -> Customer | None:
    normalized = normalize_entity_name(name)
    if normalized is None:
        return None

    customer = (
        db.query(Customer)
        .filter(Customer.business_id == business_id, Customer.normalized_name == normalized)
        .one_or_none()
    )
    if customer is None:
        customer = Customer(
            business_id=business_id,
            name=" ".join(str(name).split()),  # first-seen casing, cleaned spacing
            normalized_name=normalized,
        )
        db.add(customer)
        db.flush()

    phone_value = str(phone).strip() if phone is not None else ""
    if phone_value and customer.phone != phone_value:
        customer.phone = phone_value  # last non-empty value wins

    return customer


def resolve_supplier(db: Session, business_id: uuid.UUID, name) -> Supplier | None:
    normalized = normalize_entity_name(name)
    if normalized is None:
        return None

    supplier = (
        db.query(Supplier)
        .filter(Supplier.business_id == business_id, Supplier.normalized_name == normalized)
        .one_or_none()
    )
    if supplier is None:
        supplier = Supplier(
            business_id=business_id,
            name=" ".join(str(name).split()),
            normalized_name=normalized,
        )
        db.add(supplier)
        db.flush()

    return supplier


def suggest_sku(name: str, existing_skus: set[str]) -> str:
    """A deterministic SKU proposal for a product name -- an uppercase,
    dash-separated slug, disambiguated against `existing_skus` (every SKU
    already in use for the business) with a numeric suffix on collision.
    Same name always proposes the same base slug; nothing random, same
    deterministic-not-LLM-guess posture CLAUDE.md's arithmetic rule
    describes, applied here to naming instead.

    Two call sites: resolve_product uses this to auto-assign a SKU when a
    NEW product is created and none was supplied (see its docstring for
    why this is a default, not just a suggestion); the
    GET .../suggested-sku endpoint (app/routers/products.py) also exposes
    it directly, for an owner who cleared a SKU and wants a fresh one, or
    for products that predate auto-assignment (no backfill -- see
    docs/decisions.md).
    """
    base = re.sub(r"[^A-Z0-9]+", "-", name.strip().upper()).strip("-") or "SKU"
    if base not in existing_skus:
        return base
    suffix = 2
    while f"{base}-{suffix}" in existing_skus:
        suffix += 1
    return f"{base}-{suffix}"


def resolve_product(
    db: Session,
    business_id: uuid.UUID,
    name,
    *,
    sku=None,
    category=None,
    base_unit=None,
    reorder_level=None,
    cost_price=None,
    selling_price=None,
    supplier_id=None,
) -> Product | None:
    """Get-or-create resolution of a product from a raw name -- same shape
    as resolve_customer/resolve_supplier (v0.7, roadmap.md "Inventory
    depth"). This is the real entity those write paths adopt in place of
    canonicalize_product_name's string-only stopgap; that function is
    unaffected and keeps serving the sales/inventory rows that predate it.

    Every optional field follows the same last-non-empty-value-wins rule
    resolve_customer's phone does: a later call can fill in or correct
    sku/category/base_unit/reorder_level/cost_price/selling_price/
    supplier_id, but a blank/omitted value on this call never erases a
    value a previous call already set.

    SKU is the one exception at creation time: a brand-new product with no
    `sku` given gets one auto-assigned via suggest_sku, not left blank.
    Most owners in this product's actual market (African informal retail,
    product-vision.md) never had a SKU scheme to begin with and won't go
    looking for one, so every product gets a real, searchable identifier
    by default -- closer to how lightweight/informal-retail POS tools
    (e.g. Loyverse) handle this than Shopify/Square's leave-it-blank
    default, which assumes a merchant already has a scheme to import.
    Still fully editable afterward via PATCH /products/{id} -- a default,
    not a lock-in. See docs/decisions.md.
    """
    normalized = normalize_entity_name(name)
    if normalized is None:
        return None

    product = (
        db.query(Product)
        .filter(Product.business_id == business_id, Product.normalized_name == normalized)
        .one_or_none()
    )
    if product is None:
        display_name = " ".join(str(name).split())
        computed_sku = str(sku).strip() if sku is not None and str(sku).strip() else None
        if computed_sku is None:
            # See this function's docstring for why auto-assignment,
            # not blank-until-edited, is the default here.
            existing_skus = {
                s
                for (s,) in db.query(Product.sku).filter(
                    Product.business_id == business_id, Product.sku.isnot(None)
                )
            }
            computed_sku = suggest_sku(display_name, existing_skus)
        product = Product(
            business_id=business_id,
            name=display_name,  # first-seen casing, cleaned spacing
            normalized_name=normalized,
            base_unit=str(base_unit).strip() if base_unit is not None and str(base_unit).strip() else "unit",
            sku=computed_sku,
        )
        db.add(product)
        db.flush()

    if sku is not None and str(sku).strip():
        product.sku = str(sku).strip()
    if category is not None and str(category).strip():
        product.category = str(category).strip()
    if base_unit is not None and str(base_unit).strip():
        product.base_unit = str(base_unit).strip()
    if reorder_level is not None:
        product.reorder_level = reorder_level
    if cost_price is not None:
        product.cost_price = cost_price
    if selling_price is not None:
        product.selling_price = selling_price
    if supplier_id is not None:
        product.supplier_id = supplier_id

    return product


def canonicalize_product_name(db: Session, business_id: uuid.UUID, name, cache: dict | None = None):
    """Converges casing/spacing variants of the same product onto ONE
    spelling per business: "rice", "Rice", "  RICE " all become whichever
    the business used first.

    Products are not (yet) a first-class entity the way Customer/Supplier
    are -- `sales.product_name` / `inventory.product_name` are plain
    strings -- so this returns the canonical STRING rather than a row, with
    no new table. Same normalization (`normalize_entity_name`) and same
    first-seen-casing semantics as resolve_customer/resolve_supplier, so
    the three behave identically from a user's point of view.

    Why this exists: over CSV, product names arrive from a system and are
    internally consistent. Over WhatsApp (v0.6) they are typed by hand on a
    phone, so a single owner produces "rice" one day and "Rice" the next,
    and every `GROUP BY product_name` (top products, inventory matching)
    silently splits one product into several. Found in live testing after a
    single message; see docs/decisions.md [2026-08-27].

    `cache` carries first-seen casings WITHIN one ingest batch. Unlike the
    entity resolvers there is no row to `db.flush()`, so two variants in the
    same batch would otherwise each miss the other and both persist.

    Returns None for blank input, and leaves the value untouched for
    non-string types (a numeric SKU-style name), so callers can assign the
    result unconditionally.
    """
    normalized = normalize_entity_name(name)
    if normalized is None:
        return None if name is None or not str(name).strip() else name

    if cache is not None and normalized in cache:
        return cache[normalized]

    cleaned = " ".join(str(name).split())
    existing = (
        db.query(Sale.product_name)
        .filter(Sale.business_id == business_id, _normalized_sql(Sale.product_name) == normalized)
        .first()
    ) or (
        db.query(Inventory.product_name)
        .filter(Inventory.business_id == business_id, _normalized_sql(Inventory.product_name) == normalized)
        .first()
    )
    canonical = existing[0] if existing else cleaned

    if cache is not None:
        cache[normalized] = canonical
    return canonical
