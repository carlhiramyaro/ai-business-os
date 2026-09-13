"""GET /api/v1/auth/me and the just-in-time provisioning it triggers via
app/dependencies.py's get_current_user. There is no /register, /login,
/refresh, or /logout anymore -- Clerk owns those flows on the frontend.
See docs/decisions.md's Clerk-migration entry.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.models import User
from tests.auth_helpers import auth_header, mint_token, register_and_login
from tests.conftest import TEST_RSA_PRIVATE_KEY


def test_valid_token_jit_provisions_a_new_user(client):
    token = register_and_login("newuser@example.com", full_name="New User")
    response = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "newuser@example.com"
    assert body["fullName"] == "New User"
    assert "id" in body


def test_second_request_with_same_token_returns_same_user_not_a_duplicate(client, db_session):
    token = register_and_login("repeat@example.com")

    first = client.get("/api/v1/auth/me", headers=auth_header(token))
    second = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert db_session.query(User).filter(User.email == "repeat@example.com").count() == 1


def test_token_with_existing_email_links_by_email_instead_of_duplicating(client, db_session):
    """Simulates a pre-migration imported account: a users row with a real
    email but no clerk_user_id yet (see scripts/import_users_to_clerk.py).
    The first Clerk sign-in for that email must link the existing row, not
    create a second one."""
    existing = User(full_name="Imported Owner", email="imported@example.com", clerk_user_id=None)
    db_session.add(existing)
    db_session.commit()
    existing_id = str(existing.id)

    token = mint_token(f"user_{uuid.uuid4().hex}", "imported@example.com", "Imported Owner")
    response = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["id"] == existing_id
    assert db_session.query(User).filter(User.email == "imported@example.com").count() == 1

    db_session.refresh(existing)
    assert existing.clerk_user_id is not None


def test_me_requires_a_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_rejects_a_garbled_authorization_header(client):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "not-a-bearer-header"})
    assert response.status_code == 401


def test_me_rejects_a_token_signed_with_the_wrong_key(client):
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = {
        "sub": f"user_{uuid.uuid4().hex}",
        "iss": os.environ["CLERK_ISSUER"],
        "email": "forged@example.com",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    token = jwt.encode(payload, wrong_key, algorithm="RS256")
    response = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert response.status_code == 401


def test_me_rejects_an_expired_token(client):
    payload = {
        "sub": f"user_{uuid.uuid4().hex}",
        "iss": os.environ["CLERK_ISSUER"],
        "email": "expired@example.com",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    token = jwt.encode(payload, TEST_RSA_PRIVATE_KEY, algorithm="RS256")
    response = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert response.status_code == 401


def test_me_rejects_a_token_with_the_wrong_issuer(client):
    payload = {
        "sub": f"user_{uuid.uuid4().hex}",
        "iss": "https://not-clerk.example.test",
        "email": "wrong-issuer@example.com",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    token = jwt.encode(payload, TEST_RSA_PRIVATE_KEY, algorithm="RS256")
    response = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert response.status_code == 401
