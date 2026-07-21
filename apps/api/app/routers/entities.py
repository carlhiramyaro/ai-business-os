from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business
from app.models import Business, Customer, Supplier
from app.schemas.entities import CustomerItem, SupplierItem

router = APIRouter(prefix="/api/v1/businesses/{business_id}", tags=["entities"])


@router.get("/customers", response_model=list[CustomerItem])
def list_customers(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    customers = (
        db.query(Customer).filter(Customer.business_id == business.id).order_by(Customer.name).all()
    )
    return [CustomerItem(id=c.id, name=c.name, phone=c.phone, created_at=c.created_at) for c in customers]


@router.get("/suppliers", response_model=list[SupplierItem])
def list_suppliers(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    suppliers = (
        db.query(Supplier).filter(Supplier.business_id == business.id).order_by(Supplier.name).all()
    )
    return [SupplierItem(id=s.id, name=s.name, created_at=s.created_at) for s in suppliers]
