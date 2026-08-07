"""Deterministic, no-network, no-LLM tests for app/whatsapp.py's pure
functions (signature verification, inbound payload parsing) and
app/channels.py's format_for_channel -- CLAUDE.md's deterministic-vs-LLM
separation rule: these have fixed input -> expected output and zero
dependency on an LLM or a real Meta API call."""

import hashlib
import hmac
import json

import app.whatsapp as whatsapp
from app.channels import format_for_channel
from app.whatsapp import parse_inbound, send_template, send_text, verify_signature

APP_SECRET = "test-app-secret"


def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_signature_accepts_valid_signature(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    body = b'{"hello": "world"}'
    assert verify_signature(body, _sign(body)) is True


def test_verify_signature_rejects_tampered_body(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    body = b'{"hello": "world"}'
    signature = _sign(body)
    tampered = b'{"hello": "mallory"}'
    assert verify_signature(tampered, signature) is False


def test_verify_signature_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    body = b'{"hello": "world"}'
    assert verify_signature(body, _sign(body, secret="wrong-secret")) is False


def test_verify_signature_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    assert verify_signature(b"{}", None) is False


def test_verify_signature_rejects_when_unconfigured(monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    body = b'{"hello": "world"}'
    assert verify_signature(body, _sign(body)) is False


# A real (trimmed) shape captured from Meta's docs -- entry[] > changes[] >
# value.{messages,contacts}[].
_INBOUND_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WABA_ID",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "15550001111", "phone_number_id": "PHONE_ID"},
                        "contacts": [{"profile": {"name": "Ama Mensah"}, "wa_id": "233241234567"}],
                        "messages": [
                            {
                                "from": "233241234567",
                                "id": "wamid.ABC123",
                                "timestamp": "1691234567",
                                "text": {"body": "how did I do this week?"},
                                "type": "text",
                            }
                        ],
                    },
                    "field": "messages",
                }
            ],
        }
    ],
}


def test_parse_inbound_extracts_text_message():
    parsed = parse_inbound(json.loads(json.dumps(_INBOUND_PAYLOAD)))
    assert len(parsed.messages) == 1
    message = parsed.messages[0]
    assert message.message_id == "wamid.ABC123"
    assert message.from_wa_id == "233241234567"
    assert message.text == "how did I do this week?"
    assert message.contact_name == "Ama Mensah"


def test_parse_inbound_status_only_payload_has_no_messages():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [{"id": "wamid.ABC123", "status": "delivered"}],
                        }
                    }
                ]
            }
        ]
    }
    assert parse_inbound(payload).messages == []


def test_parse_inbound_extracts_status_update():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": "wamid.SENT1", "status": "delivered", "recipient_id": "233241234567"}
                            ],
                        }
                    }
                ]
            }
        ]
    }
    [status] = parse_inbound(payload).statuses
    assert status.message_id == "wamid.SENT1"
    assert status.status == "delivered"
    assert status.recipient_id == "233241234567"
    assert status.error is None


def test_parse_inbound_extracts_status_error_on_failure():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.FAILED1",
                                    "status": "failed",
                                    "errors": [{"code": 131026, "title": "Message undeliverable"}],
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    [status] = parse_inbound(payload).statuses
    assert status.status == "failed"
    assert status.error == "Message undeliverable"


def test_parse_inbound_ignores_non_text_messages():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [{"from": "233241234567", "id": "wamid.XYZ", "type": "image"}],
                        }
                    }
                ]
            }
        ]
    }
    assert parse_inbound(payload).messages == []


def test_parse_inbound_handles_empty_payload():
    assert parse_inbound({}).messages == []


def test_format_for_channel_converts_markdown_to_whatsapp_syntax():
    text = "## Summary\n\n**Revenue** is up.\n\n- item one\n- item two"
    [formatted] = format_for_channel(text, "whatsapp")
    assert "**" not in formatted
    assert "##" not in formatted
    assert "*Summary*" in formatted
    assert "*Revenue*" in formatted
    assert "• item one" in formatted
    assert "• item two" in formatted


def test_format_for_channel_passes_through_non_whatsapp_channels():
    text = "## Summary\n\n**Revenue** is up."
    assert format_for_channel(text, "web") == [text]


def test_format_for_channel_splits_long_messages():
    long_text = "\n".join(f"line {i}" for i in range(1000))
    parts = format_for_channel(long_text, "whatsapp")
    assert len(parts) > 1
    assert all(len(part) <= 4096 for part in parts)
    # No content lost or duplicated across the split.
    joined = "\n".join(parts)
    assert joined.count("line 0\n") == 1
    assert joined.count("line 999") == 1


# --- send_text / send_template: wire format, v0.6 slice 2 -------------------


class _FakeResponse:
    def __init__(self, message_id: str):
        self._message_id = message_id

    def raise_for_status(self):
        pass

    def json(self):
        return {"messages": [{"id": self._message_id}]}


def _configure_whatsapp(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "PHONE123")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-abc")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)


def test_send_text_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    assert send_text("233241234567", "hi") is None


def test_send_text_posts_expected_payload_and_returns_message_id(monkeypatch):
    _configure_whatsapp(monkeypatch)
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json)
        return _FakeResponse("wamid.SENT1")

    monkeypatch.setattr(whatsapp.httpx, "post", fake_post)

    result = send_text("233241234567", "hello there")

    assert result == "wamid.SENT1"
    assert captured["json"] == {
        "messaging_product": "whatsapp",
        "to": "233241234567",
        "type": "text",
        "text": {"body": "hello there"},
    }
    assert "PHONE123" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer token-abc"


def test_send_template_posts_expected_payload(monkeypatch):
    _configure_whatsapp(monkeypatch)
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(json=json)
        return _FakeResponse("wamid.TEMPLATE1")

    monkeypatch.setattr(whatsapp.httpx, "post", fake_post)

    result = send_template("233241234567", "insight_notification", "en_US", ["3"])

    assert result == "wamid.TEMPLATE1"
    assert captured["json"]["type"] == "template"
    assert captured["json"]["template"]["name"] == "insight_notification"
    assert captured["json"]["template"]["language"] == {"code": "en_US"}
    assert captured["json"]["template"]["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "3"}]}
    ]
