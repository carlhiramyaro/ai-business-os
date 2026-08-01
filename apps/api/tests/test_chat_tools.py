import json
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.chat_tools import (
    TOOL_SCHEMAS,
    ToolArgumentError,
    execute_tool,
    get_financial_summary,
    get_inactive_customers,
    get_inventory_status,
    get_sales_trend,
    get_top_customers,
    get_top_products,
)
from app.entities import resolve_customer
from app.models import Business, Expense, Inventory, Sale, UploadSession, User
from app.security import hash_password


def _seed_business(db_session):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.flush()
    business = Business(owner_id=user.id, business_name="Chat Tools Test Co")
    db_session.add(business)
    db_session.flush()
    upload_session = UploadSession(
        business_id=business.id,
        sales_file_url="s3://fake/sales.csv",
        inventory_file_url="s3://fake/inventory.csv",
        expenses_file_url="s3://fake/expenses.csv",
        status="COMPLETED",
    )
    db_session.add(upload_session)
    db_session.flush()
    return business, upload_session


def _add_sale(db_session, business, upload_session, row_number, **overrides):
    fields = {
        "sale_date": date(2026, 6, 1),
        "product_name": "Rice",
        "quantity": 1,
        "total_amount": Decimal("100.00"),
        "customer_name": None,
    }
    fields.update(overrides)
    # Mirror what ingestion does: resolve the customer entity and link it.
    customer = resolve_customer(db_session, business.id, fields.get("customer_name"))
    if customer is not None:
        fields["customer_id"] = customer.id
    db_session.add(
        Sale(
            business_id=business.id,
            upload_session_id=upload_session.id,
            raw_row_number=row_number,
            **fields,
        )
    )


def test_financial_summary_all_time_and_date_range(db_session):
    business, upload = _seed_business(db_session)
    _add_sale(db_session, business, upload, 1, sale_date=date(2026, 6, 1), total_amount=Decimal("100.00"))
    _add_sale(db_session, business, upload, 2, sale_date=date(2026, 7, 1), total_amount=Decimal("50.00"))
    _add_sale(db_session, business, upload, 3, sale_date=None, total_amount=Decimal("10.00"))
    db_session.add(
        Expense(
            business_id=business.id,
            upload_session_id=upload.id,
            expense_date=date(2026, 6, 15),
            category="Rent",
            amount=Decimal("40.00"),
        )
    )
    db_session.flush()

    all_time = get_financial_summary(db_session, business.id)
    assert all_time["totalRevenue"] == 160.0  # NULL-dated sale included when no range given
    assert all_time["totalExpenses"] == 40.0
    assert all_time["profit"] == 120.0
    assert all_time["expenseBreakdown"] == {"Rent": 40.0}

    june = get_financial_summary(db_session, business.id, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))
    assert june["totalRevenue"] == 100.0  # July sale and NULL-dated sale both excluded
    assert june["totalExpenses"] == 40.0


def test_sales_trend_buckets_by_month(db_session):
    business, upload = _seed_business(db_session)
    _add_sale(db_session, business, upload, 1, sale_date=date(2026, 6, 1), total_amount=Decimal("100.00"))
    _add_sale(db_session, business, upload, 2, sale_date=date(2026, 6, 20), total_amount=Decimal("30.00"))
    _add_sale(db_session, business, upload, 3, sale_date=date(2026, 7, 5), total_amount=Decimal("70.00"))
    _add_sale(db_session, business, upload, 4, sale_date=None, total_amount=Decimal("999.00"))
    db_session.flush()

    trend = get_sales_trend(db_session, business.id, interval="month")
    assert trend["points"] == [
        {"period": "2026-06-01", "revenue": 130.0, "orders": 2},
        {"period": "2026-07-01", "revenue": 70.0, "orders": 1},
    ]


def test_top_products_by_revenue_and_quantity(db_session):
    business, upload = _seed_business(db_session)
    _add_sale(db_session, business, upload, 1, product_name="Rice", quantity=2, total_amount=Decimal("200.00"))
    _add_sale(db_session, business, upload, 2, product_name="Beans", quantity=10, total_amount=Decimal("50.00"))
    _add_sale(db_session, business, upload, 3, product_name="Rice", quantity=1, total_amount=Decimal("100.00"))
    db_session.flush()

    by_revenue = get_top_products(db_session, business.id, metric="revenue", limit=2)
    assert [p["productName"] for p in by_revenue["products"]] == ["Rice", "Beans"]
    assert by_revenue["products"][0]["revenue"] == 300.0

    by_quantity = get_top_products(db_session, business.id, metric="quantity", limit=2)
    assert [p["productName"] for p in by_quantity["products"]] == ["Beans", "Rice"]
    assert by_quantity["products"][0]["quantity"] == 10.0


def test_top_customers_ranked_by_spend(db_session):
    business, upload = _seed_business(db_session)
    _add_sale(db_session, business, upload, 1, customer_name="Ama", total_amount=Decimal("300.00"), sale_date=date(2026, 6, 1))
    _add_sale(db_session, business, upload, 2, customer_name="Kofi", total_amount=Decimal("500.00"), sale_date=date(2026, 6, 2))
    _add_sale(db_session, business, upload, 3, customer_name="Ama", total_amount=Decimal("100.00"), sale_date=date(2026, 6, 10))
    _add_sale(db_session, business, upload, 4, customer_name=None, total_amount=Decimal("999.00"))
    db_session.flush()

    result = get_top_customers(db_session, business.id, limit=5)
    assert result["customers"] == [
        {"customerName": "Kofi", "customerPhone": None, "totalSpent": 500.0, "orders": 1, "lastPurchase": "2026-06-02"},
        {"customerName": "Ama", "customerPhone": None, "totalSpent": 400.0, "orders": 2, "lastPurchase": "2026-06-10"},
    ]


def test_top_customers_deduplicates_name_variants(db_session):
    business, upload = _seed_business(db_session)
    _add_sale(db_session, business, upload, 1, customer_name="Ama Mensah", total_amount=Decimal("100.00"))
    _add_sale(db_session, business, upload, 2, customer_name="ama  mensah", total_amount=Decimal("50.00"))
    _add_sale(db_session, business, upload, 3, customer_name="AMA MENSAH", total_amount=Decimal("25.00"))
    db_session.flush()

    result = get_top_customers(db_session, business.id)
    assert len(result["customers"]) == 1
    assert result["customers"][0]["customerName"] == "Ama Mensah"  # first-seen casing
    assert result["customers"][0]["totalSpent"] == 175.0
    assert result["customers"][0]["orders"] == 3


def test_inactive_customers_uses_last_purchase_cutoff(db_session):
    business, upload = _seed_business(db_session)
    _add_sale(db_session, business, upload, 1, customer_name="Ama", sale_date=date(2026, 2, 1), total_amount=Decimal("50.00"))
    _add_sale(db_session, business, upload, 2, customer_name="Kofi", sale_date=date(2026, 7, 1), total_amount=Decimal("80.00"))
    db_session.flush()

    result = get_inactive_customers(db_session, business.id, days=90, today=date(2026, 7, 21))
    assert [c["customerName"] for c in result["customers"]] == ["Ama"]
    assert result["customers"][0]["lastPurchase"] == "2026-02-01"


def test_inventory_status_flags_low_stock(db_session):
    business, upload = _seed_business(db_session)
    db_session.add(
        Inventory(
            business_id=business.id,
            upload_session_id=upload.id,
            product_name="Rice",
            quantity=2,
            reorder_level=5,
            cost_price=Decimal("10.00"),
        )
    )
    db_session.add(
        Inventory(
            business_id=business.id,
            upload_session_id=upload.id,
            product_name="Beans",
            quantity=50,
            reorder_level=5,
            cost_price=Decimal("2.00"),
        )
    )
    db_session.flush()

    result = get_inventory_status(db_session, business.id)
    assert result["totalInventoryItems"] == 2
    assert result["totalInventoryValue"] == 120.0
    assert result["lowStockItems"] == [{"productName": "Rice", "quantity": 2, "reorderLevel": 5}]


# v0.5 slice 3 (multi-tenant hardening): parametrized over every entry in
# TOOL_SCHEMAS -- the model-facing tool catalog -- rather than a hand-picked
# subset, so a future tool added to the catalog is automatically covered by
# this leakage check instead of needing a manual addition (the same
# "invariant, not a snapshot" reasoning as test_tenant_isolation.py).
_LEAK_MARKERS = ("Yaw", "SecretProduct", 999.0)


@pytest.mark.parametrize("tool_name", [schema["function"]["name"] for schema in TOOL_SCHEMAS])
def test_tools_are_scoped_to_business(db_session, tool_name):
    business_a, upload_a = _seed_business(db_session)
    business_b, upload_b = _seed_business(db_session)
    _add_sale(db_session, business_a, upload_a, 1, customer_name="Ama", product_name="Rice", total_amount=Decimal("100.00"))
    _add_sale(
        db_session,
        business_b,
        upload_b,
        1,
        customer_name="Yaw",
        product_name="SecretProduct",
        total_amount=Decimal("999.00"),
    )
    db_session.add(
        Inventory(
            business_id=business_b.id,
            upload_session_id=upload_b.id,
            product_name="SecretProduct",
            quantity=1,
            reorder_level=5,
            cost_price=Decimal("999.00"),
        )
    )
    db_session.flush()

    result = execute_tool(db_session, business_a.id, tool_name, {})
    serialized = json.dumps(result)
    for marker in _LEAK_MARKERS:
        assert str(marker) not in serialized, (
            f"{tool_name} scoped to business_a leaked business_b's data "
            f"(found {marker!r} in the result): {serialized}"
        )


def test_execute_tool_dispatches_and_validates(db_session):
    business, upload = _seed_business(db_session)
    _add_sale(db_session, business, upload, 1, total_amount=Decimal("100.00"))
    db_session.flush()

    result = execute_tool(db_session, business.id, "get_financial_summary", {})
    assert result["totalRevenue"] == 100.0

    with pytest.raises(ToolArgumentError):
        execute_tool(db_session, business.id, "get_financial_summary", {"period_start": "June 2026"})
    with pytest.raises(ToolArgumentError):
        execute_tool(db_session, business.id, "get_top_products", {"metric": "popularity"})
    with pytest.raises(ToolArgumentError):
        execute_tool(db_session, business.id, "made_up_tool", {})


def test_execute_tool_clamps_limit(db_session):
    business, upload = _seed_business(db_session)
    for i in range(30):
        _add_sale(db_session, business, upload, i + 1, product_name=f"Product {i}", total_amount=Decimal("10.00"))
    db_session.flush()

    result = execute_tool(db_session, business.id, "get_top_products", {"limit": 100})
    assert len(result["products"]) == 25
