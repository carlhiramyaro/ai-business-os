from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business
from app.ingestion import compute_sale_total, ingest_rows
from app.models import Business, UploadSession
from app.schemas.entries import EntryCreateResponse, ExpenseEntry, InventoryEntry, SaleEntry

router = APIRouter(prefix="/api/v1/businesses/{business_id}/entries", tags=["entries"])

# Quick manual entry (v0.3, roadmap.md "Continuous data"): record one sale/
# expense/inventory row in a few taps, no CSV round trip. Each submission is
# a one-row batch through the same app.ingestion.ingest_rows boundary the
# CSV pipeline uses -- casting, entity resolution, and dedup-hash detection
# all happen exactly once, there, regardless of source. See
# docs/decisions.md [2026-07-24].
#
# No auto-report generation here (unlike a completed CSV upload): a report
# per tap would be absurd at this cadence. Reports stay on-demand or
# CSV-upload-triggered; date-range reports already pick up these rows
# automatically since they query sales/expenses/inventory directly, not by
# upload_session_id.


def _create_manual_session(db: Session, business: Business) -> UploadSession:
    session = UploadSession(
        business_id=business.id,
        source_type="manual",
        status="COMPLETED",
        processing_started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.flush()
    return session


@router.post("/sales", response_model=EntryCreateResponse, status_code=status.HTTP_201_CREATED)
def create_sale_entry(
    payload: SaleEntry,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
):
    row = payload.model_dump()

    if row["total_amount"] is None:
        row["total_amount"] = compute_sale_total(row["quantity"], row["unit_price"], row["discount"])

    session = _create_manual_session(db, business)
    summary = ingest_rows(db, business.id, session.id, "sales", [row])
    db.commit()

    return EntryCreateResponse(id=summary.created_ids[0], duplicate_warning=summary.duplicate_count > 0)


@router.post("/expenses", response_model=EntryCreateResponse, status_code=status.HTTP_201_CREATED)
def create_expense_entry(
    payload: ExpenseEntry,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
):
    session = _create_manual_session(db, business)
    summary = ingest_rows(db, business.id, session.id, "expenses", [payload.model_dump()])
    db.commit()

    return EntryCreateResponse(id=summary.created_ids[0], duplicate_warning=summary.duplicate_count > 0)


@router.post("/inventory", response_model=EntryCreateResponse, status_code=status.HTTP_201_CREATED)
def create_inventory_entry(
    payload: InventoryEntry,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
):
    session = _create_manual_session(db, business)
    summary = ingest_rows(db, business.id, session.id, "inventory", [payload.model_dump()])
    db.commit()

    return EntryCreateResponse(id=summary.created_ids[0], duplicate_warning=summary.duplicate_count > 0)
