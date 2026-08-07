"""v0.6 slice 2 (roadmap.md "Outbound infrastructure + proactive
delivery") -- turns newly created Insight rows into queued WhatsApp sends,
respecting each linked identity's own notification_frequency
(app/models/channel.py). Two call sites:

- deliver_immediate, called from app/insights_generation.py right after a
  scheduled/on-demand analysis run creates new insights -- one bundled
  message per "immediate" identity, not one message per insight, so a run
  that detects several signals at once doesn't flood the owner's phone.
- collect_and_queue_digests, the body of app/tasks.py's beat-scheduled
  dispatch_whatsapp_digests_task -- independent of when analysis actually
  ran, batches whatever's accumulated since the identity's last digest.

Both go through app/outbound.py's queue_message -- narration already
happened once (app/agents.py's narrate_insight, called from
insights_generation.py); this module only composes and delivers, no LLM
call of its own.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Business, ChannelIdentity, Insight
from app.outbound import queue_message

# Same env-overridable-interval precedent as ANALYSIS_INTERVAL_SECONDS
# (app/celery_app.py) -- lets a demo session shrink this well below the
# 24h production default without a code change.
DIGEST_INTERVAL_HOURS = int(os.getenv("WHATSAPP_DIGEST_INTERVAL_HOURS", "24"))


def compose_digest_message(business_name: str, insights: list[Insight]) -> str:
    """Deterministic text composition, no LLM call. Fixed input -> expected
    output, independently testable."""
    lines = [f"Business update for {business_name}:", ""]
    for i, insight in enumerate(insights, start=1):
        lines.append(f"{i}. {insight.title}")
        lines.append(insight.body)
        lines.append("")
    return "\n".join(lines).strip()


def _identities_for(db: Session, business_id: uuid.UUID, frequency: str) -> list[ChannelIdentity]:
    return (
        db.query(ChannelIdentity)
        .filter(ChannelIdentity.business_id == business_id, ChannelIdentity.notification_frequency == frequency)
        .all()
    )


def deliver_immediate(db: Session, business: Business, insights: list[Insight]) -> None:
    """Queues one bundled message per "immediate" identity for the
    insights a single analysis run just created, and enqueues the actual
    send -- callers don't need to know about send_outbound_message_task."""
    if not insights:
        return

    identities = _identities_for(db, business.id, "immediate")
    if not identities:
        return

    from app.tasks import send_outbound_message_task  # lazy: avoid import cycle (tasks.py imports this module)

    body = compose_digest_message(business.business_name, insights)
    insight_ids = [i.id for i in insights]
    for identity in identities:
        message = queue_message(
            db, business.id, identity, body, kind="insight_immediate", related_insight_ids=insight_ids
        )
        db.commit()
        send_outbound_message_task.delay(str(message.id))


def collect_and_queue_digests(db: Session, now: datetime | None = None) -> int:
    """Beat task body (app/tasks.py's dispatch_whatsapp_digests_task): for
    every "daily_digest" identity whose digest is due (never sent, or last
    checked >= DIGEST_INTERVAL_HOURS ago), gather insights created since
    then for that identity's business and, if there are any, queue one
    bundled message. Returns the count of digests queued.

    `last_digest_sent_at` is updated on every check for a due identity,
    not only when a digest was actually sent -- a quiet business with no
    new insights still counts as "checked," so it isn't re-scanned again
    until the next interval."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=DIGEST_INTERVAL_HOURS)

    identities = db.query(ChannelIdentity).filter(ChannelIdentity.notification_frequency == "daily_digest").all()

    from app.tasks import send_outbound_message_task  # lazy: avoid import cycle (tasks.py imports this module)

    queued = 0
    for identity in identities:
        if identity.last_digest_sent_at is not None and identity.last_digest_sent_at > cutoff:
            continue

        since = identity.last_digest_sent_at or identity.created_at
        insights = (
            db.query(Insight)
            .filter(Insight.business_id == identity.business_id, Insight.created_at > since)
            .order_by(Insight.created_at)
            .all()
        )

        identity.last_digest_sent_at = now
        if not insights:
            db.commit()
            continue

        business = db.get(Business, identity.business_id)
        body = compose_digest_message(business.business_name, insights)
        message = queue_message(
            db,
            identity.business_id,
            identity,
            body,
            kind="insight_digest",
            related_insight_ids=[i.id for i in insights],
        )
        db.commit()
        send_outbound_message_task.delay(str(message.id))
        queued += 1

    return queued
