"""v0.6 slice 1 (roadmap.md "WhatsApp channel") -- a thin, dependency-free
client for Meta's WhatsApp Cloud API (graph.facebook.com), plus the two pure
functions that turn its wire format into something the rest of the app can
use without knowing about Meta's JSON shape at all.

No SDK: the Cloud API is a handful of REST calls, and Meta's official SDKs
are thin wrappers over exactly that -- pulling one in would be a dependency
for a dependency. Uses `httpx` (already a pinned dependency via FastAPI's
own test client) rather than adding `requests`.

A true no-op when unconfigured (mirrors app/observability.py's Sentry/
Langfuse pattern) -- CI and local dev must not need real Meta credentials
to import this module or run the test suite.
"""

import hashlib
import hmac
import os
from dataclasses import dataclass, field

import httpx
import structlog

logger = structlog.get_logger(__name__)

GRAPH_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")
# WhatsApp Cloud API's hard limit on a single text message body.
MAX_MESSAGE_LENGTH = 4096

# infra/ssm.tf seeds every WHATSAPP_* secret parameter with this exact
# placeholder until it's replaced by hand -- same pattern and same reason
# as app/observability.py's _UNCONFIGURED_PLACEHOLDER: a plain truthiness
# check would treat this non-empty placeholder as "configured" and start
# making real (failing) calls to graph.facebook.com with it as a token.
_UNCONFIGURED_PLACEHOLDER = "REPLACE_ME_MANUALLY"


def _configured_value(env_var: str) -> str | None:
    value = os.getenv(env_var)
    if not value or value == _UNCONFIGURED_PLACEHOLDER:
        return None
    return value


def display_number() -> str | None:
    """The human-readable number owners are told to text (Settings page) --
    cosmetic display text, never used for an actual API call (the phone
    number ID is what addresses the Cloud API). None until a real test/
    production number is configured."""
    return _configured_value("WHATSAPP_DISPLAY_NUMBER")


def is_configured() -> bool:
    """False in CI/local dev with no Meta app set up -- callers use this to
    skip real network calls the same way app/observability.py's functions
    no-op without a DSN/key."""
    return bool(
        _configured_value("WHATSAPP_PHONE_NUMBER_ID")
        and _configured_value("WHATSAPP_ACCESS_TOKEN")
        and _configured_value("WHATSAPP_APP_SECRET")
    )


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Validates Meta's `X-Hub-Signature-256` header: HMAC-SHA256 of the
    *raw* request body, keyed by the app secret, hex-encoded and prefixed
    "sha256=". Must run against the raw bytes -- re-serializing the parsed
    JSON before hashing would produce a different digest than Meta computed
    (key order, whitespace, unicode escaping all matter to HMAC input) even
    when the parsed content is identical. See docs/learning-guide.md.

    `hmac.compare_digest` (not `==`) -- a naive string comparison leaks
    timing information proportional to how many leading bytes match,
    letting an attacker recover the correct signature byte-by-byte.
    """
    app_secret = _configured_value("WHATSAPP_APP_SECRET")
    if not app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


@dataclass
class InboundMessage:
    """One inbound WhatsApp text message, flattened out of Meta's nested
    webhook payload -- everything downstream (app/channels.py,
    app/tasks.py's handle_whatsapp_message_task) works with this, never the
    raw payload."""

    message_id: str
    from_wa_id: str
    text: str
    contact_name: str | None = None
    timestamp: str | None = None


@dataclass
class ParsedWebhook:
    messages: list[InboundMessage] = field(default_factory=list)


def parse_inbound(payload: dict) -> ParsedWebhook:
    """Flattens Meta's `entry[].changes[].value.{messages,contacts}[]`
    shape into a flat list of InboundMessage. Pure function, zero network --
    unit-tested against real captured webhook payload fixtures.

    Deliberately ignores non-text message types (image/audio/location/etc,
    slice 4's concern) and `statuses[]` delivery-receipt callbacks (slice
    2's concern) -- both are valid payloads this function will simply
    return no messages for, not an error."""
    result = ParsedWebhook()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}

            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                text_body = message.get("text", {}).get("body")
                from_wa_id = message.get("from")
                message_id = message.get("id")
                if not (text_body and from_wa_id and message_id):
                    continue
                result.messages.append(
                    InboundMessage(
                        message_id=message_id,
                        from_wa_id=from_wa_id,
                        text=text_body,
                        contact_name=contacts.get(from_wa_id),
                        timestamp=message.get("timestamp"),
                    )
                )

    return result


def send_text(to: str, body: str) -> None:
    """Sends one outbound text message. No-ops (logs and returns) when
    unconfigured -- see module docstring. Raises on a non-2xx from Meta;
    callers (app/tasks.py) run inside a Celery task, so a raised exception
    becomes a normal Celery-visible failure (Sentry capture, retry
    eligibility) rather than something that needs its own handling here.

    Doesn't chunk `body` itself -- app/channels.py's format_for_channel
    already splits at MAX_MESSAGE_LENGTH before this is called, so each
    call here is always one WhatsApp message."""
    if not is_configured():
        logger.info("whatsapp_send_skipped_unconfigured", to=to)
        return

    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"

    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        },
        timeout=10.0,
    )
    response.raise_for_status()
