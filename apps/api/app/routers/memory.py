from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.business_facts import delete_fact
from app.database import get_db
from app.dependencies import get_owned_business, get_owned_fact
from app.models import Business, BusinessFact
from app.schemas.memory import BusinessFactSummary

router = APIRouter(prefix="/api/v1/businesses/{business_id}/memory", tags=["memory"])


@router.get("/", response_model=list[BusinessFactSummary])
def list_facts(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    return (
        db.query(BusinessFact)
        .filter(BusinessFact.business_id == business.id)
        .order_by(BusinessFact.created_at.desc())
        .all()
    )


@router.delete("/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fact_endpoint(fact: BusinessFact = Depends(get_owned_fact), db: Session = Depends(get_db)):
    delete_fact(db, fact)
    db.commit()
