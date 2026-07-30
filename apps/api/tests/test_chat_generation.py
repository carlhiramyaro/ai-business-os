"""Agent-loop tests: only the OpenAI client is faked (scripted responses);
tool execution runs against the real test DB, per the repo's
only-mock-the-LLM rule."""

import json
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import app.chat_generation as chat_generation_module
from app.chat_generation import MAX_TOOL_ROUNDS, generate_chat_answer
from app.models import Business, Sale, UploadSession, User
from app.security import hash_password


def _seed_business(db_session):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.flush()
    business = Business(owner_id=user.id, business_name="Agent Loop Test Co", currency="GHS")
    db_session.add(business)
    db_session.flush()
    upload_session = UploadSession(
        business_id=business.id,
        sales_file_url="s3://fake/sales.csv",
        inventory_file_url="s3://fake/inventory.csv",
        expenses_file_url="s3://fake/expenses.csv",
        status="COMPLETED",
    )
    db_session.add(upload_session)
    db_session.flush()
    db_session.add(
        Sale(
            business_id=business.id,
            upload_session_id=upload_session.id,
            sale_date=date(2026, 6, 1),
            product_name="Rice",
            quantity=1,
            total_amount=Decimal("100.00"),
            raw_row_number=1,
        )
    )
    db_session.flush()
    return business


def _tool_call(name, arguments):
    return SimpleNamespace(
        id=f"call_{uuid.uuid4().hex[:8]}",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _model_turn(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


class FakeCompletions:
    def __init__(self, scripted_turns):
        self.scripted_turns = list(scripted_turns)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.scripted_turns) > 1:
            return self.scripted_turns.pop(0)
        return self.scripted_turns[0]  # final turn repeats if the loop keeps asking


def _fake_openai(monkeypatch, scripted_turns):
    completions = FakeCompletions(scripted_turns)
    monkeypatch.setattr(
        chat_generation_module,
        "OpenAI",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    return completions


def test_sql_tool_result_flows_back_to_model(monkeypatch, db_session):
    business = _seed_business(db_session)
    completions = _fake_openai(
        monkeypatch,
        [
            _model_turn(tool_calls=[_tool_call("get_financial_summary", {})]),
            _model_turn(content="Your revenue is GHS 100."),
        ],
    )

    result = generate_chat_answer(db_session, business, "How much revenue did I make?", history=[])

    assert result.answer == "Your revenue is GHS 100."
    assert result.tool_calls == [{"tool": "get_financial_summary", "arguments": {}}]
    # The second model call must include the real DB-computed tool result.
    tool_messages = [m for m in completions.calls[1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert json.loads(tool_messages[0]["content"])["totalRevenue"] == 100.0


def test_rag_tool_uses_retrieval(monkeypatch, db_session):
    business = _seed_business(db_session)
    monkeypatch.setattr(
        chat_generation_module,
        "retrieve_relevant_chunks",
        lambda db, business_id, query, top_k=5: [f"chunk about {query}"],
    )
    completions = _fake_openai(
        monkeypatch,
        [
            _model_turn(tool_calls=[_tool_call("search_business_context", {"query": "profit risks"})]),
            _model_turn(content="Per your last report, supplier costs are the main risk."),
        ],
    )

    result = generate_chat_answer(db_session, business, "Why is profit down?", history=[])

    assert result.answer == "Per your last report, supplier costs are the main risk."
    tool_messages = [m for m in completions.calls[1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
    assert json.loads(tool_messages[0]["content"]) == {"chunks": ["chunk about profit risks"]}


def test_invalid_tool_arguments_are_fed_back_not_raised(monkeypatch, db_session):
    business = _seed_business(db_session)
    completions = _fake_openai(
        monkeypatch,
        [
            _model_turn(tool_calls=[_tool_call("get_financial_summary", {"period_start": "June 2026"})]),
            _model_turn(content="Sorry, let me rephrase that."),
        ],
    )

    result = generate_chat_answer(db_session, business, "Revenue for June 2026?", history=[])

    assert result.answer == "Sorry, let me rephrase that."
    tool_messages = [m for m in completions.calls[1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
    assert "error" in json.loads(tool_messages[0]["content"])


def test_remember_business_fact_tool_persists_fact_and_embedding(monkeypatch, db_session):
    business = _seed_business(db_session)
    monkeypatch.setattr("app.embedding_generation.generate_embedding", lambda text: [0.0] * 1536)
    completions = _fake_openai(
        monkeypatch,
        [
            _model_turn(tool_calls=[_tool_call("remember_business_fact", {"fact": "December is our peak season"})]),
            _model_turn(content="Got it, I'll remember that."),
        ],
    )

    result = generate_chat_answer(
        db_session, business, "Just so you know, December is our peak season", history=[]
    )

    assert result.answer == "Got it, I'll remember that."
    assert result.tool_calls == [
        {"tool": "remember_business_fact", "arguments": {"fact": "December is our peak season"}}
    ]
    tool_messages = [m for m in completions.calls[1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
    assert json.loads(tool_messages[0]["content"]) == {"saved": True}

    from app.models import BusinessFact, Embedding

    fact = db_session.query(BusinessFact).filter(BusinessFact.business_id == business.id).one()
    assert fact.content == "December is our peak season"
    assert fact.source == "chat"

    embedding = db_session.query(Embedding).filter(Embedding.source_id == fact.id).one()
    assert embedding.source_type == "business_fact"
    assert embedding.chunk_text == "December is our peak season"


def test_remember_business_fact_empty_fact_is_fed_back_not_raised(monkeypatch, db_session):
    business = _seed_business(db_session)
    completions = _fake_openai(
        monkeypatch,
        [
            _model_turn(tool_calls=[_tool_call("remember_business_fact", {"fact": "   "})]),
            _model_turn(content="Understood."),
        ],
    )

    result = generate_chat_answer(db_session, business, "Hmm", history=[])

    assert result.answer == "Understood."
    tool_messages = [m for m in completions.calls[1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
    assert "error" in json.loads(tool_messages[0]["content"])


def test_round_cap_forces_final_answer_without_tools(monkeypatch, db_session):
    business = _seed_business(db_session)
    completions = FakeCompletions([])

    def create(**kwargs):
        completions.calls.append(kwargs)
        if "tools" in kwargs:
            return _model_turn(tool_calls=[_tool_call("get_inventory_status", {})])
        return _model_turn(content="Here's what I found so far.")

    completions.create = create
    monkeypatch.setattr(
        chat_generation_module,
        "OpenAI",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )

    result = generate_chat_answer(db_session, business, "Loop forever please", history=[])

    assert result.answer == "Here's what I found so far."
    assert len(result.tool_calls) == MAX_TOOL_ROUNDS
    assert len(completions.calls) == MAX_TOOL_ROUNDS + 1
    assert "tools" not in completions.calls[-1]  # the forced-final call offers no tools
