"""v0.6 slice 3 (roadmap.md "Data entry by message") -- lets the chat
agent (the SAME tool-calling loop v0.2 built, web and WhatsApp alike)
record a sale/expense/inventory entry from a natural-language message
like "sold 3 bags of rice at 50 each", with an explicit confirm step
before anything is written to sales/expenses/inventory.

Two-tool shape, both dispatched from app/chat_generation.py's tool loop:
- propose_*_entry: the model extracts fields (its job); THIS module casts
  and computes deterministically (CLAUDE.md's LLM/deterministic split)
  and stages a PendingEntry row -- no ingest_rows call yet.
- confirm_pending_entry / cancel_pending_entry: the owner's next message
  ("yes"/"no") is itself just another conversational turn; the model sees
  its own prior proposal in history and calls one of these using ordinary
  language understanding, no bespoke state machine needed.

All four propose/confirm/cancel functions take (db, business_id, ...) and
raise app.chat_tools.ToolArgumentError on bad input -- reusing that
exception type (not a new one) is what lets app/chat_generation.py's
existing `except (ToolArgumentError, json.JSONDecodeError)` handling cover
these tools with no changes there.
"""

import uuid
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.chat_tools import ToolArgumentError
from app.ingestion import compute_sale_total, ingest_rows
from app.models import PendingEntry, UploadSession

# A pending entry is conversational, not a form left open for days --
# stale enough and a much-later "yes" almost certainly isn't about it
# anymore. 30 minutes is generous for a natural back-and-forth pause.
PENDING_ENTRY_TTL_MINUTES = 30


def _parse_str(arguments: dict, field: str, required: bool = False) -> str | None:
    value = arguments.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ToolArgumentError(f"{field} is required")
        return None
    return str(value).strip()


def _parse_int(arguments: dict, field: str, required: bool = False) -> int | None:
    value = arguments.get(field)
    if value is None:
        if required:
            raise ToolArgumentError(f"{field} is required")
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolArgumentError(f"{field} must be an integer, got: {value!r}")
    return value


def _parse_decimal(arguments: dict, field: str, required: bool = False) -> Decimal | None:
    value = arguments.get(field)
    if value is None:
        if required:
            raise ToolArgumentError(f"{field} is required")
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ToolArgumentError(f"{field} must be a number, got: {value!r}")


def _parse_date(arguments: dict, field: str, default: date_type) -> date_type:
    value = arguments.get(field)
    if value is None:
        return default
    try:
        return date_type.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolArgumentError(f"{field} must be an ISO date (YYYY-MM-DD), got: {value!r}")


def _stage_pending_entry(db: Session, business_id: uuid.UUID, dataset_type: str, fields: dict, summary: str) -> PendingEntry:
    """At most one "pending" row per business -- a new proposal supersedes
    (cancels) whatever was pending before it, rather than stacking
    ambiguous candidates a later "yes" could match against."""
    db.query(PendingEntry).filter(PendingEntry.business_id == business_id, PendingEntry.status == "pending").update(
        {"status": "cancelled", "resolved_at": datetime.now(timezone.utc)}
    )
    entry = PendingEntry(business_id=business_id, dataset_type=dataset_type, fields=fields, summary=summary)
    db.add(entry)
    db.flush()
    return entry


def propose_sale_entry(db: Session, business_id: uuid.UUID, arguments: dict, today: date_type | None = None) -> dict:
    today = today or date_type.today()
    product_name = _parse_str(arguments, "product_name", required=True)
    quantity = _parse_int(arguments, "quantity", required=True)
    unit_price = _parse_decimal(arguments, "unit_price")
    discount = _parse_decimal(arguments, "discount")
    total_amount = _parse_decimal(arguments, "total_amount")
    if total_amount is None:
        total_amount = compute_sale_total(quantity, unit_price, discount)
    sale_date = _parse_date(arguments, "sale_date", default=today)

    fields = {
        "sale_date": sale_date.isoformat(),
        "product_name": product_name,
        "category": _parse_str(arguments, "category"),
        "quantity": quantity,
        "unit_price": str(unit_price) if unit_price is not None else None,
        "discount": str(discount) if discount is not None else None,
        "total_amount": str(total_amount) if total_amount is not None else None,
        "customer_name": _parse_str(arguments, "customer_name"),
        "customer_phone": _parse_str(arguments, "customer_phone"),
        "payment_method": _parse_str(arguments, "payment_method"),
    }

    summary = f"Sale: {quantity} x {product_name}"
    if unit_price is not None:
        summary += f" @ {unit_price}"
    if total_amount is not None:
        summary += f" = {total_amount} total"
    summary += f" ({sale_date.isoformat()})"

    _stage_pending_entry(db, business_id, "sales", fields, summary)
    return {"proposed": True, "summary": summary}


def propose_expense_entry(db: Session, business_id: uuid.UUID, arguments: dict, today: date_type | None = None) -> dict:
    today = today or date_type.today()
    category = _parse_str(arguments, "category", required=True)
    amount = _parse_decimal(arguments, "amount", required=True)
    vendor = _parse_str(arguments, "vendor")
    expense_date = _parse_date(arguments, "expense_date", default=today)

    fields = {
        "expense_date": expense_date.isoformat(),
        "category": category,
        "vendor": vendor,
        "amount": str(amount),
        "description": _parse_str(arguments, "description"),
    }

    summary = f"Expense: {category}"
    if vendor:
        summary += f" ({vendor})"
    summary += f" -- {amount} ({expense_date.isoformat()})"

    _stage_pending_entry(db, business_id, "expenses", fields, summary)
    return {"proposed": True, "summary": summary}


def _decimal_str(arguments: dict, field: str) -> str | None:
    value = _parse_decimal(arguments, field)
    return str(value) if value is not None else None


def propose_inventory_entry(db: Session, business_id: uuid.UUID, arguments: dict) -> dict:
    product_name = _parse_str(arguments, "product_name", required=True)
    quantity = _parse_int(arguments, "quantity", required=True)

    fields = {
        "product_name": product_name,
        "category": _parse_str(arguments, "category"),
        "quantity": quantity,
        "reorder_level": _parse_int(arguments, "reorder_level"),
        "supplier": _parse_str(arguments, "supplier"),
        "cost_price": _decimal_str(arguments, "cost_price"),
        "selling_price": _decimal_str(arguments, "selling_price"),
    }

    summary = f"Inventory: {product_name} -- quantity {quantity}"

    _stage_pending_entry(db, business_id, "inventory", fields, summary)
    return {"proposed": True, "summary": summary}


def _active_pending_entry(db: Session, business_id: uuid.UUID) -> PendingEntry | None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=PENDING_ENTRY_TTL_MINUTES)
    return (
        db.query(PendingEntry)
        .filter(
            PendingEntry.business_id == business_id,
            PendingEntry.status == "pending",
            PendingEntry.created_at > cutoff,
        )
        .order_by(PendingEntry.created_at.desc())
        .first()
    )


def confirm_pending_entry(db: Session, business_id: uuid.UUID) -> dict:
    """Casting happens here, inside ingest_rows, from the raw values
    propose_*_entry staged -- not at proposal time -- same "cast once, at
    the real write" precedent the CSV/document paths follow.

    source_type="chat" covers both web chat and WhatsApp equally: this
    module has no visibility into which channel the conversation is on
    (generate_chat_answer, which calls into this, is itself
    channel-agnostic) -- see docs/decisions.md."""
    entry = _active_pending_entry(db, business_id)
    if entry is None:
        return {"confirmed": False, "reason": "No pending entry to confirm."}

    session = UploadSession(
        business_id=business_id,
        source_type="chat",
        status="COMPLETED",
        processing_started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.flush()

    summary = ingest_rows(db, business_id, session.id, entry.dataset_type, [entry.fields])
    entry.status = "confirmed"
    entry.resolved_at = datetime.now(timezone.utc)
    db.flush()

    return {"confirmed": True, "summary": entry.summary, "duplicate_warning": summary.duplicate_count > 0}


def cancel_pending_entry(db: Session, business_id: uuid.UUID) -> dict:
    entry = _active_pending_entry(db, business_id)
    if entry is None:
        return {"cancelled": False, "reason": "No pending entry to cancel."}

    entry.status = "cancelled"
    entry.resolved_at = datetime.now(timezone.utc)
    db.flush()

    return {"cancelled": True, "summary": entry.summary}
