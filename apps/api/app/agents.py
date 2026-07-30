import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def _call_llm(system_prompt: str, user_content: str) -> dict:
    client = OpenAI()
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


_FINDINGS_INSTRUCTION = (
    'Respond as strict JSON: {"findings": "2-4 sentence narrative", "confidence": 0.0-1.0}.'
)


def run_finance_agent(metrics: dict) -> dict:
    system = (
        "You are the Finance analyst on a small-business analysis team. Given these "
        "computed revenue/expense/profit metrics, write a short finding about the "
        "business's financial health. " + _FINDINGS_INSTRUCTION
    )
    return _call_llm(system, json.dumps(metrics))


def run_inventory_agent(metrics: dict) -> dict:
    system = (
        "You are the Inventory analyst on a small-business analysis team. Given these "
        "computed stock-level metrics, write a short finding about inventory health "
        "(e.g. reorder risk, overstock). " + _FINDINGS_INSTRUCTION
    )
    return _call_llm(system, json.dumps(metrics))


def run_marketing_agent(metrics: dict) -> dict:
    system = (
        "You are the Marketing analyst on a small-business analysis team. Given these "
        "computed sales/customer metrics, write a short finding about what's selling "
        "and how customers are paying. " + _FINDINGS_INSTRUCTION
    )
    return _call_llm(system, json.dumps(metrics))


def run_operations_agent(metrics: dict) -> dict:
    system = (
        "You are the Operations analyst on a small-business analysis team. Given these "
        "computed order-volume/discount metrics, write a short finding about "
        "operational efficiency. " + _FINDINGS_INSTRUCTION
    )
    return _call_llm(system, json.dumps(metrics))


def run_manager_agent(agent_findings: dict) -> dict:
    system = (
        "You are the Manager agent synthesizing four analysts' findings (finance, "
        "inventory, marketing, operations) into a Business Health Report. You are also "
        "given a 'forecast' object of deterministically computed figures: projected "
        "revenue over the next horizonDays (with the trailing average it's based on and "
        "the week-over-week trend, when available), and stock-depletion estimates per "
        "product (daysToStockout, and which items are atRisk within the horizon). "
        "Respond as strict JSON with exactly these fields: {\"summary\": \"1-2 sentence "
        'executive summary", "risks": ["..."], "opportunities": ["..."], "actionPlan": '
        '["..."], "forecast": "1-2 sentence forecast"}. Keep each list to 2-4 concise '
        "items, each item a single sentence. The forecast field MUST explain the given "
        "computed forecast numbers (cite the projected revenue and any at-risk products "
        "by name) -- never invent a forecast figure that isn't in the provided data."
    )
    return _call_llm(system, json.dumps(agent_findings))


def narrate_insight(signal: dict, relevant_facts: list[str] | None = None) -> dict:
    """v0.4 slice 2: turn one deterministic signal (app/signals.py) into the
    explain-and-recommend voice from product-vision.md's rice example.
    Given the signal's computed metrics, explain what's happening and
    recommend one concrete next step -- never invent a figure that isn't in
    `signal["metrics"]`.

    v0.4 slice 3: relevant_facts (from business memory, app/business_facts.py
    via app/insights_generation.py's retrieval) are known context the model
    can use to inform its tone -- e.g. not flagging an expected seasonal dip
    as alarming -- but they never substitute for or override the metrics."""
    system = (
        f"You are narrating a single detected '{signal['type']}' business signal for a "
        "small-business owner. You are given the deterministically computed metrics behind "
        "it -- explain what's happening in plain language and recommend one concrete next "
        'step. Respond as strict JSON: {"title": "one short headline (under 10 words)", '
        '"body": "2-3 sentences: what\'s happening, why it matters, what to do"}. Cite the '
        "given numbers directly; never invent a figure that isn't in the provided metrics. "
        "If the payload includes a knownContext list, use it only to inform tone (e.g. don't "
        "treat an expected seasonal pattern as alarming) -- still ground every number in metrics."
    )
    payload = {"metrics": signal["metrics"]}
    if relevant_facts:
        payload["knownContext"] = relevant_facts
    return _call_llm(system, json.dumps(payload))
