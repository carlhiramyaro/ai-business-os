import uuid
from datetime import date
from decimal import Decimal

from app.models import Expense, Sale, UploadSession
from tests.auth_helpers import auth_header, register_and_login


def _create_business(client, token, name="Ledger Test Co"):
    return client.post("/api/v1/businesses/", json={"businessName": name}, headers=auth_header(token)).json()["id"]


def _seed_session(db_session, business_id):
    session = UploadSession(business_id=uuid.UUID(business_id), source_type="csv", status="COMPLETED")
    db_session.add(session)
    db_session.flush()
    return session


def test_list_sales_empty(client, db_session):
    token = register_and_login("ledger1@example.com")
    business_id = _create_business(client, token)

    response = client.get(f"/api/v1/businesses/{business_id}/sales", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json() == []


def test_list_sales_returns_business_rows_newest_first(client, db_session):
    token = register_and_login("ledger2@example.com")
    business_id = _create_business(client, token)
    session = _seed_session(db_session, business_id)
    db_session.add(
        Sale(
            business_id=uuid.UUID(business_id),
            upload_session_id=session.id,
            sale_date=date(2026, 1, 1),
            product_name="Rice",
            quantity=1,
            total_amount=Decimal("10.00"),
            raw_row_number=1,
        )
    )
    db_session.add(
        Sale(
            business_id=uuid.UUID(business_id),
            upload_session_id=session.id,
            sale_date=date(2026, 2, 1),
            product_name="Beans",
            quantity=2,
            total_amount=Decimal("20.00"),
            raw_row_number=2,
        )
    )
    db_session.commit()

    response = client.get(f"/api/v1/businesses/{business_id}/sales", headers=auth_header(token))
    assert response.status_code == 200
    names = [row["productName"] for row in response.json()]
    assert names == ["Beans", "Rice"]  # newest sale_date first


def test_list_sales_pagination(client, db_session):
    token = register_and_login("ledger3@example.com")
    business_id = _create_business(client, token)
    session = _seed_session(db_session, business_id)
    for i in range(5):
        db_session.add(
            Sale(
                business_id=uuid.UUID(business_id),
                upload_session_id=session.id,
                sale_date=date(2026, 1, i + 1),
                product_name=f"Product {i}",
                quantity=1,
                total_amount=Decimal("10.00"),
                raw_row_number=i + 1,
            )
        )
    db_session.commit()

    response = client.get(f"/api/v1/businesses/{business_id}/sales?limit=2&offset=1", headers=auth_header(token))
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_expenses_returns_business_rows_newest_first(client, db_session):
    token = register_and_login("ledger4@example.com")
    business_id = _create_business(client, token)
    session = _seed_session(db_session, business_id)
    db_session.add(
        Expense(
            business_id=uuid.UUID(business_id),
            upload_session_id=session.id,
            expense_date=date(2026, 1, 1),
            category="Rent",
            amount=Decimal("50.00"),
        )
    )
    db_session.add(
        Expense(
            business_id=uuid.UUID(business_id),
            upload_session_id=session.id,
            expense_date=date(2026, 2, 1),
            category="Utilities",
            amount=Decimal("30.00"),
        )
    )
    db_session.commit()

    response = client.get(f"/api/v1/businesses/{business_id}/expenses", headers=auth_header(token))
    assert response.status_code == 200
    categories = [row["category"] for row in response.json()]
    assert categories == ["Utilities", "Rent"]


def test_sales_and_expenses_forbidden_for_non_owner(client, db_session):
    token = register_and_login("ledger5@example.com")
    business_id = _create_business(client, token)

    intruder_token = register_and_login("ledger_intruder@example.com")
    intruder_headers = auth_header(intruder_token)

    assert client.get(f"/api/v1/businesses/{business_id}/sales", headers=intruder_headers).status_code == 403
    assert client.get(f"/api/v1/businesses/{business_id}/expenses", headers=intruder_headers).status_code == 403
