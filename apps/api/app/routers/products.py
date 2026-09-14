from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_business, get_owned_product
from app.entities import suggest_sku
from app.inventory import get_current_stock, get_pack_relationship, list_current_stock, record_recount, record_repack, record_stock_movement
from app.models import Business, PackRelationship, Product
from app.schemas.products import (
    PackRelationshipItem,
    PackRelationshipRequest,
    ProductItem,
    ProductUpdate,
    RepackRequest,
    RepackResponse,
    StockAdjustmentRequest,
    StockAdjustmentResponse,
    SuggestedSkuResponse,
)

router = APIRouter(prefix="/api/v1/businesses/{business_id}/products", tags=["products"])

# v0.7 slice 3 (roadmap.md "Inventory depth"): the API surface behind the
# /inventory page -- list current stock, edit a product's own fields
# (sku/category/baseUnit/reorderLevel/prices -- never quantity, which is
# ledger-derived, not settable directly), record a restock/recount/loss/
# damage adjustment. docs/decisions.md [2026-09-14] added pack
# relationships -- declaring that one product is a sealed pack of another
# (a case of cans) and the explicit "break"/"assemble" repack action that
# converts between them -- replacing an earlier per-transaction unit
# conversion (ProductUnit) that turned out to be a confusing setup flow.


def _low_stock(quantity, reorder_level) -> bool:
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


@router.get("/{product_id}/suggested-sku", response_model=SuggestedSkuResponse)
def get_suggested_sku(
    business: Business = Depends(get_owned_business),
    product: Product = Depends(get_owned_product),
    db: Session = Depends(get_db),
):
    """A proposal, not an assignment -- the owner sees this as a button on
    the Edit form and can accept, edit, or ignore it; nothing here writes
    to the product. See app.entities.suggest_sku."""
    existing_skus = {
        sku
        for (sku,) in db.query(Product.sku).filter(Product.business_id == business.id, Product.sku.isnot(None))
    }
    existing_skus.discard(product.sku)  # don't disambiguate against the product's own current sku
    return SuggestedSkuResponse(sku=suggest_sku(product.name, existing_skus))


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
    if payload.reason == "recount":
        movement = record_recount(
            db, business.id, product, payload.quantity, source_type="manual", note=payload.note
        )
    else:
        movement = record_stock_movement(
            db, business.id, product, payload.quantity, reason=payload.reason, source_type="manual", note=payload.note
        )

    db.commit()
    return StockAdjustmentResponse(
        id=movement.id,
        product_id=product.id,
        quantity_delta=movement.quantity_delta,
        reason=movement.reason,
        current_stock=get_current_stock(db, product.id),
    )


@router.get("/{product_id}/pack-relationship", response_model=PackRelationshipItem | None)
def get_product_pack_relationship(product: Product = Depends(get_owned_product), db: Session = Depends(get_db)):
    """None (not 404) when this product isn't a pack of anything -- that's
    the normal, expected state for most products, not an error."""
    relationship = get_pack_relationship(db, product.id)
    if relationship is None:
        return None
    unit_product = db.get(Product, relationship.unit_product_id)
    return PackRelationshipItem(
        id=relationship.id,
        pack_product_id=relationship.pack_product_id,
        unit_product_id=relationship.unit_product_id,
        unit_product_name=unit_product.name,
        units_per_pack=relationship.units_per_pack,
    )


@router.post(
    "/{product_id}/pack-relationship",
    response_model=PackRelationshipItem,
    status_code=status.HTTP_201_CREATED,
)
def declare_pack_relationship(
    payload: PackRelationshipRequest,
    business: Business = Depends(get_owned_business),
    product: Product = Depends(get_owned_product),
    db: Session = Depends(get_db),
):
    """Get-or-update, not always-insert: redeclaring corrects the
    unitsPerPack factor or which product it points at, rather than
    erroring or duplicating -- matches the unique constraint on
    pack_product_id (a product is a pack of at most one other product)."""
    unit_product = db.get(Product, payload.unit_product_id)
    if unit_product is None or unit_product.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if unit_product.id == product.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A product can't be a pack of itself")

    relationship = get_pack_relationship(db, product.id)
    if relationship is None:
        relationship = PackRelationship(
            business_id=business.id,
            pack_product_id=product.id,
            unit_product_id=unit_product.id,
            units_per_pack=payload.units_per_pack,
        )
        db.add(relationship)
    else:
        relationship.unit_product_id = unit_product.id
        relationship.units_per_pack = payload.units_per_pack
    db.commit()
    db.refresh(relationship)
    return PackRelationshipItem(
        id=relationship.id,
        pack_product_id=relationship.pack_product_id,
        unit_product_id=relationship.unit_product_id,
        unit_product_name=unit_product.name,
        units_per_pack=relationship.units_per_pack,
    )


@router.post("/{product_id}/repack", response_model=RepackResponse, status_code=status.HTTP_201_CREATED)
def create_repack(
    payload: RepackRequest,
    business: Business = Depends(get_owned_business),
    product: Product = Depends(get_owned_product),
    db: Session = Depends(get_db),
):
    try:
        pack_movement, unit_movement = record_repack(
            db, business.id, product, payload.quantity, direction=payload.direction, note=payload.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    db.commit()
    return RepackResponse(
        pack_product_id=pack_movement.product_id,
        pack_current_stock=get_current_stock(db, pack_movement.product_id),
        unit_product_id=unit_movement.product_id,
        unit_current_stock=get_current_stock(db, unit_movement.product_id),
    )
