"""Verifies the specific risk flagged while planning Langfuse tracing:
LangGraph's report_graph fans out to 4 analyst agents CONCURRENTLY (one
LangGraph superstep, a thread pool underneath) before fanning into the
manager node. Langfuse's tracing relies on Python contextvars (the same
mechanism OpenTelemetry's context propagation uses) to know which trace a
span belongs to -- if LangGraph's executor didn't propagate the calling
context into each concurrent thread, the four analyst spans would each
start their own orphaned trace instead of nesting under the report's one
trace, silently breaking the "group traces by request" promise
(learning-guide.md §2.5).

Confirmed by reading langgraph's installed source directly
(myenv/.../langgraph/pregel/_executor.py uses contextvars.copy_context()
before submitting each node to its thread pool) -- this test is the
regression guard for that fact, using structlog's contextvars (the same
underlying stdlib mechanism Langfuse's OTel context relies on) as a
faithful, fast, no-network stand-in for a real Langfuse client. If a
future langgraph upgrade regresses this, this test fails loudly instead of
traces silently orphaning in production.
"""

import structlog

import app.agents as agents_module
from app.report_graph import report_graph


def test_langgraph_concurrent_analysts_inherit_calling_context(monkeypatch):
    seen_context_values = []

    def fake_call_llm(system_prompt, user_content):
        seen_context_values.append(structlog.contextvars.get_contextvars().get("trace_marker"))
        if "Manager agent" in system_prompt:
            return {
                "summary": "ok",
                "risks": [],
                "opportunities": [],
                "actionPlan": [],
                "forecast": "ok",
            }
        return {"findings": "ok", "confidence": 0.9}

    monkeypatch.setattr(agents_module, "_call_llm", fake_call_llm)

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(trace_marker="report-abc123")
    try:
        report_graph.invoke(
            {
                "finance_metrics": {},
                "inventory_metrics": {},
                "marketing_metrics": {},
                "operations_metrics": {},
                "forecast_metrics": {},
            }
        )
    finally:
        structlog.contextvars.clear_contextvars()

    # 4 analysts + 1 manager
    assert len(seen_context_values) == 5
    assert all(value == "report-abc123" for value in seen_context_values), (
        "one or more of the 4 concurrent analyst nodes (or the manager) did not "
        "inherit the calling context -- LangGraph's executor may no longer be "
        "propagating contextvars into its thread pool, which would silently "
        "orphan Langfuse spans in production. See this file's module docstring."
    )
