from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business, get_owned_product
from app.inventory import get_current_stock, list_current_stock, record_recount, record_stock_movement
from app.models import Business, Product, ProductUnit
from app.schemas.products import (
    ProductItem,
    ProductUnitItem,
    ProductUnitRequest,
    ProductUpdate,
    StockAdjustmentRequest,
    StockAdjustmentResponse,
)

router = APIRouter(prefix="/api/v1/businesses/{business_id}/products", tags=["products"])

# v0.7 slice 3 (roadmap.md "Inventory depth"): the API surface behind the
# /inventory page -- list current stock, edit a product's own fields
# (sku/category/baseUnit/reorderLevel/prices -- never quantity, which is
# ledger-derived, not settable directly), record a restock/recount/loss/
# damage adjustment, and declare a non-base unit (e.g. "carton" = 24
# "piece") for real unit conversion. See docs/decisions.md [2026-09-14].


def _low_stock(quantity: int, reorder_level: int | None) -> bool:
    return reorder_level is not None and quantity <= reorder_level


def _to_item(item: dict) -> ProductItem:
    return ProductItem(
        id=item["productId"],
        name=item["productName"],
        sku=item["sku"],
        category=item["category"],
        quantity=item["quantity"],
        base_unit=item["baseUnit"],
        reorder_level=item["reorderLevel"],
        cost_price=item["costPrice"],
        selling_price=item["sellingPrice"],
        low_stock=_low_stock(item["quantity"], item["reorderLevel"]),
    )


@router.get("/", response_model=list[ProductItem])
def list_products(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    return [_to_item(item) for item in list_current_stock(db, business.id)]


@router.patch("/{product_id}", response_model=ProductItem)
def update_product(
    payload: ProductUpdate,
    product: Product = Depends(get_owned_product),
    db: Session = Depends(get_db),
):
    # Same last-non-empty-value-wins rule resolve_product already applies
    # to these fields when a sale/inventory entry supplies them -- omitted
    # (unset) fields are left alone, and an explicit null is a no-op too
    # (there's no "clear the sku" affordance yet, matching how resolve_product
    # already treats a blank sku as "nothing new to record").
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return _to_item(
        {
            "productId": product.id,
            "productName": product.name,
            "sku": product.sku,
            "category": product.category,
            "quantity": get_current_stock(db, product.id),
            "baseUnit": product.base_unit,
            "reorderLevel": product.reorder_level,
            "costPrice": product.cost_price,
            "sellingPrice": product.selling_price,
        }
    )


@router.post(
    "/{product_id}/stock-movements",
    response_model=StockAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_stock_adjustment(
    payload: StockAdjustmentRequest,
    business: Business = Depends(get_owned_business),
    product: Product = Depends(get_owned_product),
    db: Session = Depends(get_db),
):
    try:
        if payload.reason == "recount":
            movement = record_recount(
                db,
                business.id,
                product,
                payload.quantity,
                unit_name=payload.unit_name,
                source_type="manual",
                note=payload.note,
            )
        else:
            movement = record_stock_movement(
                db,
                business.id,
                product,
                payload.quantity,
                reason=payload.reason,
                unit_name=payload.unit_name,
                source_type="manual",
                note=payload.note,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    db.commit()
    return StockAdjustmentResponse(
        id=movement.id,
        product_id=product.id,
        quantity_delta=movement.quantity_delta,
        reason=movement.reason,
        current_stock=get_current_stock(db, product.id),
    )


@router.post("/{product_id}/units", response_model=ProductUnitItem, status_code=status.HTTP_201_CREATED)
def declare_product_unit(
    payload: ProductUnitRequest,
    product: Product = Depends(get_owned_product),
    db: Session = Depends(get_db),
):
    """Get-or-update, not always-insert: redeclaring an existing unit name
    corrects its conversion factor rather than erroring or duplicating,
    matching the unique constraint on (product_id, unit_name)."""
    unit_name = payload.unit_name.strip()
    product_unit = (
        db.query(ProductUnit)
        .filter(ProductUnit.product_id == product.id, ProductUnit.unit_name == unit_name)
        .one_or_none()
    )
    if product_unit is None:
        product_unit = ProductUnit(
            product_id=product.id, unit_name=unit_name, conversion_to_base=payload.conversion_to_base
        )
        db.add(product_unit)
    else:
        product_unit.conversion_to_base = payload.conversion_to_base
    db.commit()
    db.refresh(product_unit)
    return product_unit
