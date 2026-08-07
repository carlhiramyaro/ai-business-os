import uuid
from datetime import datetime, timedelta, timezone

from app.document_extraction import (
    _parse_extraction_response,
    cancel_document_review,
    confirm_document_review,
    format_extraction_summary,
)
from app.models import Business, DocumentExtraction, Expense, UploadSession, User
from app.security import hash_password


def test_parse_extraction_keeps_only_canonical_fields():
    raw = {
        "rows": [
            {"saleDate": "2026-07-24", "productName": "Rice", "quantity": 2, "totalAmount": "25.0"},
            {"saleDate": "2026-07-24", "productName": "Beans", "notARealField": "x"},
        ],
        "confidence": 0.8,
    }
    result = _parse_extraction_response(raw, "sales")

    assert result["rows"] == [
        {"saleDate": "2026-07-24", "productName": "Rice", "quantity": 2, "totalAmount": "25.0"},
        {"saleDate": "2026-07-24", "productName": "Beans"},
    ]
    assert result["confidence"] == 0.8


def test_parse_extraction_clamps_confidence_to_0_1():
    assert _parse_extraction_response({"rows": [], "confidence": 5.0}, "sales")["confidence"] == 1.0
    assert _parse_extraction_response({"rows": [], "confidence": -2.0}, "sales")["confidence"] == 0.0


def test_parse_extraction_invalid_confidence_defaults_to_zero():
    assert _parse_extraction_response({"rows": [], "confidence": "not a number"}, "sales")["confidence"] == 0.0
    assert _parse_extraction_response({"rows": []}, "sales")["confidence"] == 0.0


def test_parse_extraction_non_list_rows_becomes_empty():
    assert _parse_extraction_response({"rows": "garbage", "confidence": 0.5}, "sales")["rows"] == []


def test_parse_extraction_skips_non_dict_row_entries():
    raw = {"rows": [{"productName": "Rice"}, "not a dict", 42], "confidence": 0.5}
    assert _parse_extraction_response(raw, "sales")["rows"] == [{"productName": "Rice"}]


def test_parse_extraction_scoped_per_dataset_type():
    """A field valid for 'sales' (customerName) isn't valid for 'expenses'
    -- extraction must respect the dataset it was asked to extract for."""
    raw = {"rows": [{"customerName": "Ama", "vendor": "Power Co", "amount": "10.0"}], "confidence": 0.5}
    result = _parse_extraction_response(raw, "expenses")
    assert result["rows"] == [{"vendor": "Power Co", "amount": "10.0"}]


# --- format_extraction_summary: v0.6 slice 4, deterministic, no LLM ---------


def test_format_extraction_summary_lists_rows():
    rows = [{"vendor": "Power Co", "amount": "150.0", "expenseDate": "2026-08-07"}]
    text = format_extraction_summary("expenses", rows)
    assert "1 item" in text
    assert "vendor: Power Co" in text
    assert "amount: 150.0" in text
    assert "YES" in text and "NO" in text


def test_format_extraction_summary_pluralizes_multiple_rows():
    rows = [{"vendor": "A", "amount": "1"}, {"vendor": "B", "amount": "2"}]
    text = format_extraction_summary("expenses", rows)
    assert "2 items" in text
    assert "1. vendor: A" in text
    assert "2. vendor: B" in text


def test_format_extraction_summary_empty_rows_asks_to_retry():
    text = format_extraction_summary("expenses", [])
    assert "couldn't read" in text.lower()
    assert "YES" not in text


def test_format_extraction_summary_omits_empty_field_values():
    rows = [{"vendor": "Power Co", "amount": "150.0", "description": ""}]
    text = format_extraction_summary("expenses", rows)
    assert "description" not in text


# --- confirm_document_review / cancel_document_review: v0.6 slice 4 --------


def _seed_business(db):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    business = Business(owner_id=user.id, business_name="Document Review Co")
    db.add(business)
    db.flush()
    return business


def _seed_needs_review_document(db, business, dataset_type="expenses", rows=None, uploaded_at=None):
    rows = rows if rows is not None else [{"vendor": "Power Co", "amount": "150.0"}]
    session = UploadSession(business_id=business.id, source_type="document", status="NEEDS_REVIEW")
    db.add(session)
    db.flush()
    if uploaded_at is not None:
        db.query(UploadSession).filter(UploadSession.id == session.id).update({"uploaded_at": uploaded_at})
        db.flush()
        db.refresh(session)
    db.add(
        DocumentExtraction(
            upload_session_id=session.id, business_id=business.id, dataset_type=dataset_type, extracted_rows=rows
        )
    )
    db.flush()
    return session


def test_confirm_document_review_ingests_and_completes(db_session):
    business = _seed_business(db_session)
    _seed_needs_review_document(db_session, business)

    result = confirm_document_review(db_session, business.id)

    assert result["confirmed"] is True
    assert result["rows_recorded"] == 1
    expense = db_session.query(Expense).one()
    assert expense.vendor == "Power Co"
    session = db_session.query(UploadSession).one()
    assert session.status == "COMPLETED"


def test_confirm_document_review_with_nothing_pending(db_session):
    business = _seed_business(db_session)
    result = confirm_document_review(db_session, business.id)
    assert result == {"confirmed": False, "reason": "No document waiting for review."}


def test_confirm_document_review_picks_most_recent(db_session):
    business = _seed_business(db_session)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    _seed_needs_review_document(db_session, business, rows=[{"vendor": "Old Co", "amount": "1"}], uploaded_at=old)
    _seed_needs_review_document(db_session, business, rows=[{"vendor": "New Co", "amount": "2"}])

    confirm_document_review(db_session, business.id)

    expense = db_session.query(Expense).one()
    assert expense.vendor == "New Co"


def test_cancel_document_review_discards_without_recording(db_session):
    business = _seed_business(db_session)
    session = _seed_needs_review_document(db_session, business)

    result = cancel_document_review(db_session, business.id)

    assert result == {"cancelled": True}
    assert db_session.query(Expense).count() == 0
    db_session.refresh(session)
    assert session.status == "FAILED"


def test_cancel_document_review_with_nothing_pending(db_session):
    business = _seed_business(db_session)
    result = cancel_document_review(db_session, business.id)
    assert result == {"cancelled": False, "reason": "No document waiting for review."}


def test_document_review_scoped_to_business(db_session):
    business_a = _seed_business(db_session)
    business_b = _seed_business(db_session)
    _seed_needs_review_document(db_session, business_a)

    result = confirm_document_review(db_session, business_b.id)

    assert result["confirmed"] is False
    assert db_session.query(Expense).count() == 0
