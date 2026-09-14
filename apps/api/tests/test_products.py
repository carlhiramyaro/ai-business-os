import uuid
from decimal import Decimal

from app.entities import resolve_product
from app.inventory import record_recount, record_stock_movement
from app.models import ProductUnit
from tests.auth_helpers import auth_header, register_and_login


def _create_business(client, token, name="Products Test Co"):
    return client.post("/api/v1/businesses/", json={"businessName": name}, headers=auth_header(token)).json()["id"]


def test_list_products_empty(client, db_session):
    token = register_and_login("products1@example.com")
    business_id = _create_business(client, token)

    response = client.get(f"/api/v1/businesses/{business_id}/products", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json() == []


def test_list_products_returns_current_stock_and_low_stock_flag(client, db_session):
    token = register_and_login("products2@example.com")
    business_id = _create_business(client, token)

    rice = resolve_product(db_session, uuid.UUID(business_id), "Rice", reorder_level=10, cost_price=Decimal("2.00"))
    record_recount(db_session, uuid.UUID(business_id), rice, 5)  # below reorder_level=10
    beans = resolve_product(db_session, uuid.UUID(business_id), "Beans", reorder_level=10)
    record_recount(db_session, uuid.UUID(business_id), beans, 50)  # above reorder_level
    db_session.commit()

    response = client.get(f"/api/v1/businesses/{business_id}/products", headers=auth_header(token))
    assert response.status_code == 200
    items = {item["name"]: item for item in response.json()}
    assert items["Rice"]["quantity"] == 5
    assert items["Rice"]["lowStock"] is True
    assert items["Beans"]["quantity"] == 50
    assert items["Beans"]["lowStock"] is False


def test_update_product_patches_only_given_fields(client, db_session):
    token = register_and_login("products3@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    db_session.commit()

    response = client.patch(
        f"/api/v1/businesses/{business_id}/products/{product.id}",
        json={"sku": "RICE-5KG", "reorderLevel": 10},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sku"] == "RICE-5KG"
    assert body["reorderLevel"] == 10
    assert body["category"] is None  # untouched


def test_create_stock_adjustment_restock_increases_stock(client, db_session):
    token = register_and_login("products4@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    db_session.commit()

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/stock-movements",
        json={"reason": "restock", "quantity": 50},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["quantityDelta"] == 50
    assert body["currentStock"] == 50


def test_create_stock_adjustment_recount_sets_absolute_count(client, db_session):
    token = register_and_login("products5@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    record_stock_movement(db_session, uuid.UUID(business_id), product, 50, reason="restock")
    db_session.commit()

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/stock-movements",
        json={"reason": "recount", "quantity": 33},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["quantityDelta"] == -17
    assert body["currentStock"] == 33


def test_create_stock_adjustment_unknown_unit_returns_400(client, db_session):
    token = register_and_login("products6@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    db_session.commit()

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/stock-movements",
        json={"reason": "restock", "quantity": 2, "unitName": "carton"},
        headers=auth_header(token),
    )
    assert response.status_code == 400


def test_declare_product_unit_then_adjust_using_it(client, db_session):
    token = register_and_login("products7@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice", base_unit="piece")
    db_session.commit()

    declare_response = client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/units",
        json={"unitName": "carton", "conversionToBase": 24},
        headers=auth_header(token),
    )
    assert declare_response.status_code == 201
    assert db_session.query(ProductUnit).filter(ProductUnit.product_id == product.id).count() == 1

    adjust_response = client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/stock-movements",
        json={"reason": "restock", "quantity": 2, "unitName": "carton"},
        headers=auth_header(token),
    )
    assert adjust_response.status_code == 201
    assert adjust_response.json()["currentStock"] == 48


def test_declare_product_unit_twice_updates_conversion_rather_than_duplicating(client, db_session):
    token = register_and_login("products8@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    db_session.commit()

    client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/units",
        json={"unitName": "carton", "conversionToBase": 24},
        headers=auth_header(token),
    )
    client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/units",
        json={"unitName": "carton", "conversionToBase": 12},
        headers=auth_header(token),
    )

    units = db_session.query(ProductUnit).filter(ProductUnit.product_id == product.id).all()
    assert len(units) == 1
    assert units[0].conversion_to_base == 12


def test_products_endpoints_forbidden_for_non_owner(client, db_session):
    token = register_and_login("products9@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    db_session.commit()

    intruder_token = register_and_login("products_intruder@example.com")
    intruder_headers = auth_header(intruder_token)

    assert client.get(f"/api/v1/businesses/{business_id}/products", headers=intruder_headers).status_code == 403
    assert (
        client.patch(
            f"/api/v1/businesses/{business_id}/products/{product.id}", json={"sku": "X"}, headers=intruder_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/businesses/{business_id}/products/{product.id}/stock-movements",
            json={"reason": "restock", "quantity": 1},
            headers=intruder_headers,
        ).status_code
        == 403
    )


def test_get_owned_product_404_for_unknown_product(client, db_session):
    token = register_and_login("products10@example.com")
    business_id = _create_business(client, token)

    response = client.patch(
        f"/api/v1/businesses/{business_id}/products/{uuid.uuid4()}", json={"sku": "X"}, headers=auth_header(token)
    )
    assert response.status_code == 404


def test_suggested_sku_slugifies_product_name(client, db_session):
    token = register_and_login("products11@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Palm Oil")
    db_session.commit()

    response = client.get(
        f"/api/v1/businesses/{business_id}/products/{product.id}/suggested-sku", headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["sku"] == "PALM-OIL"


def test_suggested_sku_disambiguates_against_other_products_in_the_business(client, db_session):
    token = register_and_login("products12@example.com")
    business_id = _create_business(client, token)
    # Distinct products (different normalized_name -> not deduped by
    # resolve_product) whose names slugify to the same base SKU.
    rice = resolve_product(db_session, uuid.UUID(business_id), "Rice", sku="RICE")
    rice_variant = resolve_product(db_session, uuid.UUID(business_id), "Rice!")
    db_session.commit()

    response = client.get(
        f"/api/v1/businesses/{business_id}/products/{rice_variant.id}/suggested-sku", headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["sku"] == "RICE-2"

    # a product's own current sku never counts as a collision against itself
    response = client.get(
        f"/api/v1/businesses/{business_id}/products/{rice.id}/suggested-sku", headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["sku"] == "RICE"


def test_suggested_sku_forbidden_for_non_owner(client, db_session):
    token = register_and_login("products13@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    db_session.commit()

    intruder_token = register_and_login("products_intruder2@example.com")
    response = client.get(
        f"/api/v1/businesses/{business_id}/products/{product.id}/suggested-sku",
        headers=auth_header(intruder_token),
    )
    assert response.status_code == 403
