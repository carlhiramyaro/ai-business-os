import difflib
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Heuristics run first and are cheap/instant; the LLM is only called when a
# header doesn't clearly match anything (mvp-scope.md: "heuristics first,
# LLM fallback for ambiguous columns"). Keeping this pure/deterministic
# means it's testable with fixed input -> expected output, no network call,
# per agent-instructions.md's rule for deterministic stages.
HEURISTIC_ACCEPT_THRESHOLD = 0.75

# Sentinel target field meaning "this source column has no useful home in
# our schema" (e.g. an internal order ID, a redundant product code when we
# already capture product name). Lets the LLM fallback -- and the user, via
# the review screen -- say "skip this" instead of being forced into the
# closest-but-wrong canonical field. finalize_upload_task's
# RECORD_FIELD_MAP.get(...) already returns None for any unrecognized
# target, so columns mapped to this are silently skipped at ingestion with
# no further plumbing needed.
IGNORE_FIELD = "ignore"

CANONICAL_FIELDS: dict[str, list[str]] = {
    "sales": [
        "saleDate",
        "productName",
        "category",
        "quantity",
        "unitPrice",
        "discount",
        "totalAmount",
        "customerName",
        "paymentMethod",
    ],
    "inventory": [
        "productName",
        "sku",
        "category",
        "quantity",
        "reorderLevel",
        "supplier",
        "costPrice",
        "sellingPrice",
    ],
    "expenses": ["expenseDate", "category", "vendor", "amount", "description"],
}

ALIASES: dict[str, list[str]] = {
    "saleDate": ["date", "sale date", "transaction date", "order date"],
    "productName": ["product", "product name", "item", "item name"],
    "category": ["category", "type", "product category"],
    "quantity": ["qty", "quantity", "units", "units sold"],
    "unitPrice": ["unit price", "price", "unitprice", "price per unit"],
    "discount": ["discount", "disc", "discount amount"],
    "totalAmount": ["total amount", "amt", "amount", "total", "revenue"],
    "customerName": ["customer", "customer name", "client", "buyer"],
    "paymentMethod": ["payment method", "payment", "method", "payment type"],
    "sku": ["sku", "product code", "item code"],
    "reorderLevel": ["reorder level", "reorder point", "min stock", "minimum stock"],
    "supplier": ["supplier", "vendor name"],
    "costPrice": ["cost price", "cost", "unit cost"],
    "sellingPrice": ["selling price", "sale price", "retail price"],
    "expenseDate": ["date", "expense date"],
    "vendor": ["vendor", "supplier", "payee"],
    "amount": ["amount", "amt", "total", "expense amount"],
    "description": ["description", "notes", "memo", "details"],
}


def normalize_header(header: str) -> str:
    return " ".join(header.strip().lower().replace("_", " ").replace("-", " ").split())


def heuristic_match(header: str, dataset_type: str) -> tuple[str, float] | None:
    normalized = normalize_header(header)
    best_field: str | None = None
    best_ratio = 0.0

    for field in CANONICAL_FIELDS[dataset_type]:
        candidates = [normalize_header(field), *ALIASES.get(field, [])]
        for candidate in candidates:
            ratio = 1.0 if normalized == candidate else difflib.SequenceMatcher(None, normalized, candidate).ratio()
            if ratio > best_ratio:
                best_field, best_ratio = field, ratio

    if best_field is None:
        return None
    return best_field, round(best_ratio, 2)


def llm_match(header: str, dataset_type: str, sample_values: list[str]) -> tuple[str, float]:
    fields = CANONICAL_FIELDS[dataset_type]
    allowed_fields = [*fields, IGNORE_FIELD]
    client = OpenAI()

    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You map a messy CSV column header to exactly one canonical field name. "
                    f"Valid canonical fields for a '{dataset_type}' dataset: {', '.join(fields)}. "
                    f"If the column doesn't correspond to any of them -- e.g. an internal order/"
                    "transaction ID, or an identifier that duplicates a field we already capture "
                    f"(like a SKU when we already have productName) -- respond with '{IGNORE_FIELD}' "
                    "instead of forcing the closest-sounding field. "
                    'Respond with strict JSON: {"targetField": "<one of the valid fields or '
                    f'\'{IGNORE_FIELD}\'>", "confidence": <0.0-1.0>}}.'
                ),
            },
            {
                "role": "user",
                "content": f"Header: {header!r}\nSample values: {sample_values!r}",
            },
        ],
        response_format={"type": "json_object"},
    )

    parsed = json.loads(response.choices[0].message.content)
    target_field = parsed.get("targetField")
    confidence = float(parsed.get("confidence", 0.0))

    if target_field not in allowed_fields:
        return fields[0], 0.0

    return target_field, round(confidence, 2)


def resolve_column_mapping(header: str, dataset_type: str, sample_values: list[str]) -> dict:
    match = heuristic_match(header, dataset_type)
    if match is not None and match[1] >= HEURISTIC_ACCEPT_THRESHOLD:
        target_field, confidence = match
        return {"targetField": target_field, "confidenceScore": confidence, "mappingMethod": "heuristic"}

    target_field, confidence = llm_match(header, dataset_type, sample_values)
    return {"targetField": target_field, "confidenceScore": confidence, "mappingMethod": "llm"}
