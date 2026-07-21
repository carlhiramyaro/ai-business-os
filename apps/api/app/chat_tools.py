"""Chat's SQL tool catalog.

A fixed set of parameterized, business-scoped query functions the chat
agent can call, plus their function-calling schemas. The LLM only ever
picks a tool name and arguments — it never writes SQL. Every function
takes (db, business_id, ...) and filters by business_id, per the
multi-tenancy rule.

Date-range arguments are optional; when omitted, a tool covers all of the
business's data. When a range IS given, rows with a NULL sale_date /
expense_date fall outside it and are excluded — the same caveat as
period-based reports (see decisions.md [2026-07-20]).
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Customer, Expense, Inventory, Sale
from app.report_metrics import compute_finance_metrics, compute_inventory_metrics

MAX_RESULT_LIMIT = 25


class ToolArgumentError(ValueError):
    """Invalid arguments from the model — fed back to it as the tool result
    so it can retry, rather than crashing the request."""


def _parse_optional_date(arguments: dict, field: str) -> date | None:
    value = arguments.get(field)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolArgumentError(f"{field} must be an ISO date (YYYY-MM-DD), got: {value!r}")


def _parse_limit(arguments: dict, default: int = 5) -> int:
    value = arguments.get("limit", default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ToolArgumentError(f"limit must be a positive integer, got: {value!r}")
    return min(value, MAX_RESULT_LIMIT)


def _parse_choice(arguments: dict, field: str, choices: tuple[str, ...], default: str) -> str:
    value = arguments.get(field, default)
    if value not in choices:
        raise ToolArgumentError(f"{field} must be one of {choices}, got: {value!r}")
    return value


def _date_range_filters(column, period_start: date | None, period_end: date | None) -> list:
    filters = []
    if period_start is not None:
        filters.append(column >= period_start)
    if period_end is not None:
        filters.append(column <= period_end)
    return filters


def get_financial_summary(
    db: Session, business_id: uuid.UUID, period_start: date | None = None, period_end: date | None = None
) -> dict:
    sale_totals = [
        row.total_amount
        for row in db.query(Sale.total_amount)
        .filter(Sale.business_id == business_id, *_date_range_filters(Sale.sale_date, period_start, period_end))
        .all()
    ]
    expense_rows = (
        db.query(Expense.amount, Expense.category)
        .filter(
            Expense.business_id == business_id,
            *_date_range_filters(Expense.expense_date, period_start, period_end),
        )
        .all()
    )
    return compute_finance_metrics(
        sale_totals, [row.amount for row in expense_rows], [row.category for row in expense_rows]
    )


def get_sales_trend(
    db: Session,
    business_id: uuid.UUID,
    interval: str = "month",
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict:
    """Revenue and order counts bucketed by day/week/month. Rows with a
    NULL sale_date can't be bucketed and are always excluded here."""
    bucket = func.date_trunc(interval, Sale.sale_date)
    rows = (
        db.query(
            bucket.label("period"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("revenue"),
            func.count(Sale.id).label("orders"),
        )
        .filter(
            Sale.business_id == business_id,
            Sale.sale_date.isnot(None),
            *_date_range_filters(Sale.sale_date, period_start, period_end),
        )
        .group_by(bucket)
        .order_by(bucket)
        .all()
    )
    return {
        "interval": interval,
        "points": [
            {"period": row.period.date().isoformat(), "revenue": round(float(row.revenue), 2), "orders": row.orders}
            for row in rows
        ],
    }


def get_top_products(
    db: Session,
    business_id: uuid.UUID,
    metric: str = "revenue",
    limit: int = 5,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict:
    measure = (
        func.coalesce(func.sum(Sale.total_amount), 0)
        if metric == "revenue"
        else func.coalesce(func.sum(Sale.quantity), 0)
    )
    rows = (
        db.query(Sale.product_name, measure.label("value"), func.count(Sale.id).label("orders"))
        .filter(
            Sale.business_id == business_id,
            Sale.product_name.isnot(None),
            *_date_range_filters(Sale.sale_date, period_start, period_end),
        )
        .group_by(Sale.product_name)
        .order_by(measure.desc())
        .limit(limit)
        .all()
    )
    return {
        "metric": metric,
        "products": [
            {"productName": row.product_name, metric: round(float(row.value), 2), "orders": row.orders}
            for row in rows
        ],
    }


def get_top_customers(
    db: Session,
    business_id: uuid.UUID,
    limit: int = 5,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict:
    """Groups by the resolved Customer entity (set at ingestion), so
    casing/spacing variants of one name count as one customer."""
    rows = (
        db.query(
            Customer.name,
            Customer.phone,
            func.coalesce(func.sum(Sale.total_amount), 0).label("total_spent"),
            func.count(Sale.id).label("orders"),
            func.max(Sale.sale_date).label("last_purchase"),
        )
        .select_from(Sale)
        .join(Customer, Sale.customer_id == Customer.id)
        .filter(
            Sale.business_id == business_id,
            *_date_range_filters(Sale.sale_date, period_start, period_end),
        )
        .group_by(Customer.id, Customer.name, Customer.phone)
        .order_by(func.coalesce(func.sum(Sale.total_amount), 0).desc())
        .limit(limit)
        .all()
    )
    return {
        "customers": [
            {
                "customerName": row.name,
                "customerPhone": row.phone,
                "totalSpent": round(float(row.total_spent), 2),
                "orders": row.orders,
                "lastPurchase": row.last_purchase.isoformat() if row.last_purchase else None,
            }
            for row in rows
        ]
    }


def get_inactive_customers(
    db: Session, business_id: uuid.UUID, days: int = 90, limit: int = 10, today: date | None = None
) -> dict:
    """Customers whose most recent (dated) purchase is more than `days` ago.
    `today` is injectable for deterministic tests; callers never expose it
    to the model."""
    cutoff = (today or date.today()) - timedelta(days=days)
    rows = (
        db.query(
            Customer.name,
            Customer.phone,
            func.max(Sale.sale_date).label("last_purchase"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("total_spent"),
        )
        .select_from(Sale)
        .join(Customer, Sale.customer_id == Customer.id)
        .filter(
            Sale.business_id == business_id,
            Sale.sale_date.isnot(None),
        )
        .group_by(Customer.id, Customer.name, Customer.phone)
        .having(func.max(Sale.sale_date) < cutoff)
        .order_by(func.max(Sale.sale_date))
        .limit(limit)
        .all()
    )
    return {
        "inactiveSinceDays": days,
        "customers": [
            {
                "customerName": row.name,
                "customerPhone": row.phone,
                "lastPurchase": row.last_purchase.isoformat(),
                "totalSpent": round(float(row.total_spent), 2),
            }
            for row in rows
        ],
    }


def get_inventory_status(db: Session, business_id: uuid.UUID) -> dict:
    items = [
        {
            "productName": row.product_name,
            "quantity": row.quantity,
            "reorderLevel": row.reorder_level,
            "costPrice": row.cost_price,
        }
        for row in db.query(Inventory).filter(Inventory.business_id == business_id).all()
    ]
    return compute_inventory_metrics(items)


def execute_tool(db: Session, business_id: uuid.UUID, name: str, arguments: dict) -> dict:
    """Dispatch a model-chosen tool call. Arguments arrive as parsed JSON
    from the model and are validated here — bad values raise
    ToolArgumentError instead of reaching a query."""
    if name == "get_financial_summary":
        return get_financial_summary(
            db,
            business_id,
            period_start=_parse_optional_date(arguments, "period_start"),
            period_end=_parse_optional_date(arguments, "period_end"),
        )
    if name == "get_sales_trend":
        return get_sales_trend(
            db,
            business_id,
            interval=_parse_choice(arguments, "interval", ("day", "week", "month"), default="month"),
            period_start=_parse_optional_date(arguments, "period_start"),
            period_end=_parse_optional_date(arguments, "period_end"),
        )
    if name == "get_top_products":
        return get_top_products(
            db,
            business_id,
            metric=_parse_choice(arguments, "metric", ("revenue", "quantity"), default="revenue"),
            limit=_parse_limit(arguments),
            period_start=_parse_optional_date(arguments, "period_start"),
            period_end=_parse_optional_date(arguments, "period_end"),
        )
    if name == "get_top_customers":
        return get_top_customers(
            db,
            business_id,
            limit=_parse_limit(arguments),
            period_start=_parse_optional_date(arguments, "period_start"),
            period_end=_parse_optional_date(arguments, "period_end"),
        )
    if name == "get_inactive_customers":
        days = arguments.get("days", 90)
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            raise ToolArgumentError(f"days must be a positive integer, got: {days!r}")
        return get_inactive_customers(db, business_id, days=days, limit=_parse_limit(arguments, default=10))
    if name == "get_inventory_status":
        return get_inventory_status(db, business_id)
    raise ToolArgumentError(f"Unknown tool: {name}")


_DATE_RANGE_PROPERTIES = {
    "period_start": {"type": "string", "description": "Inclusive start date, ISO format YYYY-MM-DD. Omit for all time."},
    "period_end": {"type": "string", "description": "Inclusive end date, ISO format YYYY-MM-DD. Omit for all time."},
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_financial_summary",
            "description": (
                "Exact revenue, expenses, profit, profit margin, and expense breakdown by "
                "category for this business, optionally restricted to a date range. Use this "
                "for any question about money totals — never estimate figures yourself."
            ),
            "parameters": {"type": "object", "properties": _DATE_RANGE_PROPERTIES, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sales_trend",
            "description": (
                "Revenue and order counts over time, bucketed by day, week, or month. Use this "
                "to see whether sales are growing or declining, or to compare periods."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "interval": {"type": "string", "enum": ["day", "week", "month"], "description": "Bucket size."},
                    **_DATE_RANGE_PROPERTIES,
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_products",
            "description": "Best-selling products ranked by revenue or by units sold, optionally within a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "enum": ["revenue", "quantity"], "description": "Ranking measure."},
                    "limit": {"type": "integer", "description": "How many products to return (default 5, max 25)."},
                    **_DATE_RANGE_PROPERTIES,
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_customers",
            "description": (
                "Customers ranked by total spend, with order counts and last purchase date, "
                "optionally within a date range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "How many customers to return (default 5, max 25)."},
                    **_DATE_RANGE_PROPERTIES,
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inactive_customers",
            "description": (
                "Customers who have not purchased in the last N days — e.g. 'who hasn't bought "
                "in three months?' uses days=90."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Inactivity threshold in days (default 90)."},
                    "limit": {"type": "integer", "description": "How many customers to return (default 10, max 25)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory_status",
            "description": (
                "Current inventory: items at or below their reorder level (low stock), total "
                "inventory value, and item count. Use for stock/reorder questions."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]
