from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_owned_business
from app.models import Business, User
from app.schemas.business import BusinessCreate, BusinessResponse, BusinessUpdate

router = APIRouter(prefix="/api/v1/businesses", tags=["businesses"])


@router.post("/", response_model=BusinessResponse, status_code=status.HTTP_201_CREATED)
def create_business(
    payload: BusinessCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    business = Business(owner_id=current_user.id, **payload.model_dump())
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


@router.get("/", response_model=list[BusinessResponse])
def list_businesses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(Business).filter(Business.owner_id == current_user.id).all()


@router.get("/{business_id}", response_model=BusinessResponse)
def get_business(business: Business = Depends(get_owned_business)):
    return business


@router.patch("/{business_id}", response_model=BusinessResponse)
def update_business(
    payload: BusinessUpdate,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(business, field, value)
    db.commit()
    db.refresh(business)
    return business


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business(
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
):
    db.delete(business)
    db.commit()
