"""Vision-LLM extraction of a photographed receipt/invoice into structured
rows (v0.3, see docs/roadmap.md, docs/decisions.md [2026-07-24]) -- the
document-era sibling of app/column_mapping.py's LLM fallback. Where column
mapping guesses which canonical field a CSV *header* means, this guesses
both the row structure and the values directly from an image, since a
photo has no header row to map.

Uses gpt-4o (not the gpt-4o-mini used elsewhere) -- multimodal extraction
from real-world receipt photos needs materially better vision accuracy
than the rest of the app's text-only calls (see docs/decisions.md
[2026-07-24]).

Extraction is best-effort by design (roadmap.md: "no handwriting-heavy
document support beyond best-effort extraction") -- every document always
goes to a human review step regardless of reported confidence; nothing here
decides NEEDS_REVIEW vs. auto-proceed the way column mapping's confidence
threshold does.
"""

import base64
import json
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

# Drop-in replacement for openai.OpenAI -- traces every call to Langfuse
# with no other code change. See docs/infra-guide.md. propagate_attributes
# (session_id=upload_session_id) is applied at the call site in
# app/tasks.py's extract_document_task, not here -- this function doesn't
# receive upload_session_id itself.
from langfuse import observe, propagate_attributes
from langfuse.openai import OpenAI
from sqlalchemy.orm import Session

from app.column_mapping import CANONICAL_FIELDS
from app.ingestion import RECORD_FIELD_MAP, IngestSummary, ingest_rows
from app.models import DocumentExtraction, UploadSession
from app.storage import document_key_for, download_fileobj

load_dotenv()

VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o")


def _call_vision_llm(system_prompt: str, image_bytes: bytes, mime_type: str) -> dict:
    client = OpenAI()
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract every line item from this document."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                ],
            },
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _parse_extraction_response(raw: dict, dataset_type: str) -> dict:
    """Deterministic validation of the vision model's JSON output --
    independently testable with a fixed input dict, no network call. Never
    trusts the model to have followed the field-name instruction exactly:
    drops any key that isn't one of this dataset's canonical fields rather
    than passing it through to ingestion."""
    fields = set(CANONICAL_FIELDS[dataset_type])
    raw_rows = raw.get("rows", [])
    if not isinstance(raw_rows, list):
        raw_rows = []

    rows = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        rows.append({field: value for field, value in raw_row.items() if field in fields})

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = round(max(0.0, min(confidence, 1.0)), 2)

    return {"rows": rows, "confidence": confidence}


@observe(name="extract_document")
def extract_document(image_bytes: bytes, dataset_type: str, *, mime_type: str = "image/jpeg") -> dict:
    """Returns {"rows": [{<canonical camelCase field>: <raw value>, ...}, ...],
    "confidence": 0.0-1.0}. Rows are NOT cast/typed yet -- that happens in
    app.ingestion.ingest_rows at confirm time, same deterministic-vs-LLM
    split the CSV path uses. Only this function's LLM call should be mocked
    in tests; _parse_extraction_response is separately, deterministically
    testable."""
    fields = CANONICAL_FIELDS[dataset_type]
    system_prompt = (
        "You extract structured line items from a photographed receipt or "
        f"invoice for a '{dataset_type}' record. Valid canonical fields: "
        f"{', '.join(fields)}. Extract one JSON object per line item/row "
        "you can identify, using only these field names -- omit a field "
        "entirely if you can't read it clearly, rather than guessing. "
        'Respond as strict JSON: {"rows": [{"<field>": "<value>", ...}, '
        '...], "confidence": 0.0-1.0} where confidence reflects your '
        "overall certainty about the extraction. If the image has no "
        'legible relevant line items, respond {"rows": [], "confidence": 0.0}.'
    )
    raw = _call_vision_llm(system_prompt, image_bytes, mime_type)
    return _parse_extraction_response(raw, dataset_type)


def run_document_extraction(
    db: Session, upload_session: UploadSession, dataset_type: str, mime_type: str
) -> DocumentExtraction:
    """Downloads the uploaded image from S3, runs vision extraction, and
    persists a DocumentExtraction + NEEDS_REVIEW transition. Shared by
    app/tasks.py's extract_document_task (the v0.3 web upload flow --
    `upload_session` already has its image in S3 by the time this runs)
    and handle_whatsapp_image_task (v0.6 slice 4 -- uploads the WhatsApp-
    downloaded image to S3 itself first, then calls this exactly the same
    way). See docs/decisions.md."""
    key = document_key_for(upload_session.business_id, upload_session.id)
    image_bytes = download_fileobj(key).read()

    with propagate_attributes(session_id=str(upload_session.id)):
        result = extract_document(image_bytes, dataset_type, mime_type=mime_type)

    extraction = DocumentExtraction(
        upload_session_id=upload_session.id,
        business_id=upload_session.business_id,
        dataset_type=dataset_type,
        extracted_rows=result["rows"],
        overall_confidence=result["confidence"],
    )
    db.add(extraction)
    upload_session.status = "NEEDS_REVIEW"
    db.commit()
    return extraction


def commit_document_extraction(db: Session, upload_session: UploadSession, extraction: DocumentExtraction) -> IngestSummary:
    """Translates extraction.extracted_rows (canonical camelCase, per
    CANONICAL_FIELDS) through RECORD_FIELD_MAP into ingest_rows's expected
    snake_case shape and calls it for real -- casting happens here, at
    confirm time, not at extraction time, same deterministic-vs-LLM split
    the CSV path uses. Shared by the web confirm endpoint
    (app/routers/documents.py) and confirm_document_review (v0.6 slice 4,
    the WhatsApp chat-tool equivalent) -- one commit path regardless of
    which review UI triggered it."""
    field_map = RECORD_FIELD_MAP[extraction.dataset_type]
    rows = [
        {field_map[field]: value for field, value in row.items() if field in field_map}
        for row in extraction.extracted_rows
    ]
    summary = ingest_rows(db, upload_session.business_id, upload_session.id, extraction.dataset_type, rows)
    if summary.duplicate_count:
        upload_session.duplicate_warning = True
    upload_session.status = "COMPLETED"
    upload_session.completed_at = datetime.now(timezone.utc)
    db.commit()
    return summary


def format_extraction_summary(dataset_type: str, rows: list[dict]) -> str:
    """Deterministic composition of the confirmation-request message sent
    after a v0.6 slice 4 WhatsApp photo is extracted -- no LLM involved
    (extraction's own uncertainty is already captured in
    overall_confidence; this just lists what was found in plain text).
    Fixed input -> expected output, independently testable, same
    deterministic/LLM separation every other confirmation summary in this
    codebase follows (app/data_entry.py's propose_*_entry)."""
    if not rows:
        return (
            "I couldn't read anything clearly from that photo. Try a clearer photo, "
            "or tell me the details and I'll record it directly."
        )
    lines = [f"I found {len(rows)} item{'s' if len(rows) != 1 else ''} on that {dataset_type[:-1] if dataset_type.endswith('s') else dataset_type} document:"]
    for i, row in enumerate(rows, start=1):
        parts = [f"{field}: {value}" for field, value in row.items() if value not in (None, "")]
        lines.append(f"{i}. {', '.join(parts)}" if parts else f"{i}. (unclear)")
    lines.append("Reply YES to record these, or NO to discard.")
    return "\n".join(lines)


def _active_document_review(db: Session, business_id: uuid.UUID) -> UploadSession | None:
    return (
        db.query(UploadSession)
        .filter(
            UploadSession.business_id == business_id,
            UploadSession.source_type == "document",
            UploadSession.status == "NEEDS_REVIEW",
        )
        .order_by(UploadSession.uploaded_at.desc())
        .first()
    )


def confirm_document_review(db: Session, business_id: uuid.UUID) -> dict:
    """The WhatsApp chat-tool equivalent of the web review screen's
    "Confirm" button (app/routers/documents.py's POST .../confirm) --
    called by app/chat_generation.py's confirm_document_review tool when
    the model recognizes the owner confirming a previously proposed photo
    extraction. Business-scoped, like app/data_entry.py's pending entries
    -- picks the single most recent NEEDS_REVIEW document session for this
    business; an older, never-reviewed one (e.g. two photos sent before
    either was confirmed) is left exactly as a web user's forgotten
    upload already would be -- no new supersede logic introduced here."""
    session = _active_document_review(db, business_id)
    if session is None:
        return {"confirmed": False, "reason": "No document waiting for review."}

    extraction = db.query(DocumentExtraction).filter(DocumentExtraction.upload_session_id == session.id).one()
    summary = commit_document_extraction(db, session, extraction)
    return {"confirmed": True, "rows_recorded": summary.inserted, "duplicate_warning": summary.duplicate_count > 0}


def cancel_document_review(db: Session, business_id: uuid.UUID) -> dict:
    session = _active_document_review(db, business_id)
    if session is None:
        return {"cancelled": False, "reason": "No document waiting for review."}

    # No "declined by owner" status exists in upload_sessions' vocabulary
    # (PROCESSING/NEEDS_REVIEW/COMPLETED/FAILED) -- FAILED is reused
    # deliberately rather than adding a new status value across the
    # frontend's UploadStatusValue type for a one-slice-only distinction.
    # See docs/decisions.md.
    session.status = "FAILED"
    session.completed_at = datetime.now(timezone.utc)
    db.commit()
    return {"cancelled": True}
