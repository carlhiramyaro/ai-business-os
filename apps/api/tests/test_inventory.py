import uuid

import pytest

from app.entities import resolve_product
from app.inventory import (
    get_current_stock,
    record_recount,
    record_stock_movement,
    to_base_quantity,
)
from app.models import Business, Product, ProductUnit, User


def _seed_business(db_session):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()
    business = Business(owner_id=user.id, business_name="Inventory Test Co")
    db_session.add(business)
    db_session.flush()
    return business


def _product(db_session, business, name="Rice", **kwargs):
    return resolve_product(db_session, business.id, name, **kwargs)


# --- resolve_product ---------------------------------------------------


def test_resolve_product_get_or_create_dedupes_variants(db_session):
    business = _seed_business(db_session)

    first = resolve_product(db_session, business.id, "Rice")
    second = resolve_product(db_session, business.id, "rice")
    third = resolve_product(db_session, business.id, "  RICE  ")

    assert first.id == second.id == third.id
    assert first.name == "Rice"  # first-seen casing wins
    assert db_session.query(Product).filter(Product.business_id == business.id).count() == 1


def test_resolve_product_blank_name_returns_none(db_session):
    business = _seed_business(db_session)
    assert resolve_product(db_session, business.id, None) is None
    assert resolve_product(db_session, business.id, "   ") is None
    assert db_session.query(Product).count() == 0


def test_resolve_product_defaults_base_unit_to_unit(db_session):
    business = _seed_business(db_session)
    product = resolve_product(db_session, business.id, "Rice")
    assert product.base_unit == "unit"


def test_resolve_product_optional_fields_last_nonempty_wins(db_session):
    business = _seed_business(db_session)

    # sku=None at creation auto-assigns rather than staying blank (see
    # test_resolve_product_auto_assigns_sku_when_created_blank) -- this
    # test is about the OTHER optional fields' last-nonempty-wins rule.
    product = resolve_product(db_session, business.id, "Rice", sku=None, reorder_level=None)
    assert product.sku == "RICE"
    assert product.reorder_level is None

    resolve_product(db_session, business.id, "Rice", sku="RICE-5KG", reorder_level=10)
    assert product.sku == "RICE-5KG"
    assert product.reorder_level == 10

    # a later call with nothing new must not erase what's already known
    resolve_product(db_session, business.id, "Rice", sku=None, reorder_level=None)
    assert product.sku == "RICE-5KG"
    assert product.reorder_level == 10

    resolve_product(db_session, business.id, "Rice", sku="RICE-25KG")
    assert product.sku == "RICE-25KG"


def test_resolve_product_auto_assigns_sku_when_created_blank(db_session):
    business = _seed_business(db_session)
    product = resolve_product(db_session, business.id, "Palm Oil")
    assert product.sku == "PALM-OIL"


def test_resolve_product_auto_assigned_sku_disambiguates_within_business(db_session):
    business = _seed_business(db_session)
    resolve_product(db_session, business.id, "Rice", sku="RICE")
    # A different product (distinct normalized_name) whose name also
    # slugifies to "RICE" -- must not collide with the explicit one above.
    variant = resolve_product(db_session, business.id, "Rice!")
    assert variant.sku == "RICE-2"


def test_resolve_product_explicit_sku_skips_auto_assignment(db_session):
    business = _seed_business(db_session)
    product = resolve_product(db_session, business.id, "Rice", sku="CUSTOM-CODE")
    assert product.sku == "CUSTOM-CODE"


def test_resolve_product_is_scoped_per_business(db_session):
    business_a = _seed_business(db_session)
    business_b = _seed_business(db_session)

    product_a = resolve_product(db_session, business_a.id, "Rice")
    product_b = resolve_product(db_session, business_b.id, "Rice")

    assert product_a.id != product_b.id
    assert db_session.query(Product).count() == 2


# --- to_base_quantity ----------------------------------------------------


def test_to_base_quantity_passthrough_for_base_unit(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business, base_unit="piece")

    assert to_base_quantity(db_session, product, 5, None) == 5
    assert to_base_quantity(db_session, product, 5, "piece") == 5


def test_to_base_quantity_converts_declared_unit(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business, base_unit="piece")
    db_session.add(ProductUnit(product_id=product.id, unit_name="carton", conversion_to_base=24))
    db_session.flush()

    assert to_base_quantity(db_session, product, 2, "carton") == 48


def test_to_base_quantity_rounds_to_whole_base_unit(db_session):
    """Python's round() is round-half-to-even, not round-half-up -- 12.5
    rounds to 12, not 13. Documented here so a future reader isn't
    surprised; a fractional conversion factor is a rare enough input that
    banker's rounding's slight bias-cancelling behavior is an acceptable,
    deliberate default rather than something worth a custom implementation."""
    business = _seed_business(db_session)
    product = _product(db_session, business, base_unit="piece")
    db_session.add(ProductUnit(product_id=product.id, unit_name="half-carton", conversion_to_base=12.5))
    db_session.flush()

    assert to_base_quantity(db_session, product, 1, "half-carton") == 12  # round(12.5) == 12, banker's rounding


def test_to_base_quantity_unknown_unit_raises(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business, base_unit="piece")

    with pytest.raises(ValueError):
        to_base_quantity(db_session, product, 1, "carton")


# --- record_stock_movement / get_current_stock ---------------------------


def test_record_stock_movement_restock_increases_stock(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)

    record_stock_movement(db_session, business.id, product, 50, reason="restock")

    assert get_current_stock(db_session, product.id) == 50


def test_record_stock_movement_sale_decreases_stock(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)
    record_stock_movement(db_session, business.id, product, 50, reason="restock")

    record_stock_movement(db_session, business.id, product, 3, reason="sale", source_type="sale", source_id=uuid.uuid4())

    assert get_current_stock(db_session, product.id) == 47


def test_record_stock_movement_loss_and_damage_decrease_stock(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)
    record_stock_movement(db_session, business.id, product, 50, reason="restock")

    record_stock_movement(db_session, business.id, product, 2, reason="loss")
    record_stock_movement(db_session, business.id, product, 1, reason="damage")

    assert get_current_stock(db_session, product.id) == 47


def test_record_stock_movement_converts_declared_unit_before_writing(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business, base_unit="piece")
    db_session.add(ProductUnit(product_id=product.id, unit_name="carton", conversion_to_base=24))
    db_session.flush()

    record_stock_movement(db_session, business.id, product, 2, reason="restock", unit_name="carton")

    assert get_current_stock(db_session, product.id) == 48


def test_record_stock_movement_direction_comes_from_reason_not_quantity_sign(db_session):
    """A caller passing a negative quantity for a 'sale' must not double
    the sign and accidentally restock -- direction comes from `reason`
    alone, so abs() is applied to the converted quantity regardless of the
    sign passed in."""
    business = _seed_business(db_session)
    product = _product(db_session, business)
    record_stock_movement(db_session, business.id, product, 50, reason="restock")

    record_stock_movement(db_session, business.id, product, -3, reason="sale")

    assert get_current_stock(db_session, product.id) == 47


def test_record_stock_movement_unknown_reason_raises(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)

    with pytest.raises(ValueError):
        record_stock_movement(db_session, business.id, product, 1, reason="theft")


def test_record_stock_movement_recount_reason_raises_use_record_recount(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)

    with pytest.raises(ValueError):
        record_stock_movement(db_session, business.id, product, 1, reason="recount")


def test_get_current_stock_is_scoped_per_product(db_session):
    business = _seed_business(db_session)
    rice = _product(db_session, business, name="Rice")
    beans = _product(db_session, business, name="Beans")

    record_stock_movement(db_session, business.id, rice, 50, reason="restock")
    record_stock_movement(db_session, business.id, beans, 20, reason="restock")

    assert get_current_stock(db_session, rice.id) == 50
    assert get_current_stock(db_session, beans.id) == 20


def test_get_current_stock_is_zero_with_no_movements(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)
    assert get_current_stock(db_session, product.id) == 0


# --- record_recount --------------------------------------------------------


def test_record_recount_computes_positive_delta(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)
    record_stock_movement(db_session, business.id, product, 40, reason="restock")

    movement = record_recount(db_session, business.id, product, 45)

    assert movement.quantity_delta == 5
    assert get_current_stock(db_session, product.id) == 45


def test_record_recount_computes_negative_delta(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)
    record_stock_movement(db_session, business.id, product, 40, reason="restock")

    movement = record_recount(db_session, business.id, product, 33)

    assert movement.quantity_delta == -7
    assert get_current_stock(db_session, product.id) == 33


def test_record_recount_matching_reality_is_a_recorded_zero_delta_movement(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)
    record_stock_movement(db_session, business.id, product, 40, reason="restock")

    movement = record_recount(db_session, business.id, product, 40)

    assert movement.quantity_delta == 0
    assert movement.reason == "recount"
    assert get_current_stock(db_session, product.id) == 40


def test_record_recount_respects_declared_unit(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business, base_unit="piece")
    db_session.add(ProductUnit(product_id=product.id, unit_name="carton", conversion_to_base=24))
    db_session.flush()
    record_stock_movement(db_session, business.id, product, 50, reason="restock")  # 50 pieces

    movement = record_recount(db_session, business.id, product, 2, unit_name="carton")  # asserts 48 pieces

    assert movement.quantity_delta == -2
    assert get_current_stock(db_session, product.id) == 48
