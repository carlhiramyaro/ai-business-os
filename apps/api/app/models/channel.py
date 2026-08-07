import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


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
