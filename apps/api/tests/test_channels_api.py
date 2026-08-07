import uuid
from datetime import datetime, timedelta, timezone

from app.channels import generate_link_code, redeem_link_code
from app.models import Business, ChannelIdentity, ChannelLinkCode, User
from app.security import hash_password


def register_and_login(client, email):
    client.post("/api/v1/auth/register", json={"fullName": "Test User", "email": email, "password": "password123"})
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return login_response.json()["accessToken"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def _create_business(client, token, name="Channel Co"):
    return client.post("/api/v1/businesses/", json={"businessName": name}, headers=auth_header(token)).json()


def _create_user_and_business(db_session, business_name="Channel Co"):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("pw"))
    db_session.add(user)
    db_session.flush()
    business = Business(owner_id=user.id, business_name=business_name)
    db_session.add(business)
    db_session.flush()
    return user, business


def test_generate_link_code_returns_code_and_expiry(client, db_session):
    token = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business = _create_business(client, token)

    response = client.post(
        f"/api/v1/businesses/{business['id']}/channels/whatsapp/link-code", headers=auth_header(token)
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["code"]) == 6
    assert body["code"].isupper()
    assert "expiresAt" in body

    stored = db_session.query(ChannelLinkCode).filter(ChannelLinkCode.code == body["code"]).one()
    assert stored.business_id == uuid.UUID(business["id"])
    assert stored.consumed_at is None


def test_redeem_link_code_creates_identity(db_session):
    user, business = _create_user_and_business(db_session, "Redeem Co")
    link_code = generate_link_code(db_session, user.id, business.id)
    db_session.flush()

    identity = redeem_link_code(db_session, link_code.code, "whatsapp", "233241234567", display_name="Ama")
    assert identity is not None
    assert identity.business_id == business.id
    assert identity.user_id == user.id
    assert identity.external_id == "233241234567"
    assert link_code.consumed_at is not None


def test_redeem_link_code_is_case_insensitive_and_trims(db_session):
    user, business = _create_user_and_business(db_session, "Case Co")
    link_code = generate_link_code(db_session, user.id, business.id)
    db_session.flush()

    identity = redeem_link_code(db_session, f"  {link_code.code.lower()}  ", "whatsapp", "233241234000")
    assert identity is not None


def test_redeem_link_code_rejects_unknown_code(db_session):
    assert redeem_link_code(db_session, "ZZZZZZ", "whatsapp", "233241234567") is None


def test_redeem_link_code_rejects_expired_code(db_session):
    user, business = _create_user_and_business(db_session, "Expired Co")
    link_code = generate_link_code(db_session, user.id, business.id)
    link_code.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.flush()

    assert redeem_link_code(db_session, link_code.code, "whatsapp", "233241234567") is None


def test_redeem_link_code_rejects_already_consumed_code(db_session):
    user, business = _create_user_and_business(db_session, "Consumed Co")
    link_code = generate_link_code(db_session, user.id, business.id)
    db_session.flush()

    first = redeem_link_code(db_session, link_code.code, "whatsapp", "233241234567")
    assert first is not None

    second = redeem_link_code(db_session, link_code.code, "whatsapp", "233249999999")
    assert second is None


def test_redeem_link_code_relinking_replaces_existing_identity(db_session):
    """One phone number maps to exactly one business at a time -- linking
    a number already linked elsewhere replaces the mapping, it doesn't
    create a second ChannelIdentity row. See app/models/channel.py."""
    user, business_a = _create_user_and_business(db_session, "Business A")
    business_b = Business(owner_id=user.id, business_name="Business B")
    db_session.add(business_b)
    db_session.flush()

    code_a = generate_link_code(db_session, user.id, business_a.id)
    db_session.flush()
    identity = redeem_link_code(db_session, code_a.code, "whatsapp", "233241111111")
    assert identity.business_id == business_a.id

    code_b = generate_link_code(db_session, user.id, business_b.id)
    db_session.flush()
    identity = redeem_link_code(db_session, code_b.code, "whatsapp", "233241111111")
    assert identity.business_id == business_b.id

    count = (
        db_session.query(ChannelIdentity)
        .filter(ChannelIdentity.channel == "whatsapp", ChannelIdentity.external_id == "233241111111")
        .count()
    )
    assert count == 1


def test_list_and_unlink_channels(client, db_session):
    token = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business = _create_business(client, token)

    code_response = client.post(
        f"/api/v1/businesses/{business['id']}/channels/whatsapp/link-code", headers=auth_header(token)
    ).json()
    identity = redeem_link_code(db_session, code_response["code"], "whatsapp", "233247654321", display_name="Kofi")
    db_session.commit()
    assert identity is not None

    list_response = client.get(f"/api/v1/businesses/{business['id']}/channels/", headers=auth_header(token))
    assert list_response.status_code == 200
    [entry] = list_response.json()
    assert entry["displayName"] == "Kofi"
    assert entry["maskedExternalId"] == "•••4321"

    delete_response = client.delete(
        f"/api/v1/businesses/{business['id']}/channels/{entry['id']}", headers=auth_header(token)
    )
    assert delete_response.status_code == 204

    empty_list = client.get(f"/api/v1/businesses/{business['id']}/channels/", headers=auth_header(token))
    assert empty_list.json() == []


def test_channels_scoped_to_owning_business(client, db_session):
    token_a = register_and_login(client, f"{uuid.uuid4()}@example.com")
    token_b = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business_a = _create_business(client, token_a, "Business A")

    response = client.get(f"/api/v1/businesses/{business_a['id']}/channels/", headers=auth_header(token_b))
    assert response.status_code == 403

    link_response = client.post(
        f"/api/v1/businesses/{business_a['id']}/channels/whatsapp/link-code", headers=auth_header(token_b)
    )
    assert link_response.status_code == 403


# --- v0.6 slice 2: notification_frequency ------------------------------------


def test_list_channels_defaults_to_off(client, db_session):
    token = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business = _create_business(client, token)
    code_response = client.post(
        f"/api/v1/businesses/{business['id']}/channels/whatsapp/link-code", headers=auth_header(token)
    ).json()
    redeem_link_code(db_session, code_response["code"], "whatsapp", "233247000000")
    db_session.commit()

    [entry] = client.get(f"/api/v1/businesses/{business['id']}/channels/", headers=auth_header(token)).json()
    assert entry["notificationFrequency"] == "off"


def test_update_channel_frequency(client, db_session):
    token = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business = _create_business(client, token)
    code_response = client.post(
        f"/api/v1/businesses/{business['id']}/channels/whatsapp/link-code", headers=auth_header(token)
    ).json()
    identity = redeem_link_code(db_session, code_response["code"], "whatsapp", "233247000001")
    db_session.commit()

    response = client.patch(
        f"/api/v1/businesses/{business['id']}/channels/{identity.id}",
        json={"notificationFrequency": "daily_digest"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["notificationFrequency"] == "daily_digest"

    [entry] = client.get(f"/api/v1/businesses/{business['id']}/channels/", headers=auth_header(token)).json()
    assert entry["notificationFrequency"] == "daily_digest"


def test_update_channel_frequency_rejects_invalid_value(client, db_session):
    token = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business = _create_business(client, token)
    code_response = client.post(
        f"/api/v1/businesses/{business['id']}/channels/whatsapp/link-code", headers=auth_header(token)
    ).json()
    identity = redeem_link_code(db_session, code_response["code"], "whatsapp", "233247000002")
    db_session.commit()

    response = client.patch(
        f"/api/v1/businesses/{business['id']}/channels/{identity.id}",
        json={"notificationFrequency": "every_five_minutes"},
        headers=auth_header(token),
    )
    assert response.status_code == 422


def test_update_channel_frequency_not_found_for_other_business(client, db_session):
    token_a = register_and_login(client, f"{uuid.uuid4()}@example.com")
    token_b = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business_a = _create_business(client, token_a, "Business A")
    business_b = _create_business(client, token_b, "Business B")
    code_response = client.post(
        f"/api/v1/businesses/{business_a['id']}/channels/whatsapp/link-code", headers=auth_header(token_a)
    ).json()
    identity = redeem_link_code(db_session, code_response["code"], "whatsapp", "233247000003")
    db_session.commit()

    response = client.patch(
        f"/api/v1/businesses/{business_b['id']}/channels/{identity.id}",
        json={"notificationFrequency": "immediate"},
        headers=auth_header(token_b),
    )
    assert response.status_code == 404
