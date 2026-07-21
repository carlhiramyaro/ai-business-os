"""Get-or-create resolution of customer/supplier entities from raw
ingested strings ("Ama Mensah", "ama  mensah" → one Customer row).

Deterministic, no LLM involvement. The normalization here MUST stay in
sync with the SQL backfill in migration `add customers suppliers` —
both lowercase, trim, and collapse internal whitespace."""

import uuid

from sqlalchemy.orm import Session

from app.models import Customer, Supplier


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
