import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base

# v0.6 slice 2: an identity's owner-chosen proactive-delivery setting.
# "off" is the default (opt-in, not opt-out) -- linking a number is for
# asking questions; agreeing to receive unprompted messages is a separate,
# deliberate choice. See docs/decisions.md.
NOTIFICATION_FREQUENCIES = ("off", "immediate", "daily_digest")


class ChannelIdentity(Base):
    """v0.6 slice 1 (roadmap.md "WhatsApp channel") -- links one external
    messaging identity (a WhatsApp phone number today; `channel` leaves room
    for more later) to exactly one (user, business) pair. This is the ONLY
    source of tenant scoping for inbound channel messages -- there is no JWT
    on a webhook request, so every handler resolves business_id through this
    table, never from anything in the provider's payload. See
    docs/decisions.md and CLAUDE.md's "every business-scoped query filters
    by businessId" rule.

    Unique on (channel, external_id): one phone number maps to exactly one
    business at a time. Linking the same number to a different business
    replaces this row (see app/channels.py's redeem_link_code) rather than
    creating a second identity -- a single inbound message must resolve
    unambiguously."""

    __tablename__ = "channel_identities"
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_channel_identities_channel_external_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    channel = Column(String, nullable=False)
    # The provider's stable identifier for this identity -- WhatsApp's
    # E.164-formatted "wa_id" (no leading '+') for channel="whatsapp".
    external_id = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    verified_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # v0.6 slice 2 (roadmap.md "Outbound infrastructure + proactive
    # delivery", see docs/decisions.md): WhatsApp's 24-hour "customer
    # service window" opens on the customer's last inbound message -- a
    # free-form reply is only allowed inside that window; outside it, only
    # a pre-approved template message can be sent. Updated on every inbound
    # message from this identity (app/tasks.py's
    # handle_whatsapp_message_task). NULL means "never messaged us" --
    # always outside the window.
    last_inbound_at = Column(DateTime(timezone=True), nullable=True)
    notification_frequency = Column(String, nullable=False, server_default="off")
    # NULL means "never sent" -- the digest dispatcher treats that the same
    # as "due now".
    last_digest_sent_at = Column(DateTime(timezone=True), nullable=True)


class ChannelLinkCode(Base):
    """A short-lived, single-use code generated from an authenticated web
    session (POST .../channels/whatsapp/link-code) and redeemed by texting
    it from WhatsApp. Proves control of both the logged-in account and the
    phone number with no SMS-OTP infrastructure -- see docs/decisions.md for
    why this direction (web generates, WhatsApp redeems) was chosen over the
    reverse."""

    __tablename__ = "channel_link_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WebhookEvent(Base):
    """Idempotency ledger for inbound provider webhooks. WhatsApp Cloud API
    delivery is at-least-once -- a retried delivery with no dedupe key would
    re-answer the same question (and re-bill the LLM call) every time Meta
    retries. Same idea as ingestion's content_hash and insights'
    fingerprint: unique on (provider, external_id), inserted before the
    handling task is enqueued, so a duplicate insert IS the "already
    handled" signal -- no separate lookup-then-insert race. See
    docs/decisions.md."""

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_webhook_events_provider_external_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String, nullable=False)
    # The provider's message ID (WhatsApp's messages[].id).
    external_id = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# v0.6 slice 2 status vocabulary, in ascending delivery order except
# "failed"/"skipped" which can occur from any prior state. See
# app/outbound.py's apply_status_update for the monotonic-ordering rule
# this backs.
OUTBOUND_STATUSES = ("queued", "sent", "delivered", "read", "failed", "skipped")


class OutboundMessage(Base):
    """v0.6 slice 2 (roadmap.md "Outbound infrastructure + proactive
    delivery") -- the queue, send record, and delivery-status audit trail
    for every message this app sends on a channel, chat replies (slice 1)
    included, not just proactive insight pushes. One send path for
    everything a channel can receive means delivery status is meaningful
    for the whole channel, not half of it, and it's the "reused later by
    v1.0 agents" outbound infrastructure the roadmap's architectural-
    changes note calls out.

    A row is created (status="queued") by app/outbound.py's queue_message,
    then delivered by app/tasks.py's send_outbound_message_task, which
    decides session-message vs. template (app/outbound.py's
    within_session_window, keyed off the identity's last_inbound_at) and
    records the provider's message id for correlating later
    delivery-status webhook callbacks (app/routers/webhooks.py). See
    docs/decisions.md."""

    __tablename__ = "outbound_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    channel_identity_id = Column(UUID(as_uuid=True), ForeignKey("channel_identities.id"), nullable=False, index=True)
    channel = Column(String, nullable=False)
    # "chat_reply" | "insight_immediate" | "insight_digest" -- what
    # triggered this send, for the Settings-page audit trail later.
    kind = Column(String, nullable=False)
    # Insight ids this message was about, if any -- NULL for chat replies.
    related_insight_ids = Column(JSONB, nullable=True)
    body = Column(Text, nullable=False)
    # "session" (free-form, sent inside the 24h window) | "template"
    # (pre-approved notification, sent outside it -- see
    # app/outbound.py's docstring for why a template can't carry the
    # actual insight content).
    send_method = Column(String, nullable=False)
    # Meta's id for the sent message -- set only once actually sent;
    # correlates inbound statuses[] delivery-receipt callbacks back to
    # this row. Not unique at the DB level: a "skipped" (unconfigured) or
    # "failed" (never reached Meta) row never gets one.
    provider_message_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, server_default="queued")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
