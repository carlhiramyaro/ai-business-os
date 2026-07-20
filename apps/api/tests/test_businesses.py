def register_and_login(client, email):
    client.post(
        "/api/v1/auth/register",
        json={"fullName": "Test User", "email": email, "password": "password123"},
    )
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return login_response.json()["accessToken"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_create_business(client):
    token = register_and_login(client, "owner@example.com")
    response = client.post(
        "/api/v1/businesses/",
        json={"businessName": "Acme Corp", "industry": "Retail"},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["businessName"] == "Acme Corp"
    assert body["industry"] == "Retail"
    assert body["currency"] is None


def test_create_business_requires_auth(client):
    response = client.post("/api/v1/businesses/", json={"businessName": "Acme"})
    assert response.status_code == 401


def test_list_businesses_only_returns_own(client):
    token_a = register_and_login(client, "a@example.com")
    token_b = register_and_login(client, "b@example.com")

    client.post("/api/v1/businesses/", json={"businessName": "A Co"}, headers=auth_header(token_a))
    client.post("/api/v1/businesses/", json={"businessName": "B Co"}, headers=auth_header(token_b))

    response = client.get("/api/v1/businesses/", headers=auth_header(token_a))
    assert response.status_code == 200
    names = [business["businessName"] for business in response.json()]
    assert names == ["A Co"]


def test_get_business_not_found(client):
    token = register_and_login(client, "owner2@example.com")
    response = client.get(
        "/api/v1/businesses/00000000-0000-0000-0000-000000000000", headers=auth_header(token)
    )
    assert response.status_code == 404


def test_get_business_forbidden_for_non_owner(client):
    token_a = register_and_login(client, "owner3@example.com")
    token_b = register_and_login(client, "intruder@example.com")

    created = client.post(
        "/api/v1/businesses/", json={"businessName": "Secret Co"}, headers=auth_header(token_a)
    )
    business_id = created.json()["id"]

    response = client.get(f"/api/v1/businesses/{business_id}", headers=auth_header(token_b))
    assert response.status_code == 403


def test_update_business_partial(client):
    token = register_and_login(client, "owner4@example.com")
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
    token = register_and_login(client, "owner5@example.com")
    created = client.post(
        "/api/v1/businesses/", json={"businessName": "Temp Co"}, headers=auth_header(token)
    )
    business_id = created.json()["id"]

    delete_response = client.delete(f"/api/v1/businesses/{business_id}", headers=auth_header(token))
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/businesses/{business_id}", headers=auth_header(token))
    assert get_response.status_code == 404
