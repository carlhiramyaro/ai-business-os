"""v0.6 slice 1 (roadmap.md "WhatsApp channel") -- the channel abstraction
sitting between a provider-specific transport (app/whatsapp.py, and
whichever channel is added after it) and the channel-agnostic chat engine
(app/chat_generation.py). Four responsibilities:

1. Resolving a verified external identity to a (user, business) pair --
   the ONLY source of tenant scoping for inbound channel messages. See
   app/models/channel.py's ChannelIdentity docstring.
2. Redeeming a web-generated link code to create/replace that mapping.
3. Giving each identity one rolling Conversation, so the existing
   send_message history logic (app/routers/chat.py) applies unchanged.
4. Rendering a channel-agnostic answer into that channel's wire format --
   kept separate from the system prompt (app/chat_generation.py) so the
   brain stays one brain and rendering stays deterministic/testable.

Functions here don't commit (same convention as app/business_facts.py) --
callers commit once alongside whatever else is in their transaction.
"""

import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import ChannelIdentity, ChannelLinkCode, Conversation

# Excludes visually ambiguous characters (0/O, 1/I/L) -- this code gets
# read off a screen and typed/copy-pasted into a phone keyboard.
_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "01IOL")
CODE_LENGTH = 6
LINK_CODE_TTL_MINUTES = 10

# A link code is short-lived by design (see the docstring above); a chat
# thread over WhatsApp is not -- this bounds how much history rides along
# on every agent call so a months-old conversation doesn't balloon context
# size or cost per message.
MAX_HISTORY_MESSAGES = 20

# WhatsApp Cloud API's hard limit on a single text message body.
_MAX_MESSAGE_LENGTH = 4096


def generate_link_code(db: Session, user_id: uuid.UUID, business_id: uuid.UUID) -> ChannelLinkCode:
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))
    link_code = ChannelLinkCode(
        user_id=user_id,
        business_id=business_id,
        code=code,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=LINK_CODE_TTL_MINUTES),
    )
    db.add(link_code)
    db.flush()
    return link_code


def resolve_identity(db: Session, channel: str, external_id: str) -> ChannelIdentity | None:
    return (
        db.query(ChannelIdentity)
        .filter(ChannelIdentity.channel == channel, ChannelIdentity.external_id == external_id)
        .one_or_none()
    )


def redeem_link_code(
    db: Session, code: str, channel: str, external_id: str, display_name: str | None = None
) -> ChannelIdentity | None:
    """Validates an unconsumed, unexpired code and links `external_id` to
    that code's (user, business). Re-linking an already-linked external_id
    REPLACES the existing identity's mapping rather than creating a second
    row -- a single inbound message must resolve unambiguously to one
    business (see ChannelIdentity's docstring), and letting the most
    recent link win is simpler and more predictable than rejecting the
    re-link outright.

    Returns None (no exception) for any invalid code -- an inbound message
    on an unrecognized/typo'd code is an ordinary, expected user error
    (app/tasks.py replies with linking instructions), not a server error.
    """
    normalized = code.strip().upper()
    link_code = (
        db.query(ChannelLinkCode)
        .filter(
            ChannelLinkCode.code == normalized,
            ChannelLinkCode.consumed_at.is_(None),
            ChannelLinkCode.expires_at > datetime.now(timezone.utc),
        )
        .one_or_none()
    )
    if link_code is None:
        return None

    link_code.consumed_at = datetime.now(timezone.utc)

    identity = resolve_identity(db, channel, external_id)
    if identity is None:
        identity = ChannelIdentity(
            user_id=link_code.user_id,
            business_id=link_code.business_id,
            channel=channel,
            external_id=external_id,
            display_name=display_name,
        )
        db.add(identity)
    else:
        identity.user_id = link_code.user_id
        identity.business_id = link_code.business_id
        identity.display_name = display_name
        identity.verified_at = datetime.now(timezone.utc)

    db.flush()
    return identity


def get_or_create_channel_conversation(db: Session, identity: ChannelIdentity) -> Conversation:
    """One rolling conversation per identity -- WhatsApp has no concept of
    "starting a new session" the way opening the web chat page does
    (app/routers/chat.py's POST .../chat/ creates a fresh Conversation per
    click), so a single ongoing thread is the natural mapping."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.channel == identity.channel, Conversation.channel_identity_id == identity.id)
        .order_by(Conversation.created_at.desc())
        .first()
    )
    if conversation is None:
        conversation = Conversation(
            business_id=identity.business_id,
            channel=identity.channel,
            channel_identity_id=identity.id,
        )
        db.add(conversation)
        db.flush()
    return conversation


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_HEADER_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+", re.MULTILINE)
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _to_whatsapp_markdown(text: str) -> str:
    """Deterministic, fixed input -> fixed output -- no LLM involvement, so
    this is independently unit-testable (CLAUDE.md's deterministic/LLM
    separation rule). WhatsApp's own formatting is a small subset of
    markdown: *bold* (single asterisk, not double), _italic_ (unchanged),
    no headers, no native bullet/table rendering."""
    text = _HEADER_RE.sub(r"*\1*", text)
    text = _BOLD_RE.sub(r"*\1*", text)
    text = _BULLET_RE.sub(r"\1• ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _split_message(text: str, limit: int = _MAX_MESSAGE_LENGTH) -> list[str]:
    """Splits on paragraph, then line, boundaries where possible -- only
    hard-cuts mid-line as a last resort for a single line longer than the
    limit (very unlikely for LLM prose, but must not silently drop text)."""
    if len(text) <= limit:
        return [text] if text else []

    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            parts.append(current)
            current = ""

        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current = line

    if current:
        parts.append(current)
    return parts


def format_for_channel(text: str, channel: str) -> list[str]:
    """Converts a channel-agnostic answer (as produced by
    app/chat_generation.py, always markdown) into one or more messages
    ready to send on `channel`. Unknown/"web" channels pass through
    unchanged and unsplit -- this function only exists for channels with
    their own formatting/length constraints."""
    if channel != "whatsapp":
        return [text]
    return _split_message(_to_whatsapp_markdown(text))
