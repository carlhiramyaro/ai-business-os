import uuid
from datetime import date
from decimal import Decimal

from app.ingestion import _cast_value, _content_hash, ingest_rows
from app.models import Business, Customer, Expense, Inventory, Sale, Supplier, UploadSession, User
from app.security import hash_password


def _seed_session(db_session, source_type="csv"):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.flush()
    business = Business(owner_id=user.id, business_name="Ingestion Test Co")
    db_session.add(business)
    db_session.flush()
    session = UploadSession(
        business_id=business.id,
        source_type=source_type,
        status="PROCESSING",
    )
    db_session.add(session)
    db_session.flush()
    return business, session


# --- _cast_value: deterministic, no DB, fixed input -> expected output ---


def test_cast_value_date_field():
    assert _cast_value("sale_date", "2026-01-15") == date(2026, 1, 15)


def test_cast_value_invalid_date_returns_none():
    assert _cast_value("sale_date", "not a date") is None


def test_cast_value_int_field():
    assert _cast_value("quantity", "10") == 10


def test_cast_value_invalid_int_returns_none():
    assert _cast_value("quantity", "abc") is None


def test_cast_value_decimal_field():
    assert _cast_value("total_amount", "25.50") == Decimal("25.50")


def test_cast_value_invalid_decimal_returns_none():
    assert _cast_value("total_amount", "not a number") is None


def test_cast_value_string_field_passthrough():
    assert _cast_value("product_name", "Rice") == "Rice"


def test_cast_value_none_passthrough():
    assert _cast_value("product_name", None) is None


# --- _content_hash: deterministic, stable across producers ---


def test_content_hash_stable_for_identical_input():
    business_id = uuid.uuid4()
    row = {"sale_date": date(2026, 1, 1), "product_name": "Rice", "quantity": 10, "total_amount": Decimal("25.0")}
    assert _content_hash(business_id, "sales", row) == _content_hash(business_id, "sales", row)


def test_content_hash_differs_across_businesses():
    row = {"sale_date": date(2026, 1, 1), "product_name": "Rice", "quantity": 10, "total_amount": Decimal("25.0")}
    assert _content_hash(uuid.uuid4(), "sales", row) != _content_hash(uuid.uuid4(), "sales", row)


def test_content_hash_ignores_non_dedup_fields():
    """customer_name isn't a dedup field for sales -- two rows differing only
    in customer_name should hash identically (dedup is about the sale
    itself, not who bought it)."""
    business_id = uuid.uuid4()
    base = {"sale_date": date(2026, 1, 1), "product_name": "Rice", "quantity": 10, "total_amount": Decimal("25.0")}
    row_a = {**base, "customer_name": "Ama"}
    row_b = {**base, "customer_name": "Kofi"}
    assert _content_hash(business_id, "sales", row_a) == _content_hash(business_id, "sales", row_b)


# --- ingest_rows: the shared boundary, exercised end to end against the DB ---


def test_ingest_rows_sales_casts_resolves_entities_and_sets_row_numbers(db_session):
    business, session = _seed_session(db_session)

    rows = [
        {
            "sale_date": "2026-01-05",
            "product_name": "Rice",
            "quantity": "10",
            "unit_price": "2.5",
            "total_amount": "25.0",
            "customer_name": "Ama Mensah",
            "customer_phone": "0244000000",
        },
        {
            "sale_date": "2026-01-06",
            "product_name": "Beans",
            "quantity": "4",
            "unit_price": "3.0",
            "total_amount": "12.0",
            "customer_name": "ama  mensah",  # same customer, variant casing/spacing
        },
    ]

    summary = ingest_rows(db_session, business.id, session.id, "sales", rows)

    assert summary.inserted == 2
    assert summary.duplicate_count == 0
    assert summary.date_range_start == date(2026, 1, 5)
    assert summary.date_range_end == date(2026, 1, 6)

    sales = db_session.query(Sale).filter(Sale.business_id == business.id).order_by(Sale.raw_row_number).all()
    assert [s.raw_row_number for s in sales] == [1, 2]
    assert sales[0].total_amount == Decimal("25.0")
    assert sales[0].sale_date == date(2026, 1, 5)

    # both rows resolved to the same first-class Customer entity
    customer = db_session.query(Customer).filter(Customer.business_id == business.id).one()
    assert customer.name == "Ama Mensah"
    assert {s.customer_id for s in sales} == {customer.id}


def test_ingest_rows_inventory_resolves_supplier(db_session):
    business, session = _seed_session(db_session)

    summary = ingest_rows(
        db_session,
        business.id,
        session.id,
        "inventory",
        [{"product_name": "Rice", "quantity": "100", "cost_price": "2.0", "supplier": "Acme Supplies"}],
    )

    assert summary.inserted == 1
    inventory_row = db_session.query(Inventory).filter(Inventory.business_id == business.id).one()
    supplier = db_session.query(Supplier).filter(Supplier.business_id == business.id).one()
    assert supplier.name == "Acme Supplies"
    assert inventory_row.supplier_id == supplier.id


def test_ingest_rows_expenses_date_range(db_session):
    business, session = _seed_session(db_session)

    summary = ingest_rows(
        db_session,
        business.id,
        session.id,
        "expenses",
        [
            {"expense_date": "2026-02-01", "category": "Utilities", "vendor": "Power Co", "amount": "150.0"},
            {"expense_date": "2026-02-10", "category": "Rent", "vendor": "Landlord", "amount": "500.0"},
        ],
    )

    assert summary.inserted == 2
    assert summary.date_range_start == date(2026, 2, 1)
    assert summary.date_range_end == date(2026, 2, 10)
    assert db_session.query(Expense).filter(Expense.business_id == business.id).count() == 2


def test_ingest_rows_detects_duplicate_against_prior_batch(db_session):
    """Warn-only: a second ingest of the same content is still inserted (the
    business really might have made two identical sales), but duplicate_count
    surfaces the collision so the caller can warn -- roadmap.md v0.3."""
    business, session = _seed_session(db_session)
    row = {"sale_date": "2026-01-05", "product_name": "Rice", "quantity": "10", "total_amount": "25.0"}

    first = ingest_rows(db_session, business.id, session.id, "sales", [row])
    assert first.duplicate_count == 0

    second_session = UploadSession(business_id=business.id, source_type="manual", status="PROCESSING")
    db_session.add(second_session)
    db_session.flush()
    second = ingest_rows(db_session, business.id, second_session.id, "sales", [row])

    assert second.duplicate_count == 1
    assert second.inserted == 1  # inserted anyway, never silently dropped
    assert db_session.query(Sale).filter(Sale.business_id == business.id).count() == 2


def test_ingest_rows_detects_duplicate_within_same_batch(db_session):
    business, session = _seed_session(db_session)
    row = {"sale_date": "2026-01-05", "product_name": "Rice", "quantity": "10", "total_amount": "25.0"}

    summary = ingest_rows(db_session, business.id, session.id, "sales", [row, dict(row)])

    assert summary.inserted == 2
    assert summary.duplicate_count == 1  # the second occurrence flagged, both kept


def test_ingest_rows_scoped_per_business(db_session):
    """Same content for two different businesses must not cross-contaminate
    dedup detection -- every business-scoped query filters by businessId,
    including this one (CLAUDE.md's rule with no exceptions)."""
    business_a, session_a = _seed_session(db_session)
    business_b, session_b = _seed_session(db_session)
    row = {"sale_date": "2026-01-05", "product_name": "Rice", "quantity": "10", "total_amount": "25.0"}

    ingest_rows(db_session, business_a.id, session_a.id, "sales", [row])
    second = ingest_rows(db_session, business_b.id, session_b.id, "sales", [row])

    assert second.duplicate_count == 0
