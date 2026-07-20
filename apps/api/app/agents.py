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
        "inventory, marketing, operations) into a Business Health Report. Respond as "
        'strict JSON with exactly these fields: {"summary": "1-2 sentence executive '
        'summary", "risks": ["..."], "opportunities": ["..."], "actionPlan": ["..."], '
        '"forecast": "1-2 sentence forecast"}. Keep each list to 2-4 concise items, '
        "each item a single sentence."
    )
    return _call_llm(system, json.dumps(agent_findings))
