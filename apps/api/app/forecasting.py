"""Deterministic forecasting v1 (roadmap.md v0.4) -- interpretable
statistical baselines (moving average, unit-velocity depletion), no trained
models and no LLM involvement. Feeds the Manager agent (app/agents.py)
computed numbers to explain, rather than letting it invent a forecast --
same "LLMs narrate, never produce the numbers" split as report_metrics.py.
"""

from collections import defaultdict
from datetime import date, timedelta

DEFAULT_REVENUE_WINDOW_DAYS = 7
DEFAULT_HORIZON_DAYS = 7


def _to_float(value) -> float:
    return float(value) if value is not None else 0.0


def forecast_revenue(
    daily_points: list[dict],
    *,
    window: int = DEFAULT_REVENUE_WINDOW_DAYS,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> dict:
    """daily_points: [{"date": date, "revenue": float}], any order, at most
    one entry per date. Projects the trailing `window`-day average revenue
    forward `horizon_days`. weekOverWeekPct compares the last 7 days'
    average against the prior 7 days' average -- None when fewer than 14
    days of (dated) data exist, since the comparison isn't meaningful yet."""
    points = sorted(daily_points, key=lambda p: p["date"])

    if not points:
        return {
            "averageDailyRevenue": 0.0,
            "projectedRevenue": 0.0,
            "horizonDays": horizon_days,
            "weekOverWeekPct": None,
            "basisDays": 0,
        }

    revenue_by_date = {p["date"]: _to_float(p["revenue"]) for p in points}
    basis_days = min(window, len(points))
    trailing_dates = [p["date"] for p in points[-basis_days:]]
    trailing_revenue = [revenue_by_date[d] for d in trailing_dates]
    average_daily_revenue = sum(trailing_revenue) / basis_days

    week_over_week_pct = None
    if len(points) >= 14:
        last_7 = [revenue_by_date[p["date"]] for p in points[-7:]]
        prior_7 = [revenue_by_date[p["date"]] for p in points[-14:-7]]
        last_avg = sum(last_7) / 7
        prior_avg = sum(prior_7) / 7
        week_over_week_pct = round((last_avg - prior_avg) / prior_avg, 4) if prior_avg else None

    return {
        "averageDailyRevenue": round(average_daily_revenue, 2),
        "projectedRevenue": round(average_daily_revenue * horizon_days, 2),
        "horizonDays": horizon_days,
        "weekOverWeekPct": week_over_week_pct,
        "basisDays": basis_days,
    }


def forecast_stock_depletion(
    inventory_items: list[dict],
    sales_velocity: dict[str, float],
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> dict:
    """inventory_items: [{"productName", "quantity"}]. sales_velocity:
    {productName: average units sold per day over the report period}.
    daysToStockout is None for products with no/zero velocity -- current
    stock doesn't project to deplete, so there's nothing to divide by."""
    items = []
    for item in inventory_items:
        product_name = item["productName"]
        quantity = _to_float(item["quantity"])
        velocity = _to_float(sales_velocity.get(product_name))
        days_to_stockout = round(quantity / velocity, 1) if velocity > 0 else None
        items.append(
            {
                "productName": product_name,
                "quantity": item["quantity"],
                "dailyVelocity": round(velocity, 2),
                "daysToStockout": days_to_stockout,
            }
        )

    items.sort(key=lambda i: (i["daysToStockout"] is None, i["daysToStockout"]))
    at_risk = [i for i in items if i["daysToStockout"] is not None and i["daysToStockout"] <= horizon_days]

    return {"horizonDays": horizon_days, "items": items, "atRisk": at_risk}


def sales_velocity_by_product(sales_rows: list[dict], period_start: date, period_end: date) -> dict[str, float]:
    """sales_rows: [{"productName", "quantity"}]. Average units/day per
    product over the report's day span -- shared by report_generation.py so
    forecast_stock_depletion always sees a velocity computed the same way."""
    day_span = (period_end - period_start).days + 1
    if day_span <= 0:
        return {}

    totals: dict[str, float] = defaultdict(float)
    for row in sales_rows:
        product_name = row["productName"]
        if product_name:
            totals[product_name] += _to_float(row["quantity"])

    return {product_name: total / day_span for product_name, total in totals.items()}


def daily_revenue_points(sales_rows: list[dict]) -> list[dict]:
    """sales_rows: [{"saleDate", "totalAmount"}]. Collapses to one
    {"date", "revenue"} point per distinct sale_date -- rows with a NULL
    saleDate can't be bucketed and are excluded, same caveat as
    report_metrics.py's date-range handling."""
    totals: dict[date, float] = defaultdict(float)
    for row in sales_rows:
        sale_date = row["saleDate"]
        if sale_date is not None:
            totals[sale_date] += _to_float(row["totalAmount"])

    return [{"date": d, "revenue": revenue} for d, revenue in sorted(totals.items())]
