import json
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.embedding_generation import generate_embeddings_for_report
from app.forecasting import daily_revenue_points, forecast_revenue, forecast_stock_depletion, sales_velocity_by_product
from app.models import AgentOutput, AgentRun, Business, Expense, Inventory, Report, ReportSection, Sale
from app.report_graph import report_graph
from app.report_metrics import (
    compute_finance_metrics,
    compute_inventory_metrics,
    compute_marketing_metrics,
    compute_operations_metrics,
)

AGENT_NAMES = ("finance", "inventory", "marketing", "operations")


def _write_agent_run(db: Session, business: Business, report: Report, agent_name: str, timing: dict, output: str, confidence) -> None:
    agent_run = AgentRun(
        business_id=business.id,
        report_id=report.id,
        agent_name=agent_name,
        status="completed",
        execution_time_ms=timing["execution_time_ms"],
        started_at=timing["started_at"],
        completed_at=timing["completed_at"],
    )
    db.add(agent_run)
    db.flush()
    db.add(AgentOutput(agent_run_id=agent_run.id, output=output, confidence=confidence))


def _create_pending_report(
    db: Session,
    business: Business,
    period_start: date,
    period_end: date,
    upload_session_id: uuid.UUID | None = None,
) -> Report:
    report = Report(
        business_id=business.id,
        upload_session_id=upload_session_id,
        period_start=period_start,
        period_end=period_end,
        status="PENDING",
    )
    db.add(report)
    db.flush()  # assigns report.id
    return report


def _mark_report_failed(db: Session, report: Report) -> None:
    db.rollback()
    report.status = "FAILED"
    db.commit()


def _populate_report(db: Session, business: Business, report: Report) -> None:
    # The caller's session may have pending (unflushed) sales/inventory/
    # expenses inserts from the same transaction -- SessionLocal has
    # autoflush=False, so they wouldn't otherwise be visible to the
    # queries below.
    db.flush()

    sales = (
        db.query(Sale)
        .filter(Sale.business_id == business.id, Sale.sale_date.between(report.period_start, report.period_end))
        .all()
    )
    expenses = (
        db.query(Expense)
        .filter(
            Expense.business_id == business.id,
            Expense.expense_date.between(report.period_start, report.period_end),
        )
        .all()
    )
    # Inventory is a point-in-time snapshot, not a time series -- no date column
    # to filter on, so every report includes all of the business's current stock.
    inventory_rows = db.query(Inventory).filter(Inventory.business_id == business.id).all()

    finance_metrics = compute_finance_metrics(
        sale_totals=[s.total_amount for s in sales],
        expense_amounts=[e.amount for e in expenses],
        expense_categories=[e.category for e in expenses],
    )
    inventory_metrics = compute_inventory_metrics(
        [
            {"productName": i.product_name, "quantity": i.quantity, "reorderLevel": i.reorder_level, "costPrice": i.cost_price}
            for i in inventory_rows
        ]
    )
    marketing_metrics = compute_marketing_metrics(
        [{"productName": s.product_name, "totalAmount": s.total_amount, "paymentMethod": s.payment_method} for s in sales]
    )
    operations_metrics = compute_operations_metrics(
        [{"quantity": s.quantity, "discount": s.discount, "saleDate": s.sale_date} for s in sales]
    )

    # Deterministic forecast inputs (roadmap.md v0.4 slice 1) -- built from
    # the sales/inventory rows already fetched above, no new queries. The
    # manager agent explains these numbers rather than inventing a forecast.
    velocity = sales_velocity_by_product(
        [{"productName": s.product_name, "quantity": s.quantity} for s in sales],
        report.period_start,
        report.period_end,
    )
    forecast_metrics = {
        "revenue": forecast_revenue(
            daily_revenue_points([{"saleDate": s.sale_date, "totalAmount": s.total_amount} for s in sales])
        ),
        "stockDepletion": forecast_stock_depletion(
            [{"productName": i.product_name, "quantity": i.quantity} for i in inventory_rows], velocity
        ),
    }

    final_state = report_graph.invoke(
        {
            "finance_metrics": finance_metrics,
            "inventory_metrics": inventory_metrics,
            "marketing_metrics": marketing_metrics,
            "operations_metrics": operations_metrics,
            "forecast_metrics": forecast_metrics,
        }
    )

    for agent_name in AGENT_NAMES:
        result = final_state[f"{agent_name}_result"]
        _write_agent_run(
            db,
            business,
            report,
            agent_name,
            final_state[f"{agent_name}_timing"],
            output=result["findings"],
            confidence=result.get("confidence"),
        )

    manager_result = final_state["manager_result"]
    _write_agent_run(
        db,
        business,
        report,
        "manager",
        final_state["manager_timing"],
        output=json.dumps(manager_result),
        confidence=None,
    )

    report.executive_summary = manager_result["summary"]
    report.forecast = manager_result["forecast"]

    for section_type, items in (
        ("risk", manager_result.get("risks", [])),
        ("opportunity", manager_result.get("opportunities", [])),
        ("action_item", manager_result.get("actionPlan", [])),
    ):
        for order_index, content in enumerate(items):
            db.add(ReportSection(report_id=report.id, section_type=section_type, content=content, order_index=order_index))

    report.status = "COMPLETED"
    db.flush()  # report_sections need ids before generate_embeddings_for_report queries them
    generate_embeddings_for_report(db, business, report)

    db.commit()


def generate_report(
    db: Session,
    business: Business,
    period_start: date,
    period_end: date,
    upload_session_id: uuid.UUID | None = None,
) -> Report:
    """Synchronous end-to-end generation used by finalize_upload_task (the
    auto path triggered by a completed upload)."""
    report = _create_pending_report(db, business, period_start, period_end, upload_session_id)
    try:
        _populate_report(db, business, report)
    except Exception:
        _mark_report_failed(db, report)
        raise
    return report


def run_report_generation(db: Session, business: Business, report: Report) -> None:
    """Entry point for the async manual-trigger path (app.tasks.generate_report_task)
    -- the report row already exists with status='PENDING' and a period set, created
    synchronously by the router so the client has an id to poll immediately."""
    try:
        _populate_report(db, business, report)
    except Exception:
        _mark_report_failed(db, report)
        raise
