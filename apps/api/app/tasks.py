import hashlib
import os
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.column_mapping import resolve_column_mapping
from app.database import SessionLocal
from app.document_extraction import extract_document
from app.ingestion import RECORD_FIELD_MAP, ingest_rows
from app.insights_generation import run_business_analysis
from app.models import Business, ColumnMapping, DatasetProfile, DocumentExtraction, Report, UploadSession
from app.report_generation import generate_report, run_report_generation
from app.storage import document_key_for, download_fileobj, key_for

load_dotenv()

MAPPING_CONFIDENCE_THRESHOLD = float(os.getenv("MAPPING_CONFIDENCE_THRESHOLD", "0.8"))


def _header_set_hash(headers) -> str:
    return hashlib.sha256("|".join(sorted(headers)).encode()).hexdigest()


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

        period_start = period_end = None

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
