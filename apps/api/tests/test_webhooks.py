"""POST /api/v1/webhooks/whatsapp enqueues a REAL Celery task
(handle_whatsapp_message_task), so -- same reasoning as tests/test_uploads.py
-- this module can't use the SAVEPOINT-rollback client/db_session fixtures:
the task opens its own DB connection via app.tasks.SessionLocal, which
can never see another connection's uncommitted rows. Commits for real
against ai_business_os_test and cleans up explicitly. See
docs/decisions.md [2026-07-17] and agent-instructions.md's Testing section.
"""

import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient

import app.chat_generation as chat_generation
import app.outbound as outbound
import app.tasks as tasks
from app.chat_generation import ChatAnswer
from app.database import get_db
from app.models import (
    Business,
    ChannelIdentity,
    Conversation,
    Message,
    OutboundMessage,
    PendingEntry,
    Sale,
    UploadSession,
    User,
    WebhookEvent,
)
from app.security import create_access_token, hash_password
from main import app
from tests.conftest import TestSessionLocal

APP_SECRET = "webhook-test-secret"
VERIFY_TOKEN = "webhook-test-verify-token"


def _sign(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def fake_generate_chat_answer(db, business, question, history):
    return ChatAnswer(answer=f"**Revenue** is up.\nBased on {len(history)} prior messages.", tool_calls=[])


SENT_MESSAGES: list[tuple[str, str]] = []
_next_provider_id = iter(f"wamid.FAKE{i}" for i in range(100000))


def fake_send_text(to, body):
    SENT_MESSAGES.append((to, body))
    return next(_next_provider_id)


@pytest.fixture(autouse=True)
def _patch_env_and_tasks(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN)
    monkeypatch.setattr(tasks, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(tasks, "generate_chat_answer", fake_generate_chat_answer)
    # send_text is called from two places since v0.6 slice 2: directly by
    # app/tasks.py's _handle_unlinked_message (pre-linking replies, no
    # OutboundMessage row) and, via app/outbound.py's
    # deliver_outbound_message, for everything that DOES go through the
    # queue (chat replies post-linking, proactive insight pushes) -- both
    # need patching, since they're two different modules' bound names for
    # the same underlying function.
    monkeypatch.setattr(tasks, "send_text", fake_send_text)
    monkeypatch.setattr(outbound, "send_text", fake_send_text)
    SENT_MESSAGES.clear()
    yield
    with TestSessionLocal() as db:
        db.query(OutboundMessage).delete()
        db.query(Message).delete()
        db.query(Conversation).delete()
        db.query(ChannelIdentity).delete()
        db.query(WebhookEvent).delete()
        # v0.6 slice 3: FK'd to Business, so must clear before it.
        db.query(PendingEntry).delete()
        db.query(Sale).delete()
        db.query(UploadSession).delete()
        db.query(Business).delete()
        db.query(User).delete()
        db.commit()


@pytest.fixture()
def real_client():
    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def linked_identity():
    with TestSessionLocal() as db:
        user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
        db.add(user)
        db.flush()
        business = Business(owner_id=user.id, business_name="Webhook Co")
        db.add(business)
        db.flush()
        identity = ChannelIdentity(
            user_id=user.id, business_id=business.id, channel="whatsapp", external_id="233241234567"
        )
        db.add(identity)
        db.commit()
        return str(business.id), identity.external_id


def _text_message_payload(message_id: str, from_wa_id: str, text: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": from_wa_id, "id": message_id, "type": "text", "text": {"body": text}}
                            ]
                        }
                    }
                ]
            }
        ]
    }


def _status_payload(message_id: str, status_value: str, errors: list[dict] | None = None) -> dict:
    status = {"id": message_id, "status": status_value, "recipient_id": "233241234567"}
    if errors:
        status["errors"] = errors
    return {"entry": [{"changes": [{"value": {"statuses": [status]}}]}]}


def test_get_webhook_handshake_succeeds_with_correct_token(real_client):
    response = real_client.get(
        "/api/v1/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "12345"},
    )
    assert response.status_code == 200
    assert response.text == "12345"


def test_get_webhook_handshake_rejects_wrong_token(real_client):
    response = real_client.get(
        "/api/v1/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
    )
    assert response.status_code == 403


def test_post_webhook_rejects_bad_signature(real_client):
    payload = _text_message_payload("wamid.1", "233241234567", "hello")
    body = json.dumps(payload).encode()

    response = real_client.post(
        "/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef"}
    )
    assert response.status_code == 401

    with TestSessionLocal() as db:
        assert db.query(WebhookEvent).count() == 0


def test_post_webhook_from_unlinked_number_sends_instructions(real_client):
    payload = _text_message_payload("wamid.unlinked", "233240000000", "hi")
    body = json.dumps(payload).encode()

    response = real_client.post(
        "/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)}
    )
    assert response.status_code == 200

    assert len(SENT_MESSAGES) == 1
    to, message = SENT_MESSAGES[0]
    assert to == "233240000000"
    assert "Settings" in message

    with TestSessionLocal() as db:
        assert db.query(WebhookEvent).filter(WebhookEvent.external_id == "wamid.unlinked").count() == 1


def test_post_webhook_from_linked_number_answers_via_chat_agent(real_client, linked_identity):
    business_id, external_id = linked_identity
    payload = _text_message_payload("wamid.linked", external_id, "how did I do this week?")
    body = json.dumps(payload).encode()

    response = real_client.post(
        "/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)}
    )
    assert response.status_code == 200

    assert len(SENT_MESSAGES) == 1
    to, message = SENT_MESSAGES[0]
    assert to == external_id
    assert "*Revenue*" in message  # ** -> * conversion
    assert "**" not in message

    with TestSessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business_id)).one()
        assert conversation.channel == "whatsapp"
        messages = db.query(Message).filter(Message.conversation_id == conversation.id).order_by(Message.created_at).all()
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content == "how did I do this week?"


def test_duplicate_message_id_is_not_reprocessed(real_client, linked_identity):
    _, external_id = linked_identity
    payload = _text_message_payload("wamid.dup", external_id, "what were my top products?")
    body = json.dumps(payload).encode()
    headers = {"X-Hub-Signature-256": _sign(body)}

    first = real_client.post("/api/v1/webhooks/whatsapp", content=body, headers=headers)
    assert first.status_code == 200
    second = real_client.post("/api/v1/webhooks/whatsapp", content=body, headers=headers)
    assert second.status_code == 200

    with TestSessionLocal() as db:
        assert db.query(WebhookEvent).filter(WebhookEvent.external_id == "wamid.dup").count() == 1
        assert db.query(Message).filter(Message.role == "user").count() == 1

    assert len(SENT_MESSAGES) == 1


def test_chat_reply_creates_a_sent_outbound_message(real_client, linked_identity):
    """v0.6 slice 2: chat replies now go through the same OutboundMessage
    queue proactive sends use, not a bare send_text call -- see
    docs/decisions.md."""
    _, external_id = linked_identity
    payload = _text_message_payload("wamid.audit", external_id, "how did I do today?")
    body = json.dumps(payload).encode()

    response = real_client.post("/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert response.status_code == 200

    with TestSessionLocal() as db:
        [message] = db.query(OutboundMessage).all()
        assert message.kind == "chat_reply"
        assert message.status == "sent"
        assert message.send_method == "session"
        assert message.provider_message_id is not None


# --- v0.6 slice 2: delivery-status callbacks --------------------------------


def _queue_and_send_message(business_id: str, identity_external_id: str, provider_message_id: str) -> str:
    """Simulates a message this app already sent (bypassing the real send
    path -- these tests are about the STATUS CALLBACK, not delivery
    itself, already covered by tests/test_outbound.py)."""
    with TestSessionLocal() as db:
        identity = db.query(ChannelIdentity).filter(ChannelIdentity.external_id == identity_external_id).one()
        message = OutboundMessage(
            business_id=uuid.UUID(business_id),
            channel_identity_id=identity.id,
            channel="whatsapp",
            kind="chat_reply",
            body="hello",
            send_method="session",
            provider_message_id=provider_message_id,
            status="sent",
        )
        db.add(message)
        db.commit()
        return str(message.id)


def test_status_callback_updates_outbound_message(real_client, linked_identity):
    business_id, external_id = linked_identity
    message_id = _queue_and_send_message(business_id, external_id, "wamid.STATUSTEST1")

    payload = _status_payload("wamid.STATUSTEST1", "delivered")
    body = json.dumps(payload).encode()
    response = real_client.post("/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert response.status_code == 200

    with TestSessionLocal() as db:
        message = db.get(OutboundMessage, uuid.UUID(message_id))
        assert message.status == "delivered"
        assert message.delivered_at is not None


def test_status_callback_for_unknown_message_is_ignored(real_client):
    payload = _status_payload("wamid.NEVERSENTBYTHISAPP", "delivered")
    body = json.dumps(payload).encode()
    response = real_client.post("/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert response.status_code == 200  # no error, just nothing to update


def test_status_callback_respects_monotonic_ordering(real_client, linked_identity):
    business_id, external_id = linked_identity
    message_id = _queue_and_send_message(business_id, external_id, "wamid.STATUSTEST2")

    read_payload = json.dumps(_status_payload("wamid.STATUSTEST2", "read")).encode()
    real_client.post("/api/v1/webhooks/whatsapp", content=read_payload, headers={"X-Hub-Signature-256": _sign(read_payload)})

    # An out-of-order "delivered" arriving after "read" must not regress it.
    delivered_payload = json.dumps(_status_payload("wamid.STATUSTEST2", "delivered")).encode()
    real_client.post(
        "/api/v1/webhooks/whatsapp", content=delivered_payload, headers={"X-Hub-Signature-256": _sign(delivered_payload)}
    )

    with TestSessionLocal() as db:
        message = db.get(OutboundMessage, uuid.UUID(message_id))
        assert message.status == "read"


def test_status_callback_records_failure_reason(real_client, linked_identity):
    business_id, external_id = linked_identity
    message_id = _queue_and_send_message(business_id, external_id, "wamid.STATUSTEST3")

    payload = _status_payload(
        "wamid.STATUSTEST3", "failed", errors=[{"code": 131026, "title": "Message undeliverable"}]
    )
    body = json.dumps(payload).encode()
    real_client.post("/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)})

    with TestSessionLocal() as db:
        message = db.get(OutboundMessage, uuid.UUID(message_id))
        assert message.status == "failed"
        assert message.error == "Message undeliverable"
        assert message.failed_at is not None


# --- v0.6 slice 3: data entry by message, end-to-end through the real webhook/task pipeline ---


def _tool_call(name, arguments):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=f"call_{uuid.uuid4().hex[:8]}", function=SimpleNamespace(name=name, arguments=json.dumps(arguments))
    )


def _model_turn(content=None, tool_calls=None):
    from types import SimpleNamespace

    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


class _FakeCompletions:
    def __init__(self, scripted_turns):
        self.scripted_turns = list(scripted_turns)

    def create(self, **kwargs):
        if len(self.scripted_turns) > 1:
            return self.scripted_turns.pop(0)
        return self.scripted_turns[0]


def _fake_openai(monkeypatch, scripted_turns):
    from types import SimpleNamespace

    monkeypatch.setattr(
        chat_generation,
        "OpenAI",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(scripted_turns))),
    )


def test_data_entry_propose_then_confirm_across_two_whatsapp_messages(monkeypatch, real_client, linked_identity):
    """The real generate_chat_answer (only the OpenAI client faked) end to
    end through the actual webhook -> Celery task -> chat agent -> data
    entry pipeline -- two separate inbound WhatsApp messages, exactly as
    they'd arrive as two separate webhook deliveries."""
    business_id, external_id = linked_identity
    monkeypatch.setattr(tasks, "generate_chat_answer", chat_generation.generate_chat_answer)

    _fake_openai(
        monkeypatch,
        [
            _model_turn(
                tool_calls=[_tool_call("propose_sale_entry", {"product_name": "Rice", "quantity": 3, "unit_price": 50})]
            ),
            _model_turn(content="I'll record 3 x Rice @ 50 = 150 total. Reply YES to confirm."),
        ],
    )
    payload = _text_message_payload("wamid.propose1", external_id, "sold 3 bags of rice at 50 each")
    body = json.dumps(payload).encode()
    response = real_client.post("/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert response.status_code == 200

    with TestSessionLocal() as db:
        assert db.query(Sale).count() == 0
        entry = db.query(PendingEntry).one()
        assert entry.status == "pending"

    _fake_openai(
        monkeypatch,
        [
            _model_turn(tool_calls=[_tool_call("confirm_pending_entry", {})]),
            _model_turn(content="Recorded! 3 x Rice for 150."),
        ],
    )
    payload = _text_message_payload("wamid.confirm1", external_id, "yes")
    body = json.dumps(payload).encode()
    response = real_client.post("/api/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert response.status_code == 200

    with TestSessionLocal() as db:
        sale = db.query(Sale).one()
        assert sale.product_name == "Rice"
        assert sale.quantity == 3
        entry = db.query(PendingEntry).one()
        assert entry.status == "confirmed"

    assert len(SENT_MESSAGES) == 2
    assert "150" in SENT_MESSAGES[0][1]
    assert "Recorded" in SENT_MESSAGES[1][1]

