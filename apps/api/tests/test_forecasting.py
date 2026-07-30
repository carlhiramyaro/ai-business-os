from datetime import date, timedelta
from decimal import Decimal

from app.forecasting import (
    daily_revenue_points,
    forecast_revenue,
    forecast_stock_depletion,
    sales_velocity_by_product,
)


def _dates(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def test_forecast_revenue_empty_input():
    result = forecast_revenue([])
    assert result == {
        "averageDailyRevenue": 0.0,
        "projectedRevenue": 0.0,
        "horizonDays": 7,
        "weekOverWeekPct": None,
        "basisDays": 0,
    }


def test_forecast_revenue_projects_trailing_average():
    start = date(2026, 1, 1)
    points = [{"date": d, "revenue": 100.0} for d in _dates(start, 5)]
    result = forecast_revenue(points, window=7, horizon_days=7)
    # Only 5 days of data exist, so basisDays clamps to 5, not the requested window.
    assert result["basisDays"] == 5
    assert result["averageDailyRevenue"] == 100.0
    assert result["projectedRevenue"] == 700.0
    assert result["weekOverWeekPct"] is None


def test_forecast_revenue_week_over_week_trend():
    start = date(2026, 1, 1)
    prior_week = [{"date": d, "revenue": 100.0} for d in _dates(start, 7)]
    last_week = [{"date": d, "revenue": 150.0} for d in _dates(start + timedelta(days=7), 7)]
    result = forecast_revenue(prior_week + last_week)
    assert result["weekOverWeekPct"] == round((150.0 - 100.0) / 100.0, 4)


def test_forecast_revenue_week_over_week_decline():
    start = date(2026, 1, 1)
    prior_week = [{"date": d, "revenue": 200.0} for d in _dates(start, 7)]
    last_week = [{"date": d, "revenue": 100.0} for d in _dates(start + timedelta(days=7), 7)]
    result = forecast_revenue(prior_week + last_week)
    assert result["weekOverWeekPct"] == -0.5


def test_forecast_stock_depletion_computes_days_to_stockout():
    items = [{"productName": "Rice", "quantity": 20}, {"productName": "Beans", "quantity": 100}]
    velocity = {"Rice": 5.0, "Beans": 2.0}
    result = forecast_stock_depletion(items, velocity, horizon_days=7)
    by_name = {i["productName"]: i for i in result["items"]}
    assert by_name["Rice"]["daysToStockout"] == 4.0
    assert by_name["Beans"]["daysToStockout"] == 50.0
    # Sorted soonest-first.
    assert [i["productName"] for i in result["items"]] == ["Rice", "Beans"]
    assert [i["productName"] for i in result["atRisk"]] == ["Rice"]


def test_forecast_stock_depletion_zero_velocity_excluded_from_at_risk():
    items = [{"productName": "Oil", "quantity": 10}]
    result = forecast_stock_depletion(items, sales_velocity={}, horizon_days=7)
    assert result["items"][0]["daysToStockout"] is None
    assert result["atRisk"] == []


def test_forecast_stock_depletion_empty_input():
    result = forecast_stock_depletion([], {}, horizon_days=7)
    assert result == {"horizonDays": 7, "items": [], "atRisk": []}


def test_sales_velocity_by_product():
    rows = [
        {"productName": "Rice", "quantity": 10},
        {"productName": "Rice", "quantity": 4},
        {"productName": "Beans", "quantity": 7},
    ]
    velocity = sales_velocity_by_product(rows, date(2026, 1, 1), date(2026, 1, 7))
    assert velocity == {"Rice": 2.0, "Beans": 1.0}


def test_sales_velocity_by_product_ignores_missing_product_name():
    rows = [{"productName": None, "quantity": 5}]
    velocity = sales_velocity_by_product(rows, date(2026, 1, 1), date(2026, 1, 7))
    assert velocity == {}


def test_daily_revenue_points_collapses_by_date_and_skips_nulls():
    rows = [
        {"saleDate": date(2026, 1, 1), "totalAmount": Decimal("100.00")},
        {"saleDate": date(2026, 1, 1), "totalAmount": Decimal("50.00")},
        {"saleDate": None, "totalAmount": Decimal("999.00")},
    ]
    points = daily_revenue_points(rows)
    assert points == [{"date": date(2026, 1, 1), "revenue": 150.0}]
