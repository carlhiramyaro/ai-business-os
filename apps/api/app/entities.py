"""Get-or-create resolution of customer/supplier entities from raw
ingested strings ("Ama Mensah", "ama  mensah" → one Customer row).

Deterministic, no LLM involvement. The normalization here MUST stay in
sync with the SQL backfill in migration `add customers suppliers` —
both lowercase, trim, and collapse internal whitespace."""

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Customer, Inventory, Sale, Supplier


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
