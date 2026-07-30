from datetime import date

from app.signals import (
    detect_expense_spike,
    detect_inactive_customers,
    detect_revenue_trend,
    detect_stock_depletion,
)

PERIOD_END = date(2026, 1, 21)  # 2026-W04


def test_detect_revenue_trend_no_prior_revenue_is_none():
    assert detect_revenue_trend(100.0, 0.0, PERIOD_END) is None


def test_detect_revenue_trend_below_threshold_is_none():
    # +10% move, default threshold is 20%.
    assert detect_revenue_trend(110.0, 100.0, PERIOD_END) is None


def test_detect_revenue_trend_decline_is_critical_below_30pct():
    result = detect_revenue_trend(50.0, 100.0, PERIOD_END)
    assert result["type"] == "revenue_trend"
    assert result["severity"] == "critical"
    assert result["anchor"] == "2026-W04"
    assert result["metrics"] == {"recentWeekRevenue": 50.0, "priorWeekRevenue": 100.0, "pctChange": -0.5}


def test_detect_revenue_trend_moderate_decline_is_warning():
    result = detect_revenue_trend(75.0, 100.0, PERIOD_END)
    assert result["severity"] == "warning"


def test_detect_revenue_trend_growth_is_info():
    result = detect_revenue_trend(150.0, 100.0, PERIOD_END)
    assert result["severity"] == "info"
    assert result["metrics"]["pctChange"] == 0.5


def test_detect_expense_spike_flags_only_categories_over_threshold():
    recent = {"Rent": 100.0, "Utilities": 140.0, "Supplies": 50.0}
    baseline = {"Rent": 100.0, "Utilities": 100.0, "Supplies": 0.0}
    signals = detect_expense_spike(recent, baseline, PERIOD_END)
    assert len(signals) == 1
    assert signals[0]["metrics"]["category"] == "Utilities"
    assert signals[0]["metrics"]["pctChange"] == 0.4
    assert signals[0]["anchor"] == "Utilities:2026-W04"


def test_detect_expense_spike_severity_critical_at_75pct():
    recent = {"Rent": 200.0}
    baseline = {"Rent": 100.0}
    signals = detect_expense_spike(recent, baseline, PERIOD_END)
    assert signals[0]["severity"] == "critical"


def test_detect_expense_spike_zero_baseline_skipped():
    signals = detect_expense_spike({"NewCategory": 500.0}, {}, PERIOD_END)
    assert signals == []


def test_detect_stock_depletion_one_signal_per_at_risk_item():
    stock_forecast = {
        "horizonDays": 7,
        "items": [{"productName": "Rice", "quantity": 30, "dailyVelocity": 20.0, "daysToStockout": 1.5}],
        "atRisk": [{"productName": "Rice", "quantity": 30, "dailyVelocity": 20.0, "daysToStockout": 1.5}],
    }
    signals = detect_stock_depletion(stock_forecast)
    assert len(signals) == 1
    assert signals[0]["type"] == "stock_depletion"
    assert signals[0]["severity"] == "critical"
    assert signals[0]["anchor"] == "Rice"


def test_detect_stock_depletion_empty_at_risk_is_empty():
    assert detect_stock_depletion({"horizonDays": 7, "items": [], "atRisk": []}) == []


def test_detect_inactive_customers_below_threshold_is_none():
    result = detect_inactive_customers({"inactiveSinceDays": 90, "customers": []}, PERIOD_END)
    assert result is None


def test_detect_inactive_customers_digest():
    inactive_result = {
        "inactiveSinceDays": 90,
        "customers": [{"customerName": "Jane", "customerPhone": None, "lastPurchase": "2025-01-01", "totalSpent": 50.0}],
    }
    result = detect_inactive_customers(inactive_result, PERIOD_END)
    assert result["type"] == "inactive_customers"
    assert result["anchor"] == "2026-W04"
    assert result["metrics"]["count"] == 1
