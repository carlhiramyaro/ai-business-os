"""v0.4 slice 2 (roadmap.md "Proactive intelligence") orchestration --
analogous to app/report_generation.py, but for the scheduled/on-demand
insights feed instead of the on-upload report. Detectors (app/signals.py)
compute the numbers and decide what's noteworthy; app.agents.narrate_insight
only narrates. Fingerprint-based dedup means a signal that's still true on
the next run doesn't create a second insight -- see docs/decisions.md.
"""

import hashlib
import uuid
from datetime import date, timedelta

from langfuse import observe, propagate_attributes
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents import narrate_insight
from app.chat_tools import get_inactive_customers
from app.forecasting import forecast_stock_depletion, sales_velocity_by_product
from app.insight_delivery import deliver_immediate
from app.models import Business, Expense, Insight, Inventory, Sale
from app.retrieval import retrieve_relevant_chunks
from app.signals import (
    detect_expense_spike,
    detect_inactive_customers,
    detect_revenue_trend,
    detect_stock_depletion,
)

# v0.4 slice 3: one short search phrase per insight_type, used to pull
# relevant business_facts (app/business_facts.py) into the narration --
# static and deterministic rather than an extra LLM call to formulate a
# query, since the four types are fixed and known in advance.
QUERY_BY_INSIGHT_TYPE = {
    "revenue_trend": "revenue trends, seasonality, sales patterns",
    "expense_spike": "expense patterns, cost changes, spending categories",
    "stock_depletion": "inventory, restocking, supplier reliability, product demand",
    "inactive_customers": "customer behavior, purchasing patterns, loyalty",
}
RELEVANT_FACTS_TOP_K = 3

# Trailing window sales/inventory velocity is computed over -- long enough
# to smooth out day-to-day noise, short enough to reflect current selling
# pace rather than the whole history.
VELOCITY_WINDOW_DAYS = 30
STOCKOUT_HORIZON_DAYS = 7
INACTIVE_CUSTOMER_LOOKBACK_DAYS = 90
INACTIVE_CUSTOMER_LIMIT = 25


def _revenue_between(db: Session, business_id, start: date, end: date) -> float:
    total = (
        db.query(func.coalesce(func.sum(Sale.total_amount), 0))
        .filter(Sale.business_id == business_id, Sale.sale_date.between(start, end))
        .scalar()
    )
    return float(total)


def _expense_category_totals(db: Session, business_id, start: date, end: date) -> dict[str, float]:
    rows = (
        db.query(Expense.category, func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.business_id == business_id, Expense.expense_date.between(start, end))
        .group_by(Expense.category)
        .all()
    )
    return {(category or "uncategorized"): float(total) for category, total in rows}


def _fingerprint(business_id, insight_type: str, anchor: str) -> str:
    return hashlib.sha256(f"{business_id}|{insight_type}|{anchor}".encode()).hexdigest()


def _collect_signals(db: Session, business: Business, today: date) -> list[dict]:
    recent_start, recent_end = today - timedelta(days=6), today
    prior_start, prior_end = today - timedelta(days=13), today - timedelta(days=7)
    velocity_start = today - timedelta(days=VELOCITY_WINDOW_DAYS - 1)

    signals: list[dict] = []

    recent_revenue = _revenue_between(db, business.id, recent_start, recent_end)
    prior_revenue = _revenue_between(db, business.id, prior_start, prior_end)
    revenue_signal = detect_revenue_trend(recent_revenue, prior_revenue, today)
    if revenue_signal:
        signals.append(revenue_signal)

    recent_expenses = _expense_category_totals(db, business.id, recent_start, recent_end)
    baseline_expenses = _expense_category_totals(db, business.id, prior_start, prior_end)
    signals.extend(detect_expense_spike(recent_expenses, baseline_expenses, today))

    velocity_sales = [
        {"productName": row.product_name, "quantity": row.quantity}
        for row in db.query(Sale.product_name, Sale.quantity).filter(
            Sale.business_id == business.id, Sale.sale_date.between(velocity_start, today)
        )
    ]
    velocity = sales_velocity_by_product(velocity_sales, velocity_start, today)
    inventory_items = [
        {"productName": row.product_name, "quantity": row.quantity}
        for row in db.query(Inventory).filter(Inventory.business_id == business.id)
    ]
    stock_forecast = forecast_stock_depletion(inventory_items, velocity, horizon_days=STOCKOUT_HORIZON_DAYS)
    signals.extend(detect_stock_depletion(stock_forecast))

    inactive_result = get_inactive_customers(
        db, business.id, days=INACTIVE_CUSTOMER_LOOKBACK_DAYS, limit=INACTIVE_CUSTOMER_LIMIT, today=today
    )
    inactive_signal = detect_inactive_customers(inactive_result, today)
    if inactive_signal:
        signals.append(inactive_signal)

    return signals


@observe(name="business_analysis")
def run_business_analysis(db: Session, business: Business, today: date | None = None) -> int:
    """Detects signals, narrates and persists the new ones (skipping any
    whose fingerprint already exists for this business), and returns the
    count of insights created."""
    # No persisted "analysis run" row to key off of (unlike report_id for
    # reports) -- one uuid4 per call groups this run's narrate_insight
    # calls (N per run, unbounded) and retrieval embeddings into one trace.
    with propagate_attributes(session_id=str(uuid.uuid4()), metadata={"business_id": str(business.id)}):
        return _run_business_analysis_body(db, business, today)


def _run_business_analysis_body(db: Session, business: Business, today: date | None) -> int:
    today = today or date.today()
    signals = _collect_signals(db, business, today)
    if not signals:
        return 0

    fingerprints = [_fingerprint(business.id, signal["type"], signal["anchor"]) for signal in signals]
    existing = {
        row.fingerprint
        for row in db.query(Insight.fingerprint).filter(
            Insight.business_id == business.id, Insight.fingerprint.in_(fingerprints)
        )
    }

    created_insights: list[Insight] = []
    for signal, fingerprint in zip(signals, fingerprints):
        if fingerprint in existing:
            continue
        relevant_facts = retrieve_relevant_chunks(
            db,
            business.id,
            QUERY_BY_INSIGHT_TYPE[signal["type"]],
            top_k=RELEVANT_FACTS_TOP_K,
            source_types=["business_fact"],
        )
        narration = narrate_insight(signal, relevant_facts=relevant_facts)
        insight = Insight(
            business_id=business.id,
            insight_type=signal["type"],
            severity=signal["severity"],
            title=narration["title"],
            body=narration["body"],
            metrics=signal["metrics"],
            fingerprint=fingerprint,
            period_start=today - timedelta(days=6),
            period_end=today,
        )
        db.add(insight)
        created_insights.append(insight)

    db.commit()

    # v0.6 slice 2: push a bundled WhatsApp message to every "immediate"
    # identity linked to this business -- one message for this whole run,
    # not one per insight, so several signals detected at once don't
    # flood the owner's phone. No-op if nothing new was created or no
    # identity is set to "immediate". See docs/decisions.md.
    deliver_immediate(db, business, created_insights)

    return len(created_insights)
