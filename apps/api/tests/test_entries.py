from datetime import date

from app.chat_tools import get_financial_summary
from app.models import Customer, Sale, UploadSession


def register_and_login(client, email):
    client.post(
        "/api/v1/auth/register",
        json={"fullName": "Test User", "email": email, "password": "password123"},
    )
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return login_response.json()["accessToken"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def _create_business(client, token, name="Entries Test Co"):
    return client.post("/api/v1/businesses/", json={"businessName": name}, headers=auth_header(token)).json()["id"]


def test_create_sale_entry_creates_manual_session_and_resolves_customer(client, db_session):
    token = register_and_login(client, "entries1@example.com")
    business_id = _create_business(client, token)

    response = client.post(
        f"/api/v1/businesses/{business_id}/entries/sales",
        json={
            "saleDate": "2026-03-01",
            "productName": "Rice",
            "quantity": 10,
            "unitPrice": "2.5",
            "customerName": "Ama Mensah",
            "customerPhone": "0244000000",
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["duplicateWarning"] is False

    sale = db_session.get(Sale, body["id"])
    assert sale.product_name == "Rice"
    assert sale.total_amount == 25  # computed: quantity * unitPrice, no discount given
    assert sale.raw_row_number == 1

    session = db_session.get(UploadSession, sale.upload_session_id)
    assert session.source_type == "manual"
    assert session.status == "COMPLETED"

    customer = db_session.query(Customer).filter(Customer.business_id == sale.business_id).one()
    assert customer.name == "Ama Mensah"
    assert sale.customer_id == customer.id


def test_create_sale_entry_visible_to_chat_financial_summary_tool(client, db_session):
    """The whole point of the shared ingest boundary: a manually-entered row
    needs zero special handling to show up in v0.2's SQL chat tools."""
    token = register_and_login(client, "entries2@example.com")
    business_id = _create_business(client, token)

    client.post(
        f"/api/v1/businesses/{business_id}/entries/sales",
        json={"saleDate": "2026-03-05", "productName": "Beans", "quantity": 4, "unitPrice": "3.0"},
        headers=auth_header(token),
    )

    import uuid

    summary = get_financial_summary(
        db_session, uuid.UUID(business_id), period_start=date(2026, 3, 1), period_end=date(2026, 3, 31)
    )
    assert summary["totalRevenue"] == 12.0


def test_create_expense_entry(client, db_session):
    token = register_and_login(client, "entries3@example.com")
    business_id = _create_business(client, token)

    response = client.post(
        f"/api/v1/businesses/{business_id}/entries/expenses",
        json={"expenseDate": "2026-03-02", "category": "Utilities", "vendor": "Power Co", "amount": "150.0"},
        headers=auth_header(token),
    )
    assert response.status_code == 201

    from app.models import Expense

    expense = db_session.get(Expense, response.json()["id"])
    assert expense.amount == 150
    assert expense.category == "Utilities"


def test_create_inventory_entry_resolves_supplier(client, db_session):
    token = register_and_login(client, "entries4@example.com")
    business_id = _create_business(client, token)

    response = client.post(
        f"/api/v1/businesses/{business_id}/entries/inventory",
        json={"productName": "Rice", "quantity": 100, "costPrice": "2.0", "supplier": "Acme Supplies"},
        headers=auth_header(token),
    )
    assert response.status_code == 201

    from app.models import Inventory, Supplier

    inventory_row = db_session.get(Inventory, response.json()["id"])
    supplier = db_session.query(Supplier).filter(Supplier.business_id == inventory_row.business_id).one()
    assert supplier.name == "Acme Supplies"
    assert inventory_row.supplier_id == supplier.id


def test_create_sale_entry_duplicate_warning(client, db_session):
    token = register_and_login(client, "entries5@example.com")
    business_id = _create_business(client, token)
    payload = {"saleDate": "2026-03-01", "productName": "Rice", "quantity": 10, "unitPrice": "2.5"}

    first = client.post(f"/api/v1/businesses/{business_id}/entries/sales", json=payload, headers=auth_header(token))
    assert first.json()["duplicateWarning"] is False

    second = client.post(f"/api/v1/businesses/{business_id}/entries/sales", json=payload, headers=auth_header(token))
    assert second.json()["duplicateWarning"] is True
    assert second.status_code == 201  # inserted anyway, warn-only


def test_entries_forbidden_for_non_owner(client, db_session):
    token = register_and_login(client, "entries6@example.com")
    business_id = _create_business(client, token)
    intruder_token = register_and_login(client, "entries_intruder@example.com")

    response = client.post(
        f"/api/v1/businesses/{business_id}/entries/sales",
        json={"saleDate": "2026-03-01", "productName": "Rice", "quantity": 10},
        headers=auth_header(intruder_token),
    )
    assert response.status_code == 403
