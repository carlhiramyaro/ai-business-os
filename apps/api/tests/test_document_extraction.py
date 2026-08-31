import uuid
from datetime import datetime, timedelta, timezone

from app.document_extraction import (
    DOCUMENT_REVIEW_TTL_HOURS,
    _parse_extraction_response,
    cancel_document_review,
    confirm_document_review,
    describe_document_review_state,
    document_review_footer,
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


# --- [2026-08-31] every committed document row must carry a date ---
#
# Found in live v0.6 testing: a photographed Costco receipt produced four
# expenses with expense_date NULL. Undated rows are invisible to every
# date-range query -- reports, "how did I do this month", any period-scoped
# profit -- so the money sat in the table but vanished from the analysis,
# with totals that still looked plausible (August read 200 instead of
# 258.46). A receipt prints its date once in the header, not per line, so
# the model was correctly not repeating it per row. See docs/decisions.md.


def test_parse_extraction_applies_document_date_to_every_row():
    raw = {
        "documentDate": "2026-08-15",
        "rows": [{"vendor": "Costco", "amount": "24.99"}, {"vendor": "Costco", "amount": "4.99"}],
        "confidence": 0.9,
    }
    result = _parse_extraction_response(raw, "expenses")

    assert [r["expenseDate"] for r in result["rows"]] == ["2026-08-15", "2026-08-15"]


def test_parse_extraction_per_row_date_beats_the_document_date():
    """An invoice can legitimately list items from different days."""
    raw = {
        "documentDate": "2026-08-15",
        "rows": [{"amount": "10", "expenseDate": "2026-08-01"}, {"amount": "20"}],
        "confidence": 0.9,
    }
    result = _parse_extraction_response(raw, "expenses")

    assert [r["expenseDate"] for r in result["rows"]] == ["2026-08-01", "2026-08-15"]


def test_parse_extraction_without_a_document_date_leaves_rows_undated():
    """Extraction never invents a date -- the commit-time fallback owns that,
    so a genuinely illegible date stays visible as missing until then."""
    result = _parse_extraction_response({"rows": [{"amount": "10"}], "confidence": 0.5}, "expenses")

    assert "expenseDate" not in result["rows"][0]


def test_parse_extraction_ignores_a_blank_document_date():
    result = _parse_extraction_response(
        {"documentDate": "   ", "rows": [{"amount": "10"}], "confidence": 0.5}, "expenses"
    )

    assert "expenseDate" not in result["rows"][0]


def test_parse_extraction_document_date_is_a_no_op_for_inventory():
    """Inventory has no date field; a documentDate must not invent one."""
    result = _parse_extraction_response(
        {"documentDate": "2026-08-15", "rows": [{"productName": "Rice", "quantity": 5}], "confidence": 0.9},
        "inventory",
    )

    assert result["rows"] == [{"productName": "Rice", "quantity": 5}]


def test_confirm_document_review_dates_undated_rows_from_the_upload(db_session):
    """The commit-time backstop: a row must never reach the database
    undated, because nothing downstream can see it if it does."""
    business = _seed_business(db_session)
    # Within DOCUMENT_REVIEW_TTL_HOURS -- an expired review is not
    # confirmable at all, which is a different test below.
    uploaded_at = datetime.now(timezone.utc) - timedelta(hours=2)
    _seed_needs_review_document(
        db_session,
        business,
        rows=[{"vendor": "Costco", "amount": "24.99"}],
        uploaded_at=uploaded_at,
    )

    confirm_document_review(db_session, business.id)

    expense = db_session.query(Expense).one()
    assert expense.expense_date == uploaded_at.date()


def test_confirm_document_review_keeps_a_date_the_receipt_supplied(db_session):
    """The fallback must not overwrite a real date read off the receipt."""
    business = _seed_business(db_session)
    _seed_needs_review_document(
        db_session,
        business,
        rows=[{"vendor": "Costco", "amount": "24.99", "expenseDate": "2026-07-04"}],
        uploaded_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    confirm_document_review(db_session, business.id)

    expense = db_session.query(Expense).one()
    assert expense.expense_date.isoformat() == "2026-07-04"


# --- [2026-08-31] two receipts in review at once ---
#
# Two photos sent before confirming either both produce a "reply YES to
# record these" prompt, but a single YES resolves only the MOST RECENT
# (last-in-first-out, which nobody would guess) and nothing said the other
# was still waiting. Document reviews also had no TTL at all, while pending
# entries expire after 30 minutes -- so a forgotten receipt stayed
# confirmable forever, and describe_document_review_state kept telling the
# model a document awaited review, meaning an unrelated "yes" weeks later
# could record it. See docs/decisions.md.


def test_confirm_resolves_the_most_recent_and_leaves_the_earlier_waiting(db_session):
    """Not data loss -- the earlier receipt survives a later YES -- but the
    owner has no way to know which one they just recorded."""
    business = _seed_business(db_session)
    first = _seed_needs_review_document(
        db_session, business, rows=[{"vendor": "FirstShop", "amount": "111.00"}],
        uploaded_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    second = _seed_needs_review_document(
        db_session, business, rows=[{"vendor": "SecondShop", "amount": "222.00"}]
    )

    confirm_document_review(db_session, business.id)

    assert [e.vendor for e in db_session.query(Expense).all()] == ["SecondShop"]
    assert db_session.get(UploadSession, second.id).status == "COMPLETED"
    assert db_session.get(UploadSession, first.id).status == "NEEDS_REVIEW"


def test_document_review_footer_names_the_single_waiting_document(db_session):
    business = _seed_business(db_session)
    _seed_needs_review_document(
        db_session, business, rows=[{"vendor": "Costco", "amount": "24.99"}]
    )

    footer = document_review_footer(db_session, business.id)

    assert "Awaiting your confirmation" in footer
    assert "Costco" in footer
    assert "Reply YES" in footer


def test_document_review_footer_surfaces_the_backlog(db_session):
    """The owner must be told a YES leaves others waiting."""
    business = _seed_business(db_session)
    _seed_needs_review_document(
        db_session, business, rows=[{"vendor": "FirstShop", "amount": "111.00"}],
        uploaded_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    _seed_needs_review_document(
        db_session, business, rows=[{"vendor": "SecondShop", "amount": "222.00"}]
    )

    footer = document_review_footer(db_session, business.id)

    assert "2 photos awaiting review" in footer
    assert "SecondShop" in footer  # the one a YES actually records
    assert "others stay waiting" in footer


def test_document_review_footer_is_none_when_nothing_waits(db_session):
    business = _seed_business(db_session)
    assert document_review_footer(db_session, business.id) is None


def test_expired_document_review_is_not_confirmable(db_session):
    """A receipt left unconfirmed past the TTL must not be recorded by an
    unrelated 'yes' later -- the wrong record under the owner's
    confirmation."""
    business = _seed_business(db_session)
    _seed_needs_review_document(
        db_session,
        business,
        rows=[{"vendor": "StaleShop", "amount": "999.00"}],
        uploaded_at=datetime.now(timezone.utc) - timedelta(hours=DOCUMENT_REVIEW_TTL_HOURS + 1),
    )

    assert document_review_footer(db_session, business.id) is None
    assert "NO photographed document" in describe_document_review_state(db_session, business.id)

    result = confirm_document_review(db_session, business.id)
    assert result["confirmed"] is False
    assert db_session.query(Expense).count() == 0


def test_document_review_within_ttl_is_still_confirmable(db_session):
    business = _seed_business(db_session)
    _seed_needs_review_document(
        db_session,
        business,
        rows=[{"vendor": "FreshShop", "amount": "10.00"}],
        uploaded_at=datetime.now(timezone.utc) - timedelta(hours=DOCUMENT_REVIEW_TTL_HOURS - 1),
    )

    assert confirm_document_review(db_session, business.id)["confirmed"] is True
    assert db_session.query(Expense).one().vendor == "FreshShop"


def test_state_description_tells_the_model_about_multiple_reviews(db_session):
    business = _seed_business(db_session)
    _seed_needs_review_document(
        db_session, business, rows=[{"vendor": "A", "amount": "1"}],
        uploaded_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    _seed_needs_review_document(db_session, business, rows=[{"vendor": "B", "amount": "2"}])

    state = describe_document_review_state(db_session, business.id)

    assert "2 photographed documents" in state
    assert "MOST RECENT" in state
