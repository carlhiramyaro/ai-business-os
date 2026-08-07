import hashlib
import os
from datetime import datetime, timezone

import pandas as pd
import structlog
from dotenv import load_dotenv
from langfuse import observe, propagate_attributes
from sqlalchemy.orm import Session

from app.auth_maintenance import delete_expired_refresh_tokens
from app.celery_app import celery_app
from app.channels import (
    MAX_HISTORY_MESSAGES,
    format_for_channel,
    get_or_create_channel_conversation,
    redeem_link_code,
    resolve_identity,
)
from app.chat_generation import generate_chat_answer
from app.column_mapping import resolve_column_mapping
from app.database import SessionLocal
from app.document_extraction import extract_document
from app.ingestion import RECORD_FIELD_MAP, ingest_rows
from app.insight_delivery import collect_and_queue_digests
from app.insights_generation import run_business_analysis
from app.models import (
    Business,
    ChannelIdentity,
    ColumnMapping,
    DatasetProfile,
    DocumentExtraction,
    Message,
    OutboundMessage,
    Report,
    UploadSession,
)
from app.outbound import deliver_outbound_message
from app.report_generation import generate_report, run_report_generation
from app.storage import document_key_for, download_fileobj, key_for
from app.whatsapp import send_text

load_dotenv()

logger = structlog.get_logger(__name__)

MAPPING_CONFIDENCE_THRESHOLD = float(os.getenv("MAPPING_CONFIDENCE_THRESHOLD", "0.8"))


def _header_set_hash(headers) -> str:
    return hashlib.sha256("|".join(sorted(headers)).encode()).hexdigest()


def _mark_failed(db: Session, upload_session: UploadSession) -> None:
    db.rollback()
    upload_session.status = "FAILED"
    upload_session.completed_at = datetime.now(timezone.utc)
    db.commit()


def _provided_dataset_types(upload_session: UploadSession) -> list[str]:
    """Which of sales/inventory/expenses were actually uploaded for this
    session -- derived from the nullable *_file_url columns rather than
    assuming all three, so a sales-only (or any partial) upload only
    column-maps/ingests/profiles the datasets that exist. See
    app/routers/upload.py's create_upload."""
    return [dt for dt in ("sales", "inventory", "expenses") if getattr(upload_session, f"{dt}_file_url")]


@celery_app.task(name="run_column_mapping")
def run_column_mapping_task(upload_session_id: str):
    # propagate_attributes wraps the call from outside rather than being
    # stacked as a second decorator under @celery_app.task -- avoids any
    # risk of Celery's task registration/signature introspection
    # misbehaving under a doubly-decorated function. See
    # docs/infra-guide.md.
    with propagate_attributes(session_id=str(upload_session_id)):
        _run_column_mapping(upload_session_id)


@observe(name="column_mapping")
def _run_column_mapping(upload_session_id: str):
    db: Session = SessionLocal()
    upload_session = None
    try:
        upload_session = db.get(UploadSession, upload_session_id)
        if upload_session is None:
            return

        upload_session.processing_started_at = datetime.now(timezone.utc)
        db.commit()

        any_needs_review = False

        for dataset_type in _provided_dataset_types(upload_session):
            key = key_for(upload_session.business_id, upload_session.id, dataset_type)
            df = pd.read_csv(download_fileobj(key))
            header_hash = _header_set_hash(df.columns)

            for header in df.columns:
                sample_values = [str(v) for v in df[header].dropna().head(3).tolist()]
                mapping = resolve_column_mapping(header, dataset_type, sample_values)

                db.add(
                    ColumnMapping(
                        upload_session_id=upload_session.id,
                        business_id=upload_session.business_id,
                        dataset_type=dataset_type,
                        source_column_name=header,
                        target_field=mapping["targetField"],
                        confidence_score=mapping["confidenceScore"],
                        mapping_method=mapping["mappingMethod"],
                        header_set_hash=header_hash,
                        sample_values=sample_values,
                    )
                )

                if mapping["confidenceScore"] < MAPPING_CONFIDENCE_THRESHOLD:
                    any_needs_review = True

        db.commit()

        if any_needs_review:
            upload_session.status = "NEEDS_REVIEW"
            db.commit()
        else:
            upload_session.status = "PROCESSING"
            db.commit()
            finalize_upload_task.delay(str(upload_session.id))
    except Exception:
        if upload_session is not None:
            _mark_failed(db, upload_session)
        raise
    finally:
        db.close()


@celery_app.task(name="finalize_upload")
def finalize_upload_task(upload_session_id: str):
    db: Session = SessionLocal()
    upload_session = None
    try:
        upload_session = db.get(UploadSession, upload_session_id)
        if upload_session is None:
            return

        period_start = period_end = None

        for dataset_type in _provided_dataset_types(upload_session):
            key = key_for(upload_session.business_id, upload_session.id, dataset_type)
            df = pd.read_csv(download_fileobj(key))

            mappings = (
                db.query(ColumnMapping)
                .filter(
                    ColumnMapping.upload_session_id == upload_session.id,
                    ColumnMapping.dataset_type == dataset_type,
                )
                .all()
            )
            header_to_field = {
                m.source_column_name: RECORD_FIELD_MAP[dataset_type].get(m.target_field) for m in mappings
            }

            # Translate the CSV into the canonical snake_case-keyed row dicts
            # that app.ingestion.ingest_rows -- the same boundary manual
            # entry and document extraction call -- expects. Casting, entity
            # resolution, and dedup-hashing all happen inside ingest_rows,
            # not here.
            rows = []
            for row in df.itertuples(index=False):
                record = {}
                for header, value in zip(df.columns, row):
                    field_name = header_to_field.get(header)
                    if field_name:
                        record[field_name] = value
                rows.append(record)

            summary = ingest_rows(db, upload_session.business_id, upload_session.id, dataset_type, rows)

            if summary.duplicate_count:
                upload_session.duplicate_warning = True

            if dataset_type in ("sales", "expenses"):
                if summary.date_range_start is not None:
                    period_start = (
                        summary.date_range_start
                        if period_start is None
                        else min(period_start, summary.date_range_start)
                    )
                if summary.date_range_end is not None:
                    period_end = (
                        summary.date_range_end if period_end is None else max(period_end, summary.date_range_end)
                    )

            db.add(
                DatasetProfile(
                    upload_session_id=upload_session.id,
                    dataset_type=dataset_type,
                    total_rows=len(df),
                    duplicate_rows=int(df.duplicated().sum()),
                    missing_values=int(df.isna().sum().sum()),
                    date_range_start=summary.date_range_start,
                    date_range_end=summary.date_range_end,
                )
            )

        if period_start is None or period_end is None:
            # Inventory-only upload, or every sales/expenses date column was mapped
            # to "ignore" / failed to parse. Fall back to a single-day period
            # anchored on the upload itself. Since the cumulative report query also
            # date-filters Sale/Expense rows, this means finance/marketing/operations
            # metrics will reflect an empty set for this report (inventory metrics
            # still populate normally, since inventory isn't date-filtered) -- a
            # real, visible edge case, not swept under the rug.
            period_start = period_end = upload_session.uploaded_at.date()

        business = db.get(Business, upload_session.business_id)
        generate_report(
            db,
            business,
            period_start=period_start,
            period_end=period_end,
            upload_session_id=upload_session.id,
        )

        upload_session.status = "COMPLETED"
        upload_session.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        if upload_session is not None:
            _mark_failed(db, upload_session)
        raise
    finally:
        db.close()


def _mark_report_failed(db: Session, report: Report) -> None:
    db.rollback()
    report.status = "FAILED"
    db.commit()


@celery_app.task(name="generate_report")
def generate_report_task(report_id: str):
    db: Session = SessionLocal()
    report = None
    try:
        report = db.get(Report, report_id)
        if report is None:
            return
        business = db.get(Business, report.business_id)
        run_report_generation(db, business, report)
    except Exception:
        if report is not None:
            _mark_report_failed(db, report)
        raise
    finally:
        db.close()


@celery_app.task(name="extract_document")
def extract_document_task(upload_session_id: str, dataset_type: str, mime_type: str = "image/jpeg"):
    """v0.3 document processing: download the photographed receipt/invoice,
    run vision extraction, and stash the (uncast) rows on a new
    DocumentExtraction for the user to review. Always lands on
    NEEDS_REVIEW -- extraction here is best-effort by design (see
    app/document_extraction.py's docstring), never auto-confirmed the way
    a high-confidence CSV column mapping can skip review."""
    db: Session = SessionLocal()
    upload_session = None
    try:
        upload_session = db.get(UploadSession, upload_session_id)
        if upload_session is None:
            return

        key = document_key_for(upload_session.business_id, upload_session.id)
        image_bytes = download_fileobj(key).read()

        with propagate_attributes(session_id=str(upload_session_id)):
            result = extract_document(image_bytes, dataset_type, mime_type=mime_type)

        db.add(
            DocumentExtraction(
                upload_session_id=upload_session.id,
                business_id=upload_session.business_id,
                dataset_type=dataset_type,
                extracted_rows=result["rows"],
                overall_confidence=result["confidence"],
            )
        )
        upload_session.status = "NEEDS_REVIEW"
        db.commit()
    except Exception:
        if upload_session is not None:
            _mark_failed(db, upload_session)
        raise
    finally:
        db.close()


@celery_app.task(name="run_business_analysis")
def run_business_analysis_task(business_id: str):
    """v0.4 slice 2: detect + narrate this business's insights (on-demand
    via POST /insights/run, or scheduled -- see
    dispatch_scheduled_analysis_task below). Errors aren't persisted onto
    any row the way upload/report failures are (there's no in-flight
    "analysis session" record) -- Celery's own retry/failure visibility
    covers this task."""
    db: Session = SessionLocal()
    try:
        business = db.get(Business, business_id)
        if business is None:
            return
        run_business_analysis(db, business)
    finally:
        db.close()


@celery_app.task(name="dispatch_scheduled_analysis")
def dispatch_scheduled_analysis_task():
    """Celery beat's entry point (app/celery_app.py's beat_schedule) -- fans
    out one run_business_analysis_task per business so each business's
    analysis is isolated and independently retryable, rather than one giant
    task looping over every business inline."""
    db: Session = SessionLocal()
    try:
        business_ids = [row.id for row in db.query(Business.id).all()]
    finally:
        db.close()

    for business_id in business_ids:
        run_business_analysis_task.delay(str(business_id))


_LINK_WELCOME = "Linked to {business_name}. Ask me anything about your business, e.g. \"how did I do this week?\""
_LINK_INSTRUCTIONS = (
    "This number isn't linked to a business yet. Log in at the web app, go to Settings, "
    "and generate a link code -- then text that code here to connect."
)
_LINK_INVALID = "That code isn't valid or has expired. Generate a new one from Settings and try again."


def _send_reply(db: Session, business: Business, identity: ChannelIdentity, text: str) -> None:
    """Sends a chat reply through the same queue/audit/delivery-status
    infrastructure v0.6 slice 2 introduced for proactive sends
    (app/outbound.py) -- one OutboundMessage row per WhatsApp message
    chunk, so delivery status is meaningful for every message this app
    sends, not just insight pushes. Delivered INLINE (deliver_outbound_
    message called directly, not via send_outbound_message_task.delay())
    rather than re-queued: this function already runs inside a background
    task, so a second queue hop would only add latency for a reply the
    owner is actively waiting on. Insight pushes queue instead, because
    they have no one waiting synchronously. See docs/decisions.md."""
    for part in format_for_channel(text, "whatsapp"):
        message = OutboundMessage(
            business_id=business.id,
            channel_identity_id=identity.id,
            channel="whatsapp",
            kind="chat_reply",
            body=part,
            send_method="session",
            status="queued",
        )
        db.add(message)
        db.flush()
        deliver_outbound_message(db, message, identity)
        db.commit()


def _handle_unlinked_message(db: Session, from_wa_id: str, text: str, contact_name: str | None) -> None:
    """No ChannelIdentity exists yet for this number -- the only thing a
    message from it can mean is "this is a link code" or "this number
    hasn't been linked." Sends the pre-linking replies directly via
    send_text (not the OutboundMessage queue -- there's no business to
    scope an audit row to, by definition, before linking succeeds)."""
    candidate = text.strip()
    looks_like_code = candidate and " " not in candidate and len(candidate) <= 12
    if not looks_like_code:
        send_text(from_wa_id, _LINK_INSTRUCTIONS)
        return

    identity = redeem_link_code(db, candidate, "whatsapp", from_wa_id, display_name=contact_name)
    if identity is None:
        send_text(from_wa_id, _LINK_INVALID)
        return

    # This very message is what just proved the number can receive a
    # reply right now -- set before the welcome send below so
    # deliver_outbound_message's session-window check (were it used here)
    # would see it as current. Kept as a direct send_text since there's no
    # prior Message/Conversation context to anchor an OutboundMessage's
    # audit trail to yet.
    identity.last_inbound_at = datetime.now(timezone.utc)
    db.commit()
    business = db.get(Business, identity.business_id)
    send_text(from_wa_id, _LINK_WELCOME.format(business_name=business.business_name))


@celery_app.task(name="handle_whatsapp_message")
def handle_whatsapp_message_task(message_id: str, from_wa_id: str, text: str, contact_name: str | None = None):
    """v0.6 slice 1: routes one inbound WhatsApp text through to the SAME
    chat agent loop the web UI uses (app/chat_generation.py, entirely
    unchanged) and sends the answer back. app/routers/webhooks.py enqueues
    this after verifying the signature and recording the message for
    idempotency -- this task trusts message_id/from_wa_id/text as already
    validated.

    Tenant scoping comes ONLY from the resolved ChannelIdentity, never from
    anything in the inbound payload -- see app/models/channel.py."""
    db: Session = SessionLocal()
    try:
        identity = resolve_identity(db, "whatsapp", from_wa_id)
        if identity is None:
            _handle_unlinked_message(db, from_wa_id, text, contact_name)
            return

        # v0.6 slice 2: opens/refreshes the 24h customer-service window --
        # set before the reply below so its own send resolves as "session"
        # rather than "template". See app/outbound.py.
        identity.last_inbound_at = datetime.now(timezone.utc)

        business = db.get(Business, identity.business_id)
        conversation = get_or_create_channel_conversation(db, identity)

        db.add(Message(conversation_id=conversation.id, role="user", content=text))
        db.flush()

        history = [
            {"role": m.role, "content": m.content}
            for m in db.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
            .all()[:-1]  # exclude the message just added -- passed separately below
        ][-MAX_HISTORY_MESSAGES:]

        with propagate_attributes(
            session_id=str(conversation.id), metadata={"business_id": str(business.id), "channel": "whatsapp"}
        ):
            result = generate_chat_answer(db, business, text, history)

        db.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content=result.answer,
                tool_calls=result.tool_calls,
            )
        )
        db.commit()

        _send_reply(db, business, identity, result.answer)
    finally:
        db.close()


@celery_app.task(name="send_outbound_message")
def send_outbound_message_task(outbound_message_id: str):
    """v0.6 slice 2: delivers one queued proactive message
    (app/insight_delivery.py's deliver_immediate/collect_and_queue_digests
    both enqueue this after app/outbound.py's queue_message). Thin wrapper
    around app/outbound.py's deliver_outbound_message, matching this
    file's existing task-is-a-thin-wrapper convention (e.g.
    generate_report_task -> run_report_generation)."""
    db: Session = SessionLocal()
    try:
        message = db.get(OutboundMessage, outbound_message_id)
        if message is None:
            return
        identity = db.get(ChannelIdentity, message.channel_identity_id)
        if identity is None:
            return
        deliver_outbound_message(db, message, identity)
        db.commit()
    finally:
        db.close()


@celery_app.task(name="dispatch_whatsapp_digests")
def dispatch_whatsapp_digests_task():
    """Celery beat's entry point (app/celery_app.py's beat_schedule) for
    "daily_digest"-frequency identities -- independent of when analysis
    itself ran (unlike "immediate", which fires from inside
    run_business_analysis), this batches whatever's accumulated since each
    identity's last digest. See app/insight_delivery.py."""
    db: Session = SessionLocal()
    try:
        queued = collect_and_queue_digests(db)
    finally:
        db.close()
    logger.info("whatsapp_digests_dispatched", queued_count=queued)


@celery_app.task(name="cleanup_expired_refresh_tokens")
def cleanup_expired_refresh_tokens_task():
    """v0.5 slice 3: beat-scheduled (app/celery_app.py's beat_schedule) --
    without this, expired RefreshToken rows only ever get deleted lazily,
    on the specific unlucky path where someone tries to *use* an
    already-expired token, or explicitly on /logout. A user who never logs
    out (the common case) leaves an ever-growing pile of expired rows
    forever. Logs the deleted count as the only observable signal this ran
    at all -- makes "is the table being kept flat" a CloudWatch query
    instead of a psql session, and a sudden spike in the count is itself a
    legitimate signal (mass logout, or a token-issuance bug)."""
    db: Session = SessionLocal()
    try:
        deleted = delete_expired_refresh_tokens(db)
    finally:
        db.close()
    logger.info("refresh_tokens_cleaned", deleted_count=deleted)
