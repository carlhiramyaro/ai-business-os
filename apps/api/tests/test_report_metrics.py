from decimal import Decimal

from app.report_metrics import (
    compute_finance_metrics,
    compute_inventory_metrics,
    compute_marketing_metrics,
    compute_operations_metrics,
)


def test_compute_finance_metrics():
    result = compute_finance_metrics(
        sale_totals=[Decimal("100.00"), Decimal("50.00")],
        expense_amounts=[Decimal("30.00"), Decimal("20.00")],
        expense_categories=["Utilities", "Rent"],
    )
    assert result == {
        "totalRevenue": 150.0,
        "totalExpenses": 50.0,
        "profit": 100.0,
        "profitMargin": round(100.0 / 150.0, 4),
        "expenseBreakdown": {"Utilities": 30.0, "Rent": 20.0},
    }


def test_compute_finance_metrics_zero_revenue_has_no_margin():
    result = compute_finance_metrics(sale_totals=[], expense_amounts=[Decimal("10")], expense_categories=["Rent"])
    assert result["profitMargin"] is None


def test_compute_inventory_metrics_flags_low_stock():
    items = [
        {"productName": "Rice", "quantity": 5, "reorderLevel": 10, "costPrice": Decimal("2.0")},
        {"productName": "Beans", "quantity": 50, "reorderLevel": 10, "costPrice": Decimal("1.0")},
    ]
    result = compute_inventory_metrics(items)
    assert result["lowStockItems"] == [{"productName": "Rice", "quantity": 5, "reorderLevel": 10}]
    assert result["totalInventoryValue"] == 5 * 2.0 + 50 * 1.0
    assert result["totalInventoryItems"] == 2


def test_compute_marketing_metrics_ranks_top_products():
    sales = [
        {"productName": "Rice", "totalAmount": Decimal("100"), "paymentMethod": "Cash"},
        {"productName": "Beans", "totalAmount": Decimal("50"), "paymentMethod": "Card"},
        {"productName": "Rice", "totalAmount": Decimal("25"), "paymentMethod": "Cash"},
    ]
    result = compute_marketing_metrics(sales)
    assert result["topProducts"][0] == {"productName": "Rice", "totalRevenue": 125.0}
    assert result["paymentMethodBreakdown"] == {"Cash": 2, "Card": 1}


def test_compute_operations_metrics():
    import datetime

    sales = [
        {"quantity": 5, "discount": Decimal("1.0"), "saleDate": datetime.date(2026, 1, 1)},
        {"quantity": 3, "discount": Decimal("2.0"), "saleDate": datetime.date(2026, 1, 3)},
    ]
    result = compute_operations_metrics(sales)
    assert result["totalOrders"] == 2
    assert result["averageDiscount"] == 1.5
    assert result["dateRangeStart"] == "2026-01-01"
    assert result["dateRangeEnd"] == "2026-01-03"
