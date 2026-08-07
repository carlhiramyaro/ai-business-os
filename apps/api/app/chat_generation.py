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
from app.data_entry import (
    cancel_pending_entry,
    confirm_pending_entry,
    propose_expense_entry,
    propose_inventory_entry,
    propose_sale_entry,
)
from app.document_extraction import cancel_document_review, confirm_document_review
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

# v0.6 slice 3 (roadmap.md "Data entry by message"): propose_*_entry
# stages a row (app/data_entry.py), it does NOT write to sales/expenses/
# inventory yet -- confirm_pending_entry does that, on a LATER call once
# the owner has said something like "yes". All five dispatch through
# _execute below; casting/total-computation happens in app/data_entry.py,
# never here or in the model's own arithmetic.
_PROPOSE_SALE_ENTRY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "propose_sale_entry",
        "description": (
            "Stage a sale for confirmation -- use when the owner describes a sale they made "
            "(e.g. 'sold 3 bags of rice at 50 each'). Does NOT record anything yet; after "
            "calling this, tell the owner the proposed entry (use the tool result's `summary` "
            "verbatim -- don't recompute the total yourself) and ask them to confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string", "description": "What was sold."},
                "quantity": {"type": "integer", "description": "How many units."},
                "unit_price": {"type": "number", "description": "Price per unit, if mentioned."},
                "discount": {"type": "number", "description": "Discount amount, if mentioned."},
                "total_amount": {
                    "type": "number",
                    "description": "Total sale amount, ONLY if the owner stated it directly -- omit to let it be computed from quantity/unit_price/discount.",
                },
                "sale_date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD), resolved from relative terms like 'today'/'yesterday' using today's date. Omit for today.",
                },
                "category": {"type": "string"},
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string"},
                "payment_method": {"type": "string"},
            },
            "required": ["product_name", "quantity"],
        },
    },
}

_PROPOSE_EXPENSE_ENTRY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "propose_expense_entry",
        "description": (
            "Stage an expense for confirmation -- use when the owner describes money they "
            "spent (e.g. 'paid 200 for electricity'). Does NOT record anything yet; after "
            "calling this, relay the tool result's `summary` verbatim and ask the owner to "
            "confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Expense category, e.g. 'Utilities', 'Rent'."},
                "amount": {"type": "number"},
                "vendor": {"type": "string"},
                "expense_date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD), resolved from relative terms using today's date. Omit for today.",
                },
                "description": {"type": "string"},
            },
            "required": ["category", "amount"],
        },
    },
}

_PROPOSE_INVENTORY_ENTRY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "propose_inventory_entry",
        "description": (
            "Stage an inventory update for confirmation -- use when the owner describes stock "
            "on hand or a restock (e.g. 'got 50 more bags of rice'). Does NOT record anything "
            "yet; after calling this, relay the tool result's `summary` verbatim and ask the "
            "owner to confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string"},
                "quantity": {"type": "integer", "description": "The resulting quantity on hand, not a delta."},
                "category": {"type": "string"},
                "reorder_level": {"type": "integer"},
                "supplier": {"type": "string"},
                "cost_price": {"type": "number"},
                "selling_price": {"type": "number"},
            },
            "required": ["product_name", "quantity"],
        },
    },
}

_CONFIRM_PENDING_ENTRY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "confirm_pending_entry",
        "description": (
            "Finalize the most recently proposed (not yet recorded) sale/expense/inventory "
            "entry -- call this when the owner confirms a proposal you made earlier in this "
            "conversation (e.g. 'yes', 'correct', 'confirm')."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_CANCEL_PENDING_ENTRY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cancel_pending_entry",
        "description": (
            "Discard the most recently proposed (not yet recorded) sale/expense/inventory "
            "entry without recording it -- call this when the owner rejects or cancels a "
            "proposal you made earlier in this conversation (e.g. 'no', 'cancel', 'that's wrong')."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

# v0.6 slice 4 (roadmap.md "Media"): when the owner sends a photo of a
# receipt/invoice, extraction happens automatically and OUTSIDE this tool
# loop (app/tasks.py's handle_whatsapp_image_task) -- there is no
# "propose_document" tool, since nothing here decided to extract it, the
# image itself triggered it. These two tools are only how the owner's
# NEXT message (confirming or rejecting what was extracted) gets acted on
# -- the same "conversation history is the state" pattern
# confirm_pending_entry/cancel_pending_entry use for text-described
# entries. See docs/learning-guide.md 2.10.
_CONFIRM_DOCUMENT_REVIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "confirm_document_review",
        "description": (
            "Finalize the most recently extracted (not yet recorded) receipt/invoice photo -- "
            "call this when the owner confirms the summary you (or rather, the extraction step) "
            "sent them after they sent a photo (e.g. 'yes', 'correct', 'record it')."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_CANCEL_DOCUMENT_REVIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cancel_document_review",
        "description": (
            "Discard the most recently extracted (not yet recorded) receipt/invoice photo "
            "without recording it -- call this when the owner rejects it (e.g. 'no', 'wrong', "
            "'discard that')."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
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
        "- When the owner describes a sale, expense, or inventory change (e.g. 'sold 3 bags of "
        "rice at 50 each', 'paid 200 for electricity'), call the matching propose_*_entry tool. "
        "This only STAGES the entry -- relay the tool result's `summary` field to the owner "
        "verbatim (never recompute the total yourself) and ask them to confirm before it's "
        "recorded. If their next message confirms it (e.g. 'yes', 'correct'), call "
        "confirm_pending_entry. If they reject or correct it (e.g. 'no', 'wrong'), call "
        "cancel_pending_entry -- then propose_*_entry again with the corrected details if they "
        "gave them.\n"
        "- If the owner just sent a photo of a receipt/invoice, it's automatically extracted "
        "and you'll see a summary of what was found already in the conversation, asking them to "
        "confirm. On their next message, if they confirm (e.g. 'yes', 'correct'), call "
        "confirm_document_review. If they reject it (e.g. 'no', 'wrong'), call "
        "cancel_document_review.\n"
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
    if name == "propose_sale_entry":
        return propose_sale_entry(db, business_id, arguments)
    if name == "propose_expense_entry":
        return propose_expense_entry(db, business_id, arguments)
    if name == "propose_inventory_entry":
        return propose_inventory_entry(db, business_id, arguments)
    if name == "confirm_pending_entry":
        return confirm_pending_entry(db, business_id)
    if name == "cancel_pending_entry":
        return cancel_pending_entry(db, business_id)
    if name == "confirm_document_review":
        return confirm_document_review(db, business_id)
    if name == "cancel_document_review":
        return cancel_document_review(db, business_id)
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
    tools = [
        *TOOL_SCHEMAS,
        _SEARCH_CONTEXT_SCHEMA,
        _REMEMBER_FACT_SCHEMA,
        _PROPOSE_SALE_ENTRY_SCHEMA,
        _PROPOSE_EXPENSE_ENTRY_SCHEMA,
        _PROPOSE_INVENTORY_ENTRY_SCHEMA,
        _CONFIRM_PENDING_ENTRY_SCHEMA,
        _CANCEL_PENDING_ENTRY_SCHEMA,
        _CONFIRM_DOCUMENT_REVIEW_SCHEMA,
        _CANCEL_DOCUMENT_REVIEW_SCHEMA,
    ]

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
