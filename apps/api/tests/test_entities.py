import uuid

from app.entities import normalize_entity_name, resolve_customer, resolve_supplier
from app.models import Business, Customer, Supplier, User
from app.security import hash_password


def _seed_business(db_session):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.flush()
    business = Business(owner_id=user.id, business_name="Entities Test Co")
    db_session.add(business)
    db_session.flush()
    return business


def test_normalize_entity_name():
    assert normalize_entity_name("  Ama   Mensah ") == "ama mensah"
    assert normalize_entity_name("AMA MENSAH") == "ama mensah"
    assert normalize_entity_name(None) is None
    assert normalize_entity_name("   ") is None


def test_resolve_customer_get_or_create_dedupes_variants(db_session):
    business = _seed_business(db_session)

    first = resolve_customer(db_session, business.id, "Ama Mensah")
    second = resolve_customer(db_session, business.id, "ama  mensah")
    third = resolve_customer(db_session, business.id, " AMA MENSAH ")

    assert first.id == second.id == third.id
    assert first.name == "Ama Mensah"  # first-seen casing wins
    assert db_session.query(Customer).filter(Customer.business_id == business.id).count() == 1


def test_resolve_customer_blank_name_returns_none(db_session):
    business = _seed_business(db_session)
    assert resolve_customer(db_session, business.id, None) is None
    assert resolve_customer(db_session, business.id, "   ") is None
    assert db_session.query(Customer).count() == 0


def test_resolve_customer_phone_last_nonempty_wins(db_session):
    business = _seed_business(db_session)

    customer = resolve_customer(db_session, business.id, "Ama", phone=None)
    assert customer.phone is None

    resolve_customer(db_session, business.id, "Ama", phone="0244000000")
    assert customer.phone == "0244000000"

    # a later row without a phone must not erase the known one
    resolve_customer(db_session, business.id, "Ama", phone="  ")
    assert customer.phone == "0244000000"

    resolve_customer(db_session, business.id, "Ama", phone="0244111111")
    assert customer.phone == "0244111111"


def test_resolution_is_scoped_per_business(db_session):
    business_a = _seed_business(db_session)
    business_b = _seed_business(db_session)

    customer_a = resolve_customer(db_session, business_a.id, "Ama")
    customer_b = resolve_customer(db_session, business_b.id, "Ama")
    supplier_a = resolve_supplier(db_session, business_a.id, "Golden Rice Ltd")
    supplier_b = resolve_supplier(db_session, business_b.id, "golden rice ltd")

    assert customer_a.id != customer_b.id
    assert supplier_a.id != supplier_b.id
    assert db_session.query(Customer).count() == 2
    assert db_session.query(Supplier).count() == 2


def register_and_login(client, email):
    client.post(
        "/api/v1/auth/register",
        json={"fullName": "Test User", "email": email, "password": "password123"},
    )
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return login_response.json()["accessToken"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_list_customers_and_suppliers_endpoints(client, db_session):
    token = register_and_login(client, "entities1@example.com")
    business_id = client.post(
        "/api/v1/businesses/", json={"businessName": "Entities API Co"}, headers=auth_header(token)
    ).json()["id"]

    resolve_customer(db_session, uuid.UUID(business_id), "Kofi Boateng", phone="0244000000")
    resolve_customer(db_session, uuid.UUID(business_id), "Ama Mensah")
    resolve_supplier(db_session, uuid.UUID(business_id), "Golden Rice Ltd")
    db_session.commit()

    customers = client.get(f"/api/v1/businesses/{business_id}/customers", headers=auth_header(token)).json()
    assert [(c["name"], c["phone"]) for c in customers] == [
        ("Ama Mensah", None),
        ("Kofi Boateng", "0244000000"),
    ]

    suppliers = client.get(f"/api/v1/businesses/{business_id}/suppliers", headers=auth_header(token)).json()
    assert [s["name"] for s in suppliers] == ["Golden Rice Ltd"]


def test_entities_endpoints_forbidden_for_non_owner(client, db_session):
    token = register_and_login(client, "entities2@example.com")
    business_id = client.post(
        "/api/v1/businesses/", json={"businessName": "Entities Private Co"}, headers=auth_header(token)
    ).json()["id"]

    intruder_token = register_and_login(client, "entities_intruder@example.com")
    response = client.get(f"/api/v1/businesses/{business_id}/customers", headers=auth_header(intruder_token))
    assert response.status_code == 403
    response = client.get(f"/api/v1/businesses/{business_id}/suppliers", headers=auth_header(intruder_token))
    assert response.status_code == 403
