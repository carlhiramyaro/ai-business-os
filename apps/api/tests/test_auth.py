def register(client, email="user@example.com", password="password123"):
    return client.post(
        "/api/v1/auth/register",
        json={"fullName": "Test User", "email": email, "password": password},
    )


def login(client, email="user@example.com", password="password123"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_register_creates_user(client):
    response = register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["fullName"] == "Test User"
    assert "id" in body
    assert "passwordHash" not in body


def test_register_duplicate_email_rejected(client):
    register(client)
    response = register(client)
    assert response.status_code == 409


def test_login_wrong_password_rejected(client):
    register(client)
    response = login(client, password="wrong-password")
    assert response.status_code == 401


def test_login_unknown_email_rejected(client):
    response = login(client, email="nobody@example.com")
    assert response.status_code == 401


def test_login_returns_tokens(client):
    register(client)
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["accessToken"]
    assert body["refreshToken"]
    assert body["tokenType"] == "bearer"


def test_me_requires_valid_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user(client):
    register(client)
    access_token = login(client).json()["accessToken"]
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"


def test_refresh_rotates_token_and_invalidates_old_one(client):
    register(client)
    old_refresh_token = login(client).json()["refreshToken"]

    refreshed = client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh_token})
    assert refreshed.status_code == 200
    new_refresh_token = refreshed.json()["refreshToken"]
    assert new_refresh_token != old_refresh_token

    reuse_attempt = client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh_token})
    assert reuse_attempt.status_code == 401


def test_logout_revokes_refresh_token(client):
    register(client)
    refresh_token = login(client).json()["refreshToken"]

    logout_response = client.post("/api/v1/auth/logout", json={"refreshToken": refresh_token})
    assert logout_response.status_code == 204

    refresh_after_logout = client.post("/api/v1/auth/refresh", json={"refreshToken": refresh_token})
    assert refresh_after_logout.status_code == 401
