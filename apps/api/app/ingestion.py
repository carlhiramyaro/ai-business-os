"""The one "validated rows in" boundary every data producer funnels
through -- the CSV pipeline (app/tasks.py's finalize_upload_task), quick
manual entry (app/routers/entries.py), and document extraction
(app/routers/documents.py) all translate their own input into canonical
snake_case-field row dicts and call ingest_rows(). Casting, customer/
supplier entity resolution, and dedup-hash detection then happen exactly
once, in exactly one place, regardless of which producer the rows came
from. See docs/roadmap.md v0.3 ("one canonical 'validated rows in'
interface with three producers") and docs/decisions.md [2026-07-24].
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

import pandas as pd
from sqlalchemy.orm import Session

from app.entities import resolve_customer, resolve_supplier
from app.models import Expense, Inventory, Sale

DATASET_MODELS = {"sales": Sale, "inventory": Inventory, "expenses": Expense}

# canonical (camelCase, matches erd.md/endpoints.md) -> ORM attribute (snake_case).
# The CSV producer uses this to translate a confirmed column mapping into a
# canonical row dict; manual-entry/document producers build the same shape
# directly from their own schemas.
RECORD_FIELD_MAP = {
    "sales": {
        "saleDate": "sale_date",
        "productName": "product_name",
        "category": "category",
        "quantity": "quantity",
        "unitPrice": "unit_price",
        "discount": "discount",
        "totalAmount": "total_amount",
        "customerName": "customer_name",
        "customerPhone": "customer_phone",
        "paymentMethod": "payment_method",
    },
    "inventory": {
        "productName": "product_name",
        "category": "category",
        "quantity": "quantity",
        "reorderLevel": "reorder_level",
        "supplier": "supplier",
        "costPrice": "cost_price",
        "sellingPrice": "selling_price",
    },
    "expenses": {
        "expenseDate": "expense_date",
        "category": "category",
        "vendor": "vendor",
        "amount": "amount",
        "description": "description",
    },
}

DATE_FIELDS = {"sale_date", "expense_date"}
INT_FIELDS = {"quantity", "reorder_level"}
DECIMAL_FIELDS = {"unit_price", "discount", "total_amount", "cost_price", "selling_price", "amount"}

DATE_FIELD_FOR_DATASET = {"sales": "sale_date", "expenses": "expense_date", "inventory": None}

# Natural-key fields (already-cast snake_case ORM field names) used to build
# each dataset's dedup content_hash. Deliberately excludes things like
# customer/payment-method/description that vary without changing whether two
# rows represent "the same" sale/expense/inventory line for warn-only dedup
# purposes -- see docs/decisions.md [2026-07-24].
DEDUP_FIELDS = {
    "sales": ("sale_date", "product_name", "quantity", "total_amount"),
    "expenses": ("expense_date", "category", "vendor", "amount"),
    "inventory": ("product_name", "quantity", "cost_price"),
}


@dataclass
class IngestSummary:
    inserted: int
    date_range_start: date_type | None
    date_range_end: date_type | None
    duplicate_count: int
    # Row order matches the input `rows` order -- callers that need the id
    # of a specific created row (e.g. a single manual entry, or a document
    # confirm step) can pair these up positionally.
    created_ids: list[uuid.UUID]


def _cast_value(field_name: str, value):
    if pd.isna(value):
        return None
    if field_name in DATE_FIELDS:
        parsed = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(parsed) else parsed.date()
    if field_name in INT_FIELDS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if field_name in DECIMAL_FIELDS:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
    return str(value)


def _content_hash(business_id, dataset_type: str, record_kwargs: dict) -> str:
    parts = [str(business_id), dataset_type]
    for field in DEDUP_FIELDS[dataset_type]:
        parts.append(str(record_kwargs.get(field)))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def ingest_rows(
    db: Session,
    business_id: uuid.UUID,
    upload_session_id: uuid.UUID,
    dataset_type: str,
    rows: list[dict],
    *,
    start_row_number: int = 1,
) -> IngestSummary:
    """Cast, resolve entities, dedup-hash, and insert `rows` (dicts keyed by
    canonical snake_case ORM field names, raw or castable values) for
    `dataset_type`. Rows whose content_hash matches an existing row for this
    business+dataset (or another row earlier in the same batch) are still
    inserted -- dedup here is detection-and-warn, never silent drop, per
    roadmap.md v0.3."""
    model_cls = DATASET_MODELS[dataset_type]
    date_field = DATE_FIELD_FOR_DATASET[dataset_type]

    # Pass 1: cast every row and compute its content_hash up front, so dedup
    # detection runs against stable, already-typed values regardless of which
    # producer supplied them (CSV strings, JSON body values, LLM extraction
    # output).
    casted_rows = []
    for raw_row in rows:
        record_kwargs = {"business_id": business_id, "upload_session_id": upload_session_id}
        for field_name, value in raw_row.items():
            record_kwargs[field_name] = _cast_value(field_name, value)
        casted_rows.append(record_kwargs)

    hashes = [_content_hash(business_id, dataset_type, row) for row in casted_rows]

    existing_hashes: set[str] = set()
    if hashes:
        existing_hashes = {
            h
            for (h,) in db.query(model_cls.content_hash)
            .filter(model_cls.business_id == business_id, model_cls.content_hash.in_(hashes))
            .all()
        }

    seen_in_batch: set[str] = set()
    duplicate_count = 0
    min_date: date_type | None = None
    max_date: date_type | None = None
    created_rows = []

    for offset, (record_kwargs, content_hash) in enumerate(zip(casted_rows, hashes)):
        if content_hash in existing_hashes or content_hash in seen_in_batch:
            duplicate_count += 1
        seen_in_batch.add(content_hash)
        record_kwargs["content_hash"] = content_hash

        if dataset_type == "sales":
            record_kwargs["raw_row_number"] = start_row_number + offset
            customer = resolve_customer(
                db, business_id, record_kwargs.get("customer_name"), phone=record_kwargs.get("customer_phone")
            )
            if customer is not None:
                record_kwargs["customer_id"] = customer.id
        elif dataset_type == "inventory":
            supplier = resolve_supplier(db, business_id, record_kwargs.get("supplier"))
            if supplier is not None:
                record_kwargs["supplier_id"] = supplier.id

        record = model_cls(**record_kwargs)
        db.add(record)
        created_rows.append(record)

        if date_field:
            row_date = record_kwargs.get(date_field)
            if row_date is not None:
                min_date = row_date if min_date is None else min(min_date, row_date)
                max_date = row_date if max_date is None else max(max_date, row_date)

    # Tests and callers use autoflush=False sessions (see
    # docs/decisions.md's autoflush bug entry) -- flush explicitly so the
    # rows just added are visible to any query the caller runs immediately
    # after (e.g. reading them back by content_hash, or a DatasetProfile
    # date-range query keyed off this same batch), and so each record's
    # id (assigned by the default=uuid.uuid4 column default) is populated.
    db.flush()

    return IngestSummary(
        inserted=len(casted_rows),
        created_ids=[row.id for row in created_rows],
        date_range_start=min_date,
        date_range_end=max_date,
        duplicate_count=duplicate_count,
    )
