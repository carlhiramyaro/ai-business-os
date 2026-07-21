import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.column_mapping import resolve_column_mapping
from app.database import SessionLocal
from app.entities import resolve_customer, resolve_supplier
from app.models import Business, ColumnMapping, DatasetProfile, Expense, Inventory, Report, Sale, UploadSession
from app.report_generation import generate_report, run_report_generation
from app.storage import download_fileobj, key_for

load_dotenv()

MAPPING_CONFIDENCE_THRESHOLD = float(os.getenv("MAPPING_CONFIDENCE_THRESHOLD", "0.8"))

DATASET_MODELS = {"sales": Sale, "inventory": Inventory, "expenses": Expense}

# canonical (camelCase, matches erd.md/endpoints.md) -> ORM attribute (snake_case)
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

DATE_TARGET_FIELD = {"sales": "saleDate", "expenses": "expenseDate", "inventory": None}


def _header_set_hash(headers) -> str:
    return hashlib.sha256("|".join(sorted(headers)).encode()).hexdigest()


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


def _mark_failed(db: Session, upload_session: UploadSession) -> None:
    db.rollback()
    upload_session.status = "FAILED"
    upload_session.completed_at = datetime.now(timezone.utc)
    db.commit()


@celery_app.task(name="run_column_mapping")
def run_column_mapping_task(upload_session_id: str):
    db: Session = SessionLocal()
    upload_session = None
    try:
        upload_session = db.get(UploadSession, upload_session_id)
        if upload_session is None:
            return

        upload_session.processing_started_at = datetime.now(timezone.utc)
        db.commit()

        any_needs_review = False

        for dataset_type in ("sales", "inventory", "expenses"):
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

        for dataset_type in ("sales", "inventory", "expenses"):
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
            target_to_header = {m.target_field: m.source_column_name for m in mappings}

            model_cls = DATASET_MODELS[dataset_type]

            for row_number, row in enumerate(df.itertuples(index=False), start=1):
                record_kwargs = {
                    "business_id": upload_session.business_id,
                    "upload_session_id": upload_session.id,
                }
                for header, value in zip(df.columns, row):
                    field_name = header_to_field.get(header)
                    if field_name:
                        record_kwargs[field_name] = _cast_value(field_name, value)

                if dataset_type == "sales":
                    record_kwargs["raw_row_number"] = row_number
                    customer = resolve_customer(
                        db,
                        upload_session.business_id,
                        record_kwargs.get("customer_name"),
                        phone=record_kwargs.get("customer_phone"),
                    )
                    if customer is not None:
                        record_kwargs["customer_id"] = customer.id
                elif dataset_type == "inventory":
                    supplier = resolve_supplier(db, upload_session.business_id, record_kwargs.get("supplier"))
                    if supplier is not None:
                        record_kwargs["supplier_id"] = supplier.id

                db.add(model_cls(**record_kwargs))

            date_target = DATE_TARGET_FIELD[dataset_type]
            date_header = target_to_header.get(date_target) if date_target else None
            date_values = (
                pd.to_datetime(df[date_header], errors="coerce").dropna() if date_header else None
            )

            db.add(
                DatasetProfile(
                    upload_session_id=upload_session.id,
                    dataset_type=dataset_type,
                    total_rows=len(df),
                    duplicate_rows=int(df.duplicated().sum()),
                    missing_values=int(df.isna().sum().sum()),
                    date_range_start=date_values.min().date() if date_values is not None and not date_values.empty else None,
                    date_range_end=date_values.max().date() if date_values is not None and not date_values.empty else None,
                )
            )

        db.flush()  # DatasetProfile rows added in the loop above need to be visible to this query
        profiles = (
            db.query(DatasetProfile)
            .filter(
                DatasetProfile.upload_session_id == upload_session.id,
                DatasetProfile.dataset_type.in_(("sales", "expenses")),
            )
            .all()
        )
        starts = [p.date_range_start for p in profiles if p.date_range_start is not None]
        ends = [p.date_range_end for p in profiles if p.date_range_end is not None]

        if starts and ends:
            period_start, period_end = min(starts), max(ends)
        else:
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
