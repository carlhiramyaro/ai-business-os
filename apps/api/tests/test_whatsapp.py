"""Deterministic, no-network, no-LLM tests for app/whatsapp.py's pure
functions (signature verification, inbound payload parsing) and
app/channels.py's format_for_channel -- CLAUDE.md's deterministic-vs-LLM
separation rule: these have fixed input -> expected output and zero
dependency on an LLM or a real Meta API call."""

import hashlib
import hmac
import json

from app.channels import format_for_channel
from app.whatsapp import parse_inbound, verify_signature

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


def test_parse_inbound_ignores_status_callbacks():
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
