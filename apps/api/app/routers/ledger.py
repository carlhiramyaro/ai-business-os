from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business
from app.models import Business, Expense, Sale
from app.schemas.ledger import ExpenseListItem, SaleListItem

# v0.7 slice 3 (roadmap.md "Inventory depth"): plain read-only list views,
# closing the "I can only see my own data by asking chat" gap for sales
# and expenses (the /inventory page + app/routers/products.py close it
# for inventory). Deliberately simple: no filtering beyond pagination, no
# editing -- see docs/decisions.md [2026-09-14].
router = APIRouter(prefix="/api/v1/businesses/{business_id}", tags=["ledger"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@router.get("/sales", response_model=list[SaleListItem])
def list_sales(
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    return (
        db.query(Sale)
        .filter(Sale.business_id == business.id)
        .order_by(Sale.sale_date.desc().nullslast(), Sale.raw_row_number.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/expenses", response_model=list[ExpenseListItem])
def list_expenses(
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    return (
        db.query(Expense)
        .filter(Expense.business_id == business.id)
        .order_by(Expense.expense_date.desc().nullslast(), Expense.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
