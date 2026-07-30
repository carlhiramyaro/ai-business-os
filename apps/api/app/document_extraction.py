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

from dotenv import load_dotenv

# Drop-in replacement for openai.OpenAI -- traces every call to Langfuse
# with no other code change. See docs/infra-guide.md. propagate_attributes
# (session_id=upload_session_id) is applied at the call site in
# app/tasks.py's extract_document_task, not here -- this function doesn't
# receive upload_session_id itself.
from langfuse import observe
from langfuse.openai import OpenAI

from app.column_mapping import CANONICAL_FIELDS

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
