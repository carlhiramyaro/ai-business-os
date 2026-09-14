import uuid
from decimal import Decimal

import pytest

from app.entities import resolve_product
from app.inventory import (
    get_current_stock,
    get_pack_relationship,
    record_recount,
    record_repack,
    record_stock_movement,
)
from app.models import Business, PackRelationship, Product, User


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


def _link(db_session, business, pack_product, unit_product, units_per_pack):
    relationship = PackRelationship(
        business_id=business.id,
        pack_product_id=pack_product.id,
        unit_product_id=unit_product.id,
        units_per_pack=units_per_pack,
    )
    db_session.add(relationship)
    db_session.flush()
    return relationship


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


def test_record_stock_movement_supports_fractional_quantity(db_session):
    """A loose product sold by weight (2.3 kg) needs a fractional
    quantity -- Decimal end to end, not int. See docs/decisions.md
    [2026-09-14]."""
    business = _seed_business(db_session)
    product = _product(db_session, business, base_unit="kg")
    record_stock_movement(db_session, business.id, product, "10.5", reason="restock")

    record_stock_movement(db_session, business.id, product, "2.3", reason="sale")

    assert get_current_stock(db_session, product.id) == Decimal("8.2")


def test_record_stock_movement_direction_comes_from_reason_not_quantity_sign(db_session):
    """A caller passing a negative quantity for a 'sale' must not double
    the sign and accidentally restock -- direction comes from `reason`
    alone, so abs() is applied regardless of the sign passed in."""
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


def test_record_stock_movement_repack_reason_raises_use_record_repack(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)

    with pytest.raises(ValueError):
        record_stock_movement(db_session, business.id, product, 1, reason="repack")


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


# --- record_repack / get_pack_relationship ----------------------------------


def test_get_pack_relationship_is_none_when_undeclared(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)
    assert get_pack_relationship(db_session, product.id) is None


def test_record_repack_break_moves_stock_from_pack_to_unit(db_session):
    business = _seed_business(db_session)
    case = _product(db_session, business, name="Coke Case")
    can = _product(db_session, business, name="Coke Can")
    _link(db_session, business, case, can, units_per_pack=24)
    record_stock_movement(db_session, business.id, case, 5, reason="restock")

    pack_movement, unit_movement = record_repack(db_session, business.id, case, 1, direction="break")

    assert pack_movement.quantity_delta == -1
    assert unit_movement.quantity_delta == 24
    assert get_current_stock(db_session, case.id) == 4
    assert get_current_stock(db_session, can.id) == 24


def test_record_repack_assemble_moves_stock_from_unit_to_pack(db_session):
    business = _seed_business(db_session)
    case = _product(db_session, business, name="Coke Case")
    can = _product(db_session, business, name="Coke Can")
    _link(db_session, business, case, can, units_per_pack=24)
    record_stock_movement(db_session, business.id, can, 24, reason="restock")

    pack_movement, unit_movement = record_repack(db_session, business.id, case, 1, direction="assemble")

    assert pack_movement.quantity_delta == 1
    assert unit_movement.quantity_delta == -24
    assert get_current_stock(db_session, case.id) == 1
    assert get_current_stock(db_session, can.id) == 0


def test_record_repack_movements_share_one_source_id(db_session):
    business = _seed_business(db_session)
    case = _product(db_session, business, name="Coke Case")
    can = _product(db_session, business, name="Coke Can")
    _link(db_session, business, case, can, units_per_pack=24)

    pack_movement, unit_movement = record_repack(db_session, business.id, case, 1, direction="break")

    assert pack_movement.source_id == unit_movement.source_id
    assert pack_movement.reason == unit_movement.reason == "repack"


def test_record_repack_supports_fractional_units_per_pack(db_session):
    """A 10.5 kg box of meat, sold either by the box or by the kg."""
    business = _seed_business(db_session)
    box = _product(db_session, business, name="Meat Box")
    loose = _product(db_session, business, name="Meat (loose)", base_unit="kg")
    _link(db_session, business, box, loose, units_per_pack="10.5")
    record_stock_movement(db_session, business.id, box, 1, reason="restock")

    record_repack(db_session, business.id, box, 1, direction="break")
    record_stock_movement(db_session, business.id, loose, "2.3", reason="sale")

    assert get_current_stock(db_session, box.id) == 0
    assert get_current_stock(db_session, loose.id) == Decimal("8.2")


def test_record_repack_without_declared_relationship_raises(db_session):
    business = _seed_business(db_session)
    product = _product(db_session, business)

    with pytest.raises(ValueError):
        record_repack(db_session, business.id, product, 1, direction="break")


def test_record_repack_invalid_direction_raises(db_session):
    business = _seed_business(db_session)
    case = _product(db_session, business, name="Coke Case")
    can = _product(db_session, business, name="Coke Can")
    _link(db_session, business, case, can, units_per_pack=24)

    with pytest.raises(ValueError):
        record_repack(db_session, business.id, case, 1, direction="explode")


def test_record_repack_allows_going_negative_same_as_a_sale(db_session):
    """Breaking more cases than you have goes negative -- consistent with
    every other movement here (an oversold sale isn't blocked either),
    not a new exception for repack."""
    business = _seed_business(db_session)
    case = _product(db_session, business, name="Coke Case")
    can = _product(db_session, business, name="Coke Can")
    _link(db_session, business, case, can, units_per_pack=24)

    record_repack(db_session, business.id, case, 3, direction="break")

    assert get_current_stock(db_session, case.id) == -3
    assert get_current_stock(db_session, can.id) == 72
