from collections import Counter, defaultdict


def _to_float(value) -> float:
    return float(value) if value is not None else 0.0


def compute_finance_metrics(sale_totals: list, expense_amounts: list, expense_categories: list) -> dict:
    total_revenue = sum((_to_float(v) for v in sale_totals), 0.0)
    total_expenses = sum((_to_float(v) for v in expense_amounts), 0.0)
    profit = total_revenue - total_expenses
    profit_margin = round(profit / total_revenue, 4) if total_revenue else None

    expense_breakdown: dict[str, float] = defaultdict(float)
    for category, amount in zip(expense_categories, expense_amounts):
        expense_breakdown[category or "uncategorized"] += _to_float(amount)

    return {
        "totalRevenue": round(total_revenue, 2),
        "totalExpenses": round(total_expenses, 2),
        "profit": round(profit, 2),
        "profitMargin": profit_margin,
        "expenseBreakdown": dict(expense_breakdown),
    }


def compute_inventory_metrics(inventory_items: list[dict]) -> dict:
    """Each item: {"productName", "quantity", "reorderLevel", "costPrice"}."""
    low_stock = [
        {"productName": item["productName"], "quantity": item["quantity"], "reorderLevel": item["reorderLevel"]}
        for item in inventory_items
        if item["quantity"] is not None and item["reorderLevel"] is not None and item["quantity"] <= item["reorderLevel"]
    ]
    total_inventory_value = sum(
        (_to_float(item["quantity"]) * _to_float(item["costPrice"]) for item in inventory_items), 0.0
    )

    return {
        "lowStockItems": low_stock,
        "totalInventoryValue": round(total_inventory_value, 2),
        "totalInventoryItems": len(inventory_items),
    }


def compute_marketing_metrics(sales: list[dict]) -> dict:
    """Each row: {"productName", "totalAmount", "paymentMethod"}."""
    revenue_by_product: dict[str, float] = defaultdict(float)
    for row in sales:
        if row["productName"]:
            revenue_by_product[row["productName"]] += _to_float(row["totalAmount"])

    top_products = sorted(revenue_by_product.items(), key=lambda item: item[1], reverse=True)[:3]
    payment_method_counts = Counter(row["paymentMethod"] for row in sales if row["paymentMethod"])

    return {
        "topProducts": [{"productName": name, "totalRevenue": round(total, 2)} for name, total in top_products],
        "paymentMethodBreakdown": dict(payment_method_counts),
    }


def compute_operations_metrics(sales: list[dict]) -> dict:
    """Each row: {"quantity", "discount", "saleDate"}."""
    discounts = [_to_float(row["discount"]) for row in sales if row["discount"] is not None]
    average_discount = round(sum(discounts) / len(discounts), 2) if discounts else 0.0
    sale_dates = [row["saleDate"] for row in sales if row["saleDate"] is not None]

    return {
        "totalOrders": len(sales),
        "averageDiscount": average_discount,
        "dateRangeStart": min(sale_dates).isoformat() if sale_dates else None,
        "dateRangeEnd": max(sale_dates).isoformat() if sale_dates else None,
    }
