import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.channels import (
    CODE_LENGTH,
    build_history,
    generate_link_code,
    looks_like_link_code,
    redeem_link_code,
)
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


# v0.6 [2026-08-27]: pure classifier, no DB -- decides which pre-linking
# reply an unlinked number gets. The regression these guard is a real one
# found in live testing: "Hello" (5 spaceless chars) was classified as a
# link-code attempt, so the first message a new owner ever sends was
# answered with "that code isn't valid or has expired". See
# docs/decisions.md [2026-08-27].
@pytest.mark.parametrize(
    "text",
    [
        "Hello",  # the exact message that exposed this
        "hi",
        "hey",
        "start",
        "Menu",
        "how did I do this week?",  # has spaces -- never was misclassified
        "",
        "   ",
        "ABCDE",  # right alphabet, one char too short
        "ABCDEFG",  # right alphabet, one char too long
        "ABC0EF",  # 0 is excluded from the alphabet (reads as O)
        "ABC1EF",  # 1 is excluded (reads as I/L)
        "ABCOEF",  # O is excluded
        "ABCIEF",  # I is excluded
        "ABCLEF",  # L is excluded
        "ABC-EF",  # punctuation is not in the alphabet
        "234567890123",  # 12 digits: passed the old len<=12 heuristic
    ],
)
def test_looks_like_link_code_rejects_non_codes(text):
    assert looks_like_link_code(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "ABC23F",
        "abc23f",  # phone keyboards do not shift-type
        "  ABC23F  ",  # copy-paste picks up whitespace
        "AbC23f",
    ],
)
def test_looks_like_link_code_accepts_real_code_shapes(text):
    assert looks_like_link_code(text) is True


def test_generated_codes_are_always_classified_as_codes(db_session):
    """Ties the classifier to the generator: whatever generate_link_code
    produces must be recognized, so the two can never drift apart."""
    user, business = _create_user_and_business(db_session, "Classifier Co")
    for _ in range(50):
        code = generate_link_code(db_session, user.id, business.id).code
        assert len(code) == CODE_LENGTH
        assert looks_like_link_code(code) is True
        assert looks_like_link_code(code.lower()) is True


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


# --- [2026-08-27] build_history: don't replay data-entry narration ---
#
# Measured against a real 20-message WhatsApp conversation, the model called
# propose_*_entry for a new expense 11/12 times with NO history and 12/12
# with the last 4 messages -- but only 1-3/12 with the full history. The
# failure scales with accumulated precedent, so it is worst for established
# daily users and invisible for new ones. Replacing data-entry narration
# with a factual marker took that same history from 1/12 to 11/12.
# See docs/decisions.md [2026-08-27].


class _Msg:
    """Stand-in for a Message row -- build_history only reads these three."""

    def __init__(self, role, content, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


def test_build_history_rewrites_data_entry_turns():
    history = build_history(
        [
            _Msg("user", "sold 3 bags of rice at 50 each"),
            _Msg(
                "assistant",
                "I've staged the sale entry for your review. Please confirm.",
                [{"tool": "propose_sale_entry", "arguments": {}}],
            ),
            _Msg("user", "Yes"),
            _Msg(
                "assistant",
                "The sale of 3 bags of rice has been successfully recorded.",
                [{"tool": "confirm_pending_entry", "arguments": {}}],
            ),
        ]
    )

    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    # User turns are never rewritten -- they are what the owner actually said.
    assert history[0]["content"] == "sold 3 bags of rice at 50 each"
    assert history[2]["content"] == "Yes"
    # The narration the model was copying is gone...
    assert "staged the sale entry" not in history[1]["content"]
    assert "successfully recorded" not in history[3]["content"]
    # ...but what happened is still legible to the model.
    assert "propose_sale_entry" in history[1]["content"]
    assert "confirm_pending_entry" in history[3]["content"]


def test_build_history_leaves_analytical_answers_verbatim():
    """Only data-entry turns invite imitation; rewriting ordinary answers
    would throw away context the model needs (and multi-turn slot filling
    depends on)."""
    answer = "Your total sales amount to 115.0 GHS across 3 orders."
    history = build_history(
        [
            _Msg("user", "what were my total sales?"),
            _Msg("assistant", answer, [{"tool": "get_financial_summary", "arguments": {}}]),
        ]
    )

    assert history[1]["content"] == answer


def test_build_history_handles_turns_without_tool_calls():
    history = build_history(
        [
            _Msg("assistant", "Could you tell me the quantity and price?", None),
            _Msg("assistant", "No sales recorded today.", []),
        ]
    )

    assert history[0]["content"] == "Could you tell me the quantity and price?"
    assert history[1]["content"] == "No sales recorded today."
