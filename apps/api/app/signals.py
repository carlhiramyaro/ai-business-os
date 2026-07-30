"""Deterministic anomaly/trend detectors (roadmap.md v0.4 slice 2) -- pure
functions, no DB, no LLM. Each returns a signal dict (or None/[] when
nothing crosses its threshold) carrying an "anchor" string that
app/insights_generation.py folds into a dedup fingerprint together with
business_id + insight_type -- so a signal that's still true on the next
scheduled run doesn't create a duplicate insight, the same idempotency idea
as app/ingestion.py's content_hash.
"""

from datetime import date

DEFAULT_REVENUE_TREND_THRESHOLD = 0.2  # 20% week-over-week move
DEFAULT_EXPENSE_SPIKE_THRESHOLD = 0.3  # 30% over the category's baseline
DEFAULT_INACTIVE_CUSTOMER_THRESHOLD = 1  # at least one lapsed customer triggers a digest


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def detect_revenue_trend(
    recent_7d_revenue: float,
    prior_7d_revenue: float,
    period_end: date,
    *,
    threshold: float = DEFAULT_REVENUE_TREND_THRESHOLD,
) -> dict | None:
    """recent_7d_revenue/prior_7d_revenue: total revenue over the last 7
    days vs. the 7 days before that. No signal when there's no prior-week
    revenue to compare against (nothing to divide by, not "flat")."""
    if not prior_7d_revenue:
        return None

    pct_change = round((recent_7d_revenue - prior_7d_revenue) / prior_7d_revenue, 4)
    if abs(pct_change) < threshold:
        return None

    severity = "info" if pct_change > 0 else ("critical" if pct_change <= -0.3 else "warning")

    return {
        "type": "revenue_trend",
        "severity": severity,
        "anchor": _iso_week(period_end),
        "metrics": {
            "recentWeekRevenue": round(recent_7d_revenue, 2),
            "priorWeekRevenue": round(prior_7d_revenue, 2),
            "pctChange": pct_change,
        },
    }


def detect_expense_spike(
    category_totals_recent: dict[str, float],
    category_totals_baseline: dict[str, float],
    period_end: date,
    *,
    threshold: float = DEFAULT_EXPENSE_SPIKE_THRESHOLD,
) -> list[dict]:
    """category_totals_*: {category: total spend} over equal-length recent
    vs. baseline windows. One signal per category whose recent spend
    exceeds its baseline by >= threshold; categories with no baseline spend
    are skipped -- there's nothing to compare a spike against."""
    signals = []
    for category, recent in category_totals_recent.items():
        baseline = category_totals_baseline.get(category, 0.0)
        if not baseline:
            continue
        pct_change = round((recent - baseline) / baseline, 4)
        if pct_change < threshold:
            continue
        severity = "critical" if pct_change >= 0.75 else "warning"
        signals.append(
            {
                "type": "expense_spike",
                "severity": severity,
                "anchor": f"{category}:{_iso_week(period_end)}",
                "metrics": {
                    "category": category,
                    "recentAmount": round(recent, 2),
                    "baselineAmount": round(baseline, 2),
                    "pctChange": pct_change,
                },
            }
        )
    return signals


def detect_stock_depletion(stock_forecast: dict) -> list[dict]:
    """stock_forecast: app.forecasting.forecast_stock_depletion's output --
    one signal per at-risk product, anchored on product name so the same
    risk doesn't re-fire every scheduled run while it persists."""
    signals = []
    for item in stock_forecast["atRisk"]:
        severity = "critical" if item["daysToStockout"] <= 3 else "warning"
        signals.append(
            {
                "type": "stock_depletion",
                "severity": severity,
                "anchor": item["productName"],
                "metrics": item,
            }
        )
    return signals


def detect_inactive_customers(
    inactive_result: dict,
    period_end: date,
    *,
    threshold: int = DEFAULT_INACTIVE_CUSTOMER_THRESHOLD,
) -> dict | None:
    """inactive_result: app.chat_tools.get_inactive_customers's output. One
    digest signal (not one per customer) when at least `threshold`
    customers are lapsed, anchored per ISO week so the digest doesn't
    repeat every day the same customers stay inactive."""
    customers = inactive_result["customers"]
    if len(customers) < threshold:
        return None

    return {
        "type": "inactive_customers",
        "severity": "warning",
        "anchor": _iso_week(period_end),
        "metrics": {
            "inactiveSinceDays": inactive_result["inactiveSinceDays"],
            "count": len(customers),
            "customers": customers,
        },
    }
