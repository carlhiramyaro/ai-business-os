"""v0.6 slice 2 (roadmap.md "Outbound infrastructure + proactive
delivery") -- the queue/send/status layer sitting on top of
app/whatsapp.py's dumb wire client. One send path for every outbound
message on a channel (chat replies included, not just proactive insight
pushes -- app/tasks.py's handle_whatsapp_message_task was retrofitted onto
this in the same change) so delivery status means something for the whole
channel, not half of it. See docs/decisions.md.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import ChannelIdentity, OutboundMessage
from app.whatsapp import send_template, send_text

# WhatsApp's customer-service window: a free-form ("session") message is
# only deliverable within this many hours of the customer's last inbound
# message. Outside it, only a pre-approved template message can be sent --
# see deliver_outbound_message's docstring for why that means proactive
# content outside the window can only ever be a generic nudge.
SESSION_WINDOW_HOURS = 24

_TEMPLATE_NAME = os.getenv("WHATSAPP_INSIGHT_TEMPLATE_NAME", "insight_notification")
_TEMPLATE_LANGUAGE = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US")

# Ascending delivery order -- apply_status_update uses this to reject an
# out-of-order/duplicate callback that would regress an already-more-
# advanced status. "failed" and "skipped" are handled separately (terminal
# states, not part of the forward progression).
_STATUS_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}


def within_session_window(last_inbound_at: datetime | None, now: datetime | None = None) -> bool:
    """Pure function -- fixed input -> expected output, no network/DB.
    NULL (an identity that has never messaged us -- shouldn't happen in
    practice, since only linking creates an identity and linking itself
    requires an inbound message, but defensive regardless) is always
    outside the window."""
    if last_inbound_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - last_inbound_at <= timedelta(hours=SESSION_WINDOW_HOURS)


def queue_message(
    db: Session,
    business_id: uuid.UUID,
    identity: ChannelIdentity,
    body: str,
    kind: str,
    related_insight_ids: list[uuid.UUID] | None = None,
) -> OutboundMessage:
    """Creates a queued OutboundMessage row. Doesn't decide session vs.
    template here -- that's resolved at send time (deliver_outbound_message)
    against the identity's CURRENT last_inbound_at, since the window can
    close in the time between queueing and an eventual send. Doesn't
    commit -- callers commit once alongside whatever else is in their
    transaction (same convention as app/channels.py)."""
    message = OutboundMessage(
        business_id=business_id,
        channel_identity_id=identity.id,
        channel=identity.channel,
        kind=kind,
        related_insight_ids=[str(i) for i in related_insight_ids] if related_insight_ids else None,
        body=body,
        # Real value set at delivery time (deliver_outbound_message) --
        # "session" here is just a placeholder satisfying the NOT NULL
        # column between queueing and delivery.
        send_method="session",
        status="queued",
    )
    db.add(message)
    db.flush()
    return message


def deliver_outbound_message(db: Session, message: OutboundMessage, identity: ChannelIdentity) -> None:
    """Sends `message` and records the outcome directly onto it (caller
    commits). Only app/tasks.py's send_outbound_message_task calls this --
    kept as a plain function, not the task itself, so it's unit-testable
    without Celery's eager-mode machinery.

    Outside the session window, this sends a TEMPLATE, not `message.body`
    -- a template's text is fixed at Meta's approval time, so it can never
    carry today's actual AI-generated insight content, only a generic
    count-based nudge ("you have N new insights"). `message.body` still
    holds the real content either way, for the audit trail; `send_method`
    records which path was actually used."""
    if message.channel != "whatsapp":
        raise ValueError(f"Unsupported channel: {message.channel}")

    if within_session_window(identity.last_inbound_at):
        message.send_method = "session"
        provider_message_id = send_text(identity.external_id, message.body)
    else:
        message.send_method = "template"
        count = len(message.related_insight_ids) if message.related_insight_ids else 1
        provider_message_id = send_template(
            identity.external_id, _TEMPLATE_NAME, _TEMPLATE_LANGUAGE, [str(count)]
        )

    if provider_message_id is None:
        message.status = "skipped"
        message.error = "WhatsApp not configured"
        return

    message.provider_message_id = provider_message_id
    message.status = "sent"
    message.sent_at = datetime.now(timezone.utc)


def apply_status_update(message: OutboundMessage, status: str, error: str | None = None) -> bool:
    """Applies one delivery-status webhook callback to its matching
    OutboundMessage row. Returns True if it changed anything.

    Two terminal states -- "failed" and (implicitly, never reached from
    here) "skipped" -- don't accept further updates once set: a "failed"
    row stays failed regardless of what arrives after (Meta's delivery-
    status callbacks aren't guaranteed ordered). Otherwise, monotonic
    ordering: an incoming status ranked at or below the current one is
    ignored rather than applied, so a duplicate or out-of-order callback
    can't regress an already-"read" row back to "delivered"."""
    if message.status == "failed":
        return False

    if status == "failed":
        message.status = "failed"
        message.error = error
        message.failed_at = datetime.now(timezone.utc)
        return True

    incoming_rank = _STATUS_RANK.get(status)
    if incoming_rank is None:
        return False  # unknown status value -- ignore rather than guess

    current_rank = _STATUS_RANK.get(message.status, -1)
    if incoming_rank <= current_rank:
        return False

    message.status = status
    now = datetime.now(timezone.utc)
    if status == "sent":
        message.sent_at = message.sent_at or now
    elif status == "delivered":
        message.delivered_at = now
    elif status == "read":
        message.read_at = now
    return True
