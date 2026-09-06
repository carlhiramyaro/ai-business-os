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


def looks_like_link_code(text: str) -> bool:
    """Is this inbound message an ATTEMPT at a link code, as opposed to an
    ordinary message from a number that hasn't linked yet? Decides which
    pre-linking reply app/tasks.py sends -- "how to link" vs "that code is
    invalid" -- so it must not classify a plain greeting as a code.

    Matches the exact format generate_link_code produces (CODE_LENGTH
    characters, all from _CODE_ALPHABET) rather than a looser "short and
    spaceless" heuristic: "Hello" is 5 spaceless characters and WOULD pass
    such a check, so the very first thing a new owner texts got answered
    with "that code isn't valid or has expired" instead of instructions.
    See docs/decisions.md [2026-08-27].

    Case-insensitive, and tolerant of surrounding whitespace, to match
    redeem_link_code's own `.strip().upper()` normalization -- a phone
    keyboard autocapitalizes inconsistently and nobody shift-types a code.
    """
    candidate = text.strip().upper()
    return len(candidate) == CODE_LENGTH and all(c in _CODE_ALPHABET for c in candidate)

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


# Tools whose narration is the imitation hazard: an assistant turn saying
# "I've staged the sale entry..." is, on the next turn, an example of how to
# answer a data-entry message -- with no evidence in the replayed text that
# a tool was ever involved.
_DATA_ENTRY_TOOL_PREFIXES = ("propose_", "confirm_", "cancel_")


def build_history(messages) -> list[dict]:
    """Replays a conversation for the model, replacing data-entry narration
    with a factual marker of what actually happened.

    Measured against a real 20-message WhatsApp conversation, the model
    called propose_*_entry for a new expense 11/12 times with no history and
    12/12 with the last 4 messages -- but only 3/12 with the full history.
    The failure scales with accumulated precedent, so it is WORST for
    established daily users and invisible for new ones: the product degrades
    the more an owner uses it.

    `messages.tool_calls` is persisted (v0.2 slice 2) but was being dropped
    here, so the model saw only prose. Replacing that prose with
    "[Called propose_sale_entry...]" keeps full semantic continuity -- the
    model still knows an entry was staged and confirmed -- while removing
    the sentence it was copying instead of acting. Cheap stand-in for
    replaying real tool-call turns, which OpenAI's format makes awkward
    (each assistant tool-call turn needs a matching tool-result message, and
    the audit trail stores arguments without results). See
    docs/decisions.md [2026-08-27].

    Only data-entry turns are rewritten; ordinary analytical answers are
    replayed verbatim, since nothing about them invites imitation.
    """
    history = []
    for message in messages:
        content = message.content
        if message.role == "assistant":
            tools = [
                call.get("tool", "")
                for call in (message.tool_calls or [])
                if call.get("tool", "").startswith(_DATA_ENTRY_TOOL_PREFIXES)
            ]
            if tools:
                content = f"[Called {', '.join(tools)}. The result was relayed to the owner.]"
        history.append({"role": message.role, "content": content})
    return history


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
