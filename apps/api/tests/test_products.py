import uuid
from decimal import Decimal

from app.entities import resolve_product
from app.inventory import record_recount, record_stock_movement
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
    assert Decimal(items["Rice"]["quantity"]) == 5
    assert items["Rice"]["lowStock"] is True
    assert Decimal(items["Beans"]["quantity"]) == 50
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
    assert Decimal(body["reorderLevel"]) == 10
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
    assert Decimal(body["quantityDelta"]) == 50
    assert Decimal(body["currentStock"]) == 50


def test_create_stock_adjustment_supports_fractional_quantity(client, db_session):
    """A loose product sold by weight -- Decimal end to end, not int. See
    docs/decisions.md [2026-09-14]."""
    token = register_and_login("products4b@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Meat", base_unit="kg")
    db_session.commit()

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/stock-movements",
        json={"reason": "restock", "quantity": "10.5"},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    assert Decimal(response.json()["currentStock"]) == Decimal("10.5")


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
    assert Decimal(body["quantityDelta"]) == -17
    assert Decimal(body["currentStock"]) == 33


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


# --- pack relationships / repack (docs/decisions.md [2026-09-14]) ----------


def test_get_pack_relationship_is_none_when_undeclared(client, db_session):
    token = register_and_login("products14@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Coke Case")
    db_session.commit()

    response = client.get(
        f"/api/v1/businesses/{business_id}/products/{product.id}/pack-relationship", headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json() is None


def test_declare_pack_relationship_creates_link(client, db_session):
    token = register_and_login("products15@example.com")
    business_id = _create_business(client, token)
    case = resolve_product(db_session, uuid.UUID(business_id), "Coke Case")
    can = resolve_product(db_session, uuid.UUID(business_id), "Coke Can")
    db_session.commit()

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{case.id}/pack-relationship",
        json={"unitProductId": str(can.id), "unitsPerPack": 24},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["unitProductId"] == str(can.id)
    assert body["unitProductName"] == "Coke Can"
    assert Decimal(body["unitsPerPack"]) == 24

    get_response = client.get(
        f"/api/v1/businesses/{business_id}/products/{case.id}/pack-relationship", headers=auth_header(token)
    )
    assert get_response.json()["unitProductId"] == str(can.id)


def test_declare_pack_relationship_twice_updates_rather_than_duplicating(client, db_session):
    token = register_and_login("products16@example.com")
    business_id = _create_business(client, token)
    case = resolve_product(db_session, uuid.UUID(business_id), "Coke Case")
    can = resolve_product(db_session, uuid.UUID(business_id), "Coke Can")
    db_session.commit()

    client.post(
        f"/api/v1/businesses/{business_id}/products/{case.id}/pack-relationship",
        json={"unitProductId": str(can.id), "unitsPerPack": 24},
        headers=auth_header(token),
    )
    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{case.id}/pack-relationship",
        json={"unitProductId": str(can.id), "unitsPerPack": 12},
        headers=auth_header(token),
    )
    assert response.status_code == 201

    from app.models import PackRelationship

    relationships = db_session.query(PackRelationship).filter(PackRelationship.pack_product_id == case.id).all()
    assert len(relationships) == 1
    assert relationships[0].units_per_pack == 12


def test_declare_pack_relationship_rejects_linking_to_itself(client, db_session):
    token = register_and_login("products17@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    db_session.commit()

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/pack-relationship",
        json={"unitProductId": str(product.id), "unitsPerPack": 2},
        headers=auth_header(token),
    )
    assert response.status_code == 400


def test_declare_pack_relationship_404_for_unit_product_in_another_business(client, db_session):
    token = register_and_login("products18@example.com")
    business_id = _create_business(client, token)
    case = resolve_product(db_session, uuid.UUID(business_id), "Coke Case")

    other_business_id = _create_business(client, token, name="Another Co")
    other_product = resolve_product(db_session, uuid.UUID(other_business_id), "Something Else")
    db_session.commit()

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{case.id}/pack-relationship",
        json={"unitProductId": str(other_product.id), "unitsPerPack": 2},
        headers=auth_header(token),
    )
    assert response.status_code == 404


def test_create_repack_break_converts_pack_stock_into_unit_stock(client, db_session):
    token = register_and_login("products19@example.com")
    business_id = _create_business(client, token)
    case = resolve_product(db_session, uuid.UUID(business_id), "Coke Case")
    can = resolve_product(db_session, uuid.UUID(business_id), "Coke Can")
    record_stock_movement(db_session, uuid.UUID(business_id), case, 5, reason="restock")
    db_session.commit()

    client.post(
        f"/api/v1/businesses/{business_id}/products/{case.id}/pack-relationship",
        json={"unitProductId": str(can.id), "unitsPerPack": 24},
        headers=auth_header(token),
    )

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{case.id}/repack",
        json={"quantity": 1, "direction": "break"},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert Decimal(body["packCurrentStock"]) == 4
    assert Decimal(body["unitCurrentStock"]) == 24


def test_create_repack_without_relationship_returns_400(client, db_session):
    token = register_and_login("products20@example.com")
    business_id = _create_business(client, token)
    product = resolve_product(db_session, uuid.UUID(business_id), "Rice")
    db_session.commit()

    response = client.post(
        f"/api/v1/businesses/{business_id}/products/{product.id}/repack",
        json={"quantity": 1, "direction": "break"},
        headers=auth_header(token),
    )
    assert response.status_code == 400


def test_pack_relationship_and_repack_forbidden_for_non_owner(client, db_session):
    token = register_and_login("products21@example.com")
    business_id = _create_business(client, token)
    case = resolve_product(db_session, uuid.UUID(business_id), "Coke Case")
    can = resolve_product(db_session, uuid.UUID(business_id), "Coke Can")
    db_session.commit()

    intruder_token = register_and_login("products_intruder3@example.com")
    intruder_headers = auth_header(intruder_token)

    assert (
        client.get(
            f"/api/v1/businesses/{business_id}/products/{case.id}/pack-relationship", headers=intruder_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/businesses/{business_id}/products/{case.id}/pack-relationship",
            json={"unitProductId": str(can.id), "unitsPerPack": 24},
            headers=intruder_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/businesses/{business_id}/products/{case.id}/repack",
            json={"quantity": 1, "direction": "break"},
            headers=intruder_headers,
        ).status_code
        == 403
    )
