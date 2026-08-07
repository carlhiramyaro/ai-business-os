"""v0.6 slice 3: app/data_entry.py's propose/confirm/cancel logic, called
directly (not through the LLM loop -- that's tests/test_chat_generation.py's
job). No LLM involved here at all; deterministic, fixed input -> expected
output, per CLAUDE.md's separation rule."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import app.data_entry as data_entry
from app.chat_tools import ToolArgumentError
from app.data_entry import (
    cancel_pending_entry,
    confirm_pending_entry,
    propose_expense_entry,
    propose_inventory_entry,
    propose_sale_entry,
)
from app.ingestion import ingest_rows
from app.models import Business, Expense, Inventory, PendingEntry, Sale, UploadSession, User
from app.security import hash_password

TODAY = date(2026, 3, 1)


def _seed_business(db):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    business = Business(owner_id=user.id, business_name="Data Entry Co")
    db.add(business)
    db.flush()
    return business


def _assert_raises_tool_error(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        assert False, "expected ToolArgumentError"
    except ToolArgumentError:
        pass


# --- propose_sale_entry ------------------------------------------------------


def test_propose_sale_entry_computes_total_when_omitted(db_session):
    business = _seed_business(db_session)
    result = propose_sale_entry(
        db_session, business.id, {"product_name": "Rice", "quantity": 3, "unit_price": 50}, today=TODAY
    )
    assert result["proposed"] is True
    assert "150" in result["summary"]

    [entry] = db_session.query(PendingEntry).all()
    assert entry.status == "pending"
    assert entry.dataset_type == "sales"
    assert entry.fields["product_name"] == "Rice"
    assert entry.fields["quantity"] == 3
    assert entry.fields["total_amount"] == "150"
    assert entry.fields["sale_date"] == TODAY.isoformat()


def test_propose_sale_entry_respects_explicit_total(db_session):
    business = _seed_business(db_session)
    propose_sale_entry(
        db_session,
        business.id,
        {"product_name": "Rice", "quantity": 3, "unit_price": 50, "total_amount": 999},
        today=TODAY,
    )
    [entry] = db_session.query(PendingEntry).all()
    assert entry.fields["total_amount"] == "999"


def test_propose_sale_entry_does_not_write_to_sales_table(db_session):
    business = _seed_business(db_session)
    propose_sale_entry(db_session, business.id, {"product_name": "Rice", "quantity": 3}, today=TODAY)
    assert db_session.query(Sale).count() == 0


def test_propose_sale_entry_requires_product_name_and_quantity(db_session):
    business = _seed_business(db_session)
    _assert_raises_tool_error(propose_sale_entry, db_session, business.id, {"quantity": 3}, today=TODAY)
    _assert_raises_tool_error(propose_sale_entry, db_session, business.id, {"product_name": "Rice"}, today=TODAY)


def test_propose_sale_entry_rejects_non_integer_quantity(db_session):
    business = _seed_business(db_session)
    _assert_raises_tool_error(
        propose_sale_entry, db_session, business.id, {"product_name": "Rice", "quantity": "three"}, today=TODAY
    )


def test_propose_sale_entry_rejects_bad_date(db_session):
    business = _seed_business(db_session)
    _assert_raises_tool_error(
        propose_sale_entry,
        db_session,
        business.id,
        {"product_name": "Rice", "quantity": 1, "sale_date": "not-a-date"},
        today=TODAY,
    )


# --- propose_expense_entry / propose_inventory_entry -------------------------


def test_propose_expense_entry_stages_row(db_session):
    business = _seed_business(db_session)
    result = propose_expense_entry(
        db_session, business.id, {"category": "Utilities", "amount": 200, "vendor": "Power Co"}, today=TODAY
    )
    assert result["proposed"] is True
    [entry] = db_session.query(PendingEntry).all()
    assert entry.dataset_type == "expenses"
    assert entry.fields["category"] == "Utilities"
    assert entry.fields["amount"] == "200"
    assert entry.fields["vendor"] == "Power Co"
    assert db_session.query(Expense).count() == 0


def test_propose_inventory_entry_stages_row(db_session):
    business = _seed_business(db_session)
    result = propose_inventory_entry(db_session, business.id, {"product_name": "Rice", "quantity": 50})
    assert result["proposed"] is True
    [entry] = db_session.query(PendingEntry).all()
    assert entry.dataset_type == "inventory"
    assert entry.fields["quantity"] == 50
    assert db_session.query(Inventory).count() == 0


# --- one active pending entry per business ------------------------------------


def test_new_proposal_supersedes_previous_pending_entry(db_session):
    business = _seed_business(db_session)
    propose_sale_entry(db_session, business.id, {"product_name": "Rice", "quantity": 1}, today=TODAY)
    propose_sale_entry(db_session, business.id, {"product_name": "Beans", "quantity": 2}, today=TODAY)

    entries = db_session.query(PendingEntry).order_by(PendingEntry.created_at).all()
    assert len(entries) == 2
    assert entries[0].status == "cancelled"
    assert entries[1].status == "pending"
    assert entries[1].fields["product_name"] == "Beans"


# --- confirm_pending_entry -----------------------------------------------------


def test_confirm_pending_entry_records_the_sale(db_session):
    business = _seed_business(db_session)
    propose_sale_entry(
        db_session, business.id, {"product_name": "Rice", "quantity": 3, "unit_price": 50}, today=TODAY
    )

    result = confirm_pending_entry(db_session, business.id)

    assert result["confirmed"] is True
    assert result["duplicate_warning"] is False
    [sale] = db_session.query(Sale).all()
    assert sale.product_name == "Rice"
    assert sale.quantity == 3
    assert sale.total_amount == Decimal("150")

    [entry] = db_session.query(PendingEntry).all()
    assert entry.status == "confirmed"
    assert entry.resolved_at is not None

    [session] = db_session.query(UploadSession).all()
    assert session.source_type == "chat"
    assert session.status == "COMPLETED"


def test_confirm_pending_entry_with_nothing_pending(db_session):
    business = _seed_business(db_session)
    result = confirm_pending_entry(db_session, business.id)
    assert result == {"confirmed": False, "reason": "No pending entry to confirm."}
    assert db_session.query(Sale).count() == 0


def test_confirm_pending_entry_ignores_expired_entry(db_session):
    business = _seed_business(db_session)
    propose_sale_entry(db_session, business.id, {"product_name": "Rice", "quantity": 1}, today=TODAY)
    entry = db_session.query(PendingEntry).one()
    entry.created_at = datetime.now(timezone.utc) - timedelta(minutes=data_entry.PENDING_ENTRY_TTL_MINUTES + 1)
    db_session.flush()

    result = confirm_pending_entry(db_session, business.id)

    assert result["confirmed"] is False
    assert db_session.query(Sale).count() == 0


def test_confirm_pending_entry_flags_duplicate(db_session):
    business = _seed_business(db_session)
    # Seeded through ingest_rows (not a raw ORM insert) so content_hash is
    # actually computed -- a bare Sale(...) row would never dedup-match
    # anything, since content_hash would be left NULL.
    upload_session = UploadSession(business_id=business.id, source_type="manual", status="COMPLETED")
    db_session.add(upload_session)
    db_session.flush()
    ingest_rows(
        db_session,
        business.id,
        upload_session.id,
        "sales",
        [{"sale_date": TODAY.isoformat(), "product_name": "Rice", "quantity": 3, "total_amount": "150"}],
    )

    propose_sale_entry(
        db_session, business.id, {"product_name": "Rice", "quantity": 3, "unit_price": 50}, today=TODAY
    )
    result = confirm_pending_entry(db_session, business.id)

    assert result["confirmed"] is True
    assert result["duplicate_warning"] is True


# --- cancel_pending_entry -------------------------------------------------------


def test_cancel_pending_entry_discards_without_recording(db_session):
    business = _seed_business(db_session)
    propose_sale_entry(db_session, business.id, {"product_name": "Rice", "quantity": 1}, today=TODAY)

    result = cancel_pending_entry(db_session, business.id)

    assert result["cancelled"] is True
    assert db_session.query(Sale).count() == 0
    entry = db_session.query(PendingEntry).one()
    assert entry.status == "cancelled"
    assert entry.resolved_at is not None


def test_cancel_pending_entry_with_nothing_pending(db_session):
    business = _seed_business(db_session)
    result = cancel_pending_entry(db_session, business.id)
    assert result == {"cancelled": False, "reason": "No pending entry to cancel."}


def test_pending_entries_are_scoped_to_business(db_session):
    business_a = _seed_business(db_session)
    business_b = _seed_business(db_session)
    propose_sale_entry(db_session, business_a.id, {"product_name": "Rice", "quantity": 1}, today=TODAY)

    result = confirm_pending_entry(db_session, business_b.id)

    assert result["confirmed"] is False
    assert db_session.query(Sale).count() == 0
