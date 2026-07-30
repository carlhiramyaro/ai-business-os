import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date

from dotenv import load_dotenv

# Drop-in replacement for openai.OpenAI -- traces every call to Langfuse
# with no other code change. See docs/infra-guide.md. propagate_attributes
# (session_id=conversation_id) is applied at the call site in
# app/routers/chat.py, not here -- this function doesn't receive
# conversation_id itself.
from langfuse import observe
from langfuse.openai import OpenAI
from sqlalchemy.orm import Session

from app.business_facts import remember_fact
from app.chat_tools import TOOL_SCHEMAS, ToolArgumentError, execute_tool
from app.retrieval import retrieve_relevant_chunks

load_dotenv()

# Caps the agent loop: each round is one model call that may request tool
# calls. Analytical questions rarely need more than 2-3 rounds; past the cap
# we force a final answer from whatever was gathered.
MAX_TOOL_ROUNDS = 5

_SEARCH_CONTEXT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_business_context",
        "description": (
            "Semantic search over this business's generated reports and analysis "
            "(risks, opportunities, narrative findings). Use for 'why'/pattern "
            "questions and past analysis — NOT for exact current figures; use the "
            "SQL tools for those."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to search for."}},
            "required": ["query"],
        },
    },
}

_REMEMBER_FACT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "remember_business_fact",
        "description": (
            "Save a durable fact about this business for future reference -- e.g. seasonal "
            "patterns ('December is our peak season'), recurring supplier issues, or customer "
            "preferences the owner mentions. Use this when the owner states something that will "
            "still be true/useful beyond this conversation. Do NOT use it for one-off questions "
            "or exact figures -- those come from the SQL tools and don't need remembering."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "A concise, self-contained statement of the fact -- written so it makes sense without this conversation's context.",
                }
            },
            "required": ["fact"],
        },
    },
}


@dataclass
class ChatAnswer:
    answer: str
    tool_calls: list[dict] = field(default_factory=list)


def _system_prompt(business) -> str:
    currency = getattr(business, "currency", None) or "the business's local currency"
    return (
        f"You are a business analyst assistant for '{business.business_name}', a small "
        f"business. Today's date is {date.today().isoformat()}. Amounts are in {currency}.\n\n"
        "Answer questions about this business using the provided tools:\n"
        "- Every exact figure (revenue, profit, counts, rankings) MUST come from a tool "
        "result — never compute or estimate figures yourself.\n"
        "- Use search_business_context for narrative/'why' questions and past analysis.\n"
        "- When the owner states something durable about the business that isn't just "
        "answering your current question (a seasonal pattern, a recurring supplier issue, a "
        "customer preference), call remember_business_fact to save it for future conversations.\n"
        "- Resolve relative dates ('this month', 'last week') into explicit date ranges "
        "using today's date.\n"
        "- If the tools return no relevant data, say so plainly rather than guessing.\n"
        "- Be concise and concrete; explain what the numbers mean for the owner."
    )


def _execute(db: Session, business_id: uuid.UUID, name: str, arguments: dict) -> dict:
    if name == "search_business_context":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgumentError("query must be a non-empty string")
        return {"chunks": retrieve_relevant_chunks(db, business_id, query)}
    if name == "remember_business_fact":
        fact = arguments.get("fact")
        if not isinstance(fact, str) or not fact.strip():
            raise ToolArgumentError("fact must be a non-empty string")
        remember_fact(db, business_id, fact.strip())
        return {"saved": True}
    return execute_tool(db, business_id, name, arguments)


@observe(name="chat_answer")
def generate_chat_answer(db: Session, business, question: str, history: list[dict]) -> ChatAnswer:
    """history: [{"role": "user"|"assistant", "content": "..."}], oldest first.

    Runs a tool-calling loop: the model may request tool calls (executed
    against this business's data), sees the results, and either calls more
    tools or answers. Returns the answer plus a record of every tool call
    made, so the API can show which queries backed the figures."""
    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    tools = [*TOOL_SCHEMAS, _SEARCH_CONTEXT_SCHEMA, _REMEMBER_FACT_SCHEMA]

    messages = [{"role": "system", "content": _system_prompt(business)}, *history, {"role": "user", "content": question}]
    executed: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(model=model, messages=messages, tools=tools)
        message = response.choices[0].message
        if not message.tool_calls:
            return ChatAnswer(answer=message.content, tool_calls=executed)

        messages.append(message)
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
                result = _execute(db, business.id, name, arguments)
            except (ToolArgumentError, json.JSONDecodeError) as exc:
                # The model sees its own mistake and can retry with fixed
                # arguments in the next round.
                arguments = {}
                result = {"error": str(exc)}
            executed.append({"tool": name, "arguments": arguments})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, default=str),
                }
            )

    # Round cap hit: one last call with no tools available forces a final
    # answer from the context gathered so far.
    response = client.chat.completions.create(model=model, messages=messages)
    return ChatAnswer(answer=response.choices[0].message.content, tool_calls=executed)
