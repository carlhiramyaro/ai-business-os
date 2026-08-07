"""v0.6 slice 2: app/outbound.py's queue/deliver/status-application logic.
within_session_window is pure (no DB/network); queue_message and
apply_status_update need real rows but no network; deliver_outbound_message
is exercised with app.whatsapp.send_text/send_template monkeypatched, per
CLAUDE.md's "only the LLM call gets mocked" rule extended to the one other
paid external API this codebase now calls."""

import uuid
from datetime import datetime, timedelta, timezone

import app.outbound as outbound
from app.models import Business, ChannelIdentity, OutboundMessage, User
from app.outbound import apply_status_update, deliver_outbound_message, queue_message, within_session_window
from app.security import hash_password

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _create_user_business_identity(db, notification_frequency="off"):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    business = Business(owner_id=user.id, business_name="Outbound Co")
    db.add(business)
    db.flush()
    identity = ChannelIdentity(
        user_id=user.id,
        business_id=business.id,
        channel="whatsapp",
        external_id="233241234567",
        notification_frequency=notification_frequency,
    )
    db.add(identity)
    db.flush()
    return business, identity


# --- within_session_window: pure, fixed input -> expected output ---------


def test_within_session_window_true_when_recent():
    last_inbound = NOW - timedelta(hours=1)
    assert within_session_window(last_inbound, now=NOW) is True


def test_within_session_window_false_when_expired():
    last_inbound = NOW - timedelta(hours=25)
    assert within_session_window(last_inbound, now=NOW) is False


def test_within_session_window_false_at_never_messaged():
    assert within_session_window(None, now=NOW) is False


def test_within_session_window_true_at_exactly_24h_boundary():
    last_inbound = NOW - timedelta(hours=24)
    assert within_session_window(last_inbound, now=NOW) is True


# --- queue_message ---------------------------------------------------------


def test_queue_message_creates_queued_row(db_session):
    business, identity = _create_user_business_identity(db_session)
    message = queue_message(db_session, business.id, identity, "hello", kind="chat_reply")

    assert message.status == "queued"
    assert message.channel == "whatsapp"
    assert message.business_id == business.id
    assert message.channel_identity_id == identity.id
    assert message.body == "hello"
    assert message.related_insight_ids is None


def test_queue_message_stores_related_insight_ids(db_session):
    business, identity = _create_user_business_identity(db_session)
    insight_ids = [uuid.uuid4(), uuid.uuid4()]
    message = queue_message(
        db_session, business.id, identity, "digest", kind="insight_digest", related_insight_ids=insight_ids
    )
    assert message.related_insight_ids == [str(i) for i in insight_ids]


# --- deliver_outbound_message: session vs. template decision ---------------


def test_deliver_sends_session_message_within_window(monkeypatch, db_session):
    # deliver_outbound_message always resolves the window against real
    # wall-clock time (it takes no injectable `now`, unlike
    # within_session_window itself) -- so this uses a real recent
    # timestamp, not the fixed NOW used by the pure-function tests above.
    business, identity = _create_user_business_identity(db_session)
    identity.last_inbound_at = datetime.now(timezone.utc) - timedelta(hours=1)
    message = queue_message(db_session, business.id, identity, "hi there", kind="chat_reply")

    sent = {}

    def fake_send_text(to, body):
        sent["to"], sent["body"] = to, body
        return "wamid.SENT123"

    monkeypatch.setattr(outbound, "send_text", fake_send_text)

    deliver_outbound_message(db_session, message, identity)

    assert message.send_method == "session"
    assert message.status == "sent"
    assert message.provider_message_id == "wamid.SENT123"
    assert sent == {"to": "233241234567", "body": "hi there"}


def test_deliver_sends_template_outside_window(monkeypatch, db_session):
    business, identity = _create_user_business_identity(db_session)
    identity.last_inbound_at = datetime.now(timezone.utc) - timedelta(hours=30)
    message = queue_message(
        db_session,
        business.id,
        identity,
        "the real insight text",
        kind="insight_digest",
        related_insight_ids=[uuid.uuid4(), uuid.uuid4(), uuid.uuid4()],
    )

    captured = {}

    def fake_send_template(to, template_name, language, body_params):
        captured.update(to=to, template_name=template_name, language=language, body_params=body_params)
        return "wamid.TEMPLATE123"

    monkeypatch.setattr(outbound, "send_template", fake_send_template)

    deliver_outbound_message(db_session, message, identity)

    assert message.send_method == "template"
    assert message.status == "sent"
    assert message.provider_message_id == "wamid.TEMPLATE123"
    # The template carries a count, never the actual insight body.
    assert captured["body_params"] == ["3"]
    assert "the real insight text" not in captured["body_params"]
    # message.body still holds the real content, for the audit trail.
    assert message.body == "the real insight text"


def test_deliver_marks_skipped_when_unconfigured(monkeypatch, db_session):
    business, identity = _create_user_business_identity(db_session)
    identity.last_inbound_at = datetime.now(timezone.utc)
    message = queue_message(db_session, business.id, identity, "hi", kind="chat_reply")

    monkeypatch.setattr(outbound, "send_text", lambda to, body: None)

    deliver_outbound_message(db_session, message, identity)

    assert message.status == "skipped"
    assert message.provider_message_id is None
    assert message.error


def test_deliver_rejects_unsupported_channel(db_session):
    business, identity = _create_user_business_identity(db_session)
    message = queue_message(db_session, business.id, identity, "hi", kind="chat_reply")
    message.channel = "sms"
    try:
        deliver_outbound_message(db_session, message, identity)
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- apply_status_update: monotonic ordering --------------------------------


def _outbound_message(status="sent"):
    return OutboundMessage(
        business_id=uuid.uuid4(),
        channel_identity_id=uuid.uuid4(),
        channel="whatsapp",
        kind="chat_reply",
        body="x",
        send_method="session",
        provider_message_id="wamid.X",
        status=status,
    )


def test_apply_status_update_advances_forward():
    message = _outbound_message(status="sent")
    assert apply_status_update(message, "delivered") is True
    assert message.status == "delivered"
    assert message.delivered_at is not None


def test_apply_status_update_ignores_out_of_order_regression():
    message = _outbound_message(status="read")
    assert apply_status_update(message, "delivered") is False
    assert message.status == "read"


def test_apply_status_update_ignores_duplicate():
    message = _outbound_message(status="delivered")
    assert apply_status_update(message, "delivered") is False


def test_apply_status_update_failed_is_always_applied():
    message = _outbound_message(status="sent")
    assert apply_status_update(message, "failed", error="Recipient number not on WhatsApp") is True
    assert message.status == "failed"
    assert message.error == "Recipient number not on WhatsApp"
    assert message.failed_at is not None


def test_apply_status_update_failed_is_terminal():
    message = _outbound_message(status="failed")
    assert apply_status_update(message, "delivered") is False
    assert message.status == "failed"


def test_apply_status_update_ignores_unknown_status():
    message = _outbound_message(status="sent")
    assert apply_status_update(message, "some_new_status_meta_invents_later") is False
    assert message.status == "sent"
