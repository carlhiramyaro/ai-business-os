from app.models.business import DEFAULT_CURRENCY
from tests.auth_helpers import auth_header, register_and_login


def test_create_business(client):
    token = register_and_login("owner@example.com")
    response = client.post(
        "/api/v1/businesses/",
        json={"businessName": "Acme Corp", "industry": "Retail"},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["businessName"] == "Acme Corp"
    assert body["industry"] == "Retail"
    # [2026-08-27] was `is None`. A NULL currency degraded the chat agent's
    # system prompt (app/chat_generation.py) to "amounts are in the
    # business's local currency", so live answers came back as bare
    # unlabelled numbers -- "total sales amount to 115.0" to an owner making
    # money decisions. See docs/decisions.md.
    assert body["currency"] == DEFAULT_CURRENCY == "GHS"


def test_create_business_respects_explicit_currency(client):
    """The default must not clobber an owner who does state a currency --
    Ledger is Ghana-first, not Ghana-only."""
    token = register_and_login("kenyan@example.com")
    response = client.post(
        "/api/v1/businesses/",
        json={"businessName": "Nairobi Retail", "currency": "KES"},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    assert response.json()["currency"] == "KES"


def test_update_business_can_change_currency(client):
    token = register_and_login("switcher@example.com")
    business = client.post(
        "/api/v1/businesses/", json={"businessName": "Switcher Co"}, headers=auth_header(token)
    ).json()
    assert business["currency"] == "GHS"

    response = client.patch(
        f"/api/v1/businesses/{business['id']}", json={"currency": "NGN"}, headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["currency"] == "NGN"


def test_update_business_without_currency_leaves_it_untouched(client):
    """The route applies updates with exclude_unset=True, so an unrelated
    PATCH must not blank a NOT NULL column."""
    token = register_and_login("partial@example.com")
    business = client.post(
        "/api/v1/businesses/", json={"businessName": "Partial Co", "currency": "KES"}, headers=auth_header(token)
    ).json()

    response = client.patch(
        f"/api/v1/businesses/{business['id']}", json={"industry": "Retail"}, headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["currency"] == "KES"


def test_update_business_rejects_explicit_null_currency(client):
    """An explicit null IS "set", so exclude_unset would write it to a NOT
    NULL column -- a 500 from the database. Must be a 422 from validation."""
    token = register_and_login("nuller@example.com")
    business = client.post(
        "/api/v1/businesses/", json={"businessName": "Null Co"}, headers=auth_header(token)
    ).json()

    response = client.patch(
        f"/api/v1/businesses/{business['id']}", json={"currency": None}, headers=auth_header(token)
    )
    assert response.status_code == 422

    unchanged = client.get(f"/api/v1/businesses/{business['id']}", headers=auth_header(token))
    assert unchanged.json()["currency"] == "GHS"


def test_create_business_requires_auth(client):
    response = client.post("/api/v1/businesses/", json={"businessName": "Acme"})
    assert response.status_code == 401


def test_list_businesses_only_returns_own(client):
    token_a = register_and_login("a@example.com")
    token_b = register_and_login("b@example.com")

    client.post("/api/v1/businesses/", json={"businessName": "A Co"}, headers=auth_header(token_a))
    client.post("/api/v1/businesses/", json={"businessName": "B Co"}, headers=auth_header(token_b))

    response = client.get("/api/v1/businesses/", headers=auth_header(token_a))
    assert response.status_code == 200
    names = [business["businessName"] for business in response.json()]
    assert names == ["A Co"]


def test_get_business_not_found(client):
    token = register_and_login("owner2@example.com")
    response = client.get(
        "/api/v1/businesses/00000000-0000-0000-0000-000000000000", headers=auth_header(token)
    )
    assert response.status_code == 404


def test_get_business_forbidden_for_non_owner(client):
    token_a = register_and_login("owner3@example.com")
    token_b = register_and_login("intruder@example.com")

    created = client.post(
        "/api/v1/businesses/", json={"businessName": "Secret Co"}, headers=auth_header(token_a)
    )
    business_id = created.json()["id"]

    response = client.get(f"/api/v1/businesses/{business_id}", headers=auth_header(token_b))
    assert response.status_code == 403


def test_update_business_partial(client):
    token = register_and_login("owner4@example.com")
    created = client.post(
        "/api/v1/businesses/",
        json={"businessName": "Old Name", "industry": "Retail"},
        headers=auth_header(token),
    )
    business_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/businesses/{business_id}",
        json={"businessName": "New Name"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["businessName"] == "New Name"
    assert body["industry"] == "Retail"


def test_delete_business(client):
    token = register_and_login("owner5@example.com")
    created = client.post(
        "/api/v1/businesses/", json={"businessName": "Temp Co"}, headers=auth_header(token)
    )
    business_id = created.json()["id"]

    delete_response = client.delete(f"/api/v1/businesses/{business_id}", headers=auth_header(token))
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/businesses/{business_id}", headers=auth_header(token))
    assert get_response.status_code == 404
