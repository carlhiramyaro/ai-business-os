import os

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OutboundMessage, WebhookEvent
from app.outbound import apply_status_update
from app.rate_limit import RateLimit
from app.whatsapp import parse_inbound, verify_signature

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])
logger = structlog.get_logger(__name__)

# v0.6 slice 1: not a security limit, not really a cost circuit-breaker
# either -- Meta itself is the only realistic caller, but it retries
# aggressively on anything slower than a fast 2xx, and a stray/malicious
# POST here does nothing but insert a WebhookEvent row and (on a valid
# signature only) enqueue a task, so a generous IP-keyed ceiling is enough.
_RATE_LIMIT_WEBHOOK = os.getenv("RATE_LIMIT_WEBHOOK", "120/minute")


@router.get("/whatsapp")
def verify_whatsapp_webhook(request: Request):
    """Meta's one-time subscription handshake (WhatsApp > Configuration >
    Webhook, "Verify and save"): echoes back hub.challenge as PLAIN TEXT
    (not JSON -- Meta's verifier compares the raw response body) if and
    only if hub.verify_token matches what this app was configured with.
    See docs/learning-guide.md."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if mode == "subscribe" and expected_token and token == expected_token:
        return Response(content=challenge or "", media_type="text/plain")

    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("/whatsapp", dependencies=[Depends(RateLimit(_RATE_LIMIT_WEBHOOK, "webhook"))])
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """The only `async def` route in this codebase (every other router uses
    plain `def`) -- deliberate, not a style drift: Starlette's raw-body
    read (`request.body()`) is async-only, and this route needs the exact
    raw bytes for signature verification before any parsing happens. The
    sync `db: Session` dependency still works unchanged here -- FastAPI
    runs synchronous dependencies in a threadpool regardless of whether the
    endpoint itself is sync or async.

    Verifies the signature, records each message for idempotency, and
    enqueues handling -- then returns 200 unconditionally. Deliberately
    does NOT depend on require_worker_online (app/dependencies.py) the way
    every other Celery-enqueuing route does: 503-ing here would teach Meta
    "this webhook is broken," and repeated failures can get the
    subscription auto-disabled. A dropped message with a down worker is
    logged (Sentry-visible) instead -- see docs/decisions.md.

    Reads the raw body via request.body() and verifies BEFORE any JSON
    parsing -- re-serializing the parsed payload would not reproduce the
    exact bytes Meta signed. See app/whatsapp.py's verify_signature."""
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")

    if not verify_signature(raw_body, signature):
        logger.warning("whatsapp_webhook_bad_signature")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    payload = await request.json()
    parsed = parse_inbound(payload)

    # Imported lazily: app.tasks imports a wide swath of the app (report
    # generation, insights, document extraction) that this module has no
    # other reason to pull in at import time.
    from app.tasks import handle_whatsapp_message_task

    for message in parsed.messages:
        db.add(WebhookEvent(provider="whatsapp", external_id=message.message_id, payload=payload))
        try:
            db.commit()
        except IntegrityError:
            # Already-seen message_id -- Meta's at-least-once redelivery.
            # Not an error condition, just "nothing left to do here".
            db.rollback()
            continue

        try:
            handle_whatsapp_message_task.delay(
                message.message_id, message.from_wa_id, message.text, message.contact_name
            )
        except Exception:
            # Broker unreachable, etc. -- logged and dropped rather than
            # surfaced to Meta as a webhook failure, same reasoning as the
            # require_worker_online skip above.
            logger.error("whatsapp_webhook_enqueue_failed", message_id=message.message_id, exc_info=True)

    # v0.6 slice 2: delivery-status callbacks for messages THIS app sent.
    # Applied directly, not enqueued -- a status update is a fast, pure DB
    # write with no LLM call and nothing to retry independently, unlike
    # handling an inbound message above.
    for status_update in parsed.statuses:
        outbound_message = (
            db.query(OutboundMessage)
            .filter(OutboundMessage.provider_message_id == status_update.message_id)
            .one_or_none()
        )
        if outbound_message is None:
            # Expected for anything sent before this deploy, or a status
            # callback for a message this app never sent -- not an error.
            continue
        if apply_status_update(outbound_message, status_update.status, status_update.error):
            db.commit()

    return Response(status_code=status.HTTP_200_OK)
