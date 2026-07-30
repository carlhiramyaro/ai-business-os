from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents import run_finance_agent, run_inventory_agent, run_manager_agent, run_marketing_agent, run_operations_agent


class ReportState(TypedDict, total=False):
    finance_metrics: dict
    inventory_metrics: dict
    marketing_metrics: dict
    operations_metrics: dict
    forecast_metrics: dict
    finance_result: dict
    inventory_result: dict
    marketing_result: dict
    operations_result: dict
    manager_result: dict
    finance_timing: dict
    inventory_timing: dict
    marketing_timing: dict
    operations_timing: dict
    manager_timing: dict


def _timed(agent_name: str, runner):
    """Wraps an agent runner so its node also records start/end/duration --
    needed per-agent since agent_runs (erd.md) has one row per agent, each
    with its own executionTimeMs."""

    def node(state: ReportState) -> dict:
        started_at = datetime.now(timezone.utc)
        result = runner(state[f"{agent_name}_metrics"])
        completed_at = datetime.now(timezone.utc)
        return {
            f"{agent_name}_result": result,
            f"{agent_name}_timing": {
                "started_at": started_at,
                "completed_at": completed_at,
                "execution_time_ms": int((completed_at - started_at).total_seconds() * 1000),
            },
        }

    return node


def _manager_node(state: ReportState) -> dict:
    started_at = datetime.now(timezone.utc)
    findings = {
        "finance": state["finance_result"],
        "inventory": state["inventory_result"],
        "marketing": state["marketing_result"],
        "operations": state["operations_result"],
        "forecast": state["forecast_metrics"],
    }
    result = run_manager_agent(findings)
    completed_at = datetime.now(timezone.utc)
    return {
        "manager_result": result,
        "manager_timing": {
            "started_at": started_at,
            "completed_at": completed_at,
            "execution_time_ms": int((completed_at - started_at).total_seconds() * 1000),
        },
    }


def build_report_graph():
    graph = StateGraph(ReportState)
    graph.add_node("finance", _timed("finance", run_finance_agent))
    graph.add_node("inventory", _timed("inventory", run_inventory_agent))
    graph.add_node("marketing", _timed("marketing", run_marketing_agent))
    graph.add_node("operations", _timed("operations", run_operations_agent))
    graph.add_node("manager", _manager_node)

    # Fan-out: the four analysts have no dependency on each other, so
    # LangGraph runs them within the same superstep (concurrently) --
    # fan-in: "manager" only runs once all four have written their state.
    graph.add_edge(START, "finance")
    graph.add_edge(START, "inventory")
    graph.add_edge(START, "marketing")
    graph.add_edge(START, "operations")
    graph.add_edge("finance", "manager")
    graph.add_edge("inventory", "manager")
    graph.add_edge("marketing", "manager")
    graph.add_edge("operations", "manager")
    graph.add_edge("manager", END)

    return graph.compile()


report_graph = build_report_graph()
