import uuid
from datetime import date
from decimal import Decimal

from app.models import Business, Expense, Inventory, ReportSection, Sale, UploadSession, User
from app.report_generation import generate_report
from app.security import hash_password


def fake_call_llm(system_prompt, user_content):
    if "Manager agent" in system_prompt:
        return {
            "summary": "Overall the business is healthy.",
            "risks": ["Cash flow is tight this month"],
            "opportunities": ["Expand the best-selling product line"],
            "actionPlan": ["Review supplier pricing", "Restock low inventory items"],
            "forecast": "Stable growth expected next quarter.",
        }
    return {"findings": "Looks reasonable given the data.", "confidence": 0.9}


PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 1, 31)


def _seed_business_with_data(db_session, sale_date=None, expense_date=None, raw_row_number=1):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.flush()

    business = Business(owner_id=user.id, business_name="Report Test Co")
    db_session.add(business)
    db_session.flush()

    upload_session = UploadSession(
        business_id=business.id,
        sales_file_url="s3://fake/sales.csv",
        inventory_file_url="s3://fake/inventory.csv",
        expenses_file_url="s3://fake/expenses.csv",
        status="PROCESSING",
    )
    db_session.add(upload_session)
    db_session.flush()

    db_session.add(
        Sale(
            business_id=business.id,
            upload_session_id=upload_session.id,
            sale_date=sale_date or PERIOD_START,
            product_name="Rice",
            quantity=10,
            total_amount=Decimal("100.00"),
            discount=Decimal("0"),
            payment_method="Cash",
            raw_row_number=raw_row_number,
        )
    )
    db_session.add(
        Inventory(
            business_id=business.id,
            upload_session_id=upload_session.id,
            product_name="Rice",
            quantity=5,
            reorder_level=10,
            cost_price=Decimal("2.00"),
        )
    )
    db_session.add(
        Expense(
            business_id=business.id,
            upload_session_id=upload_session.id,
            expense_date=expense_date or PERIOD_START,
            category="Rent",
            amount=Decimal("50.00"),
        )
    )
    # Deliberately no commit/flush here: app/tasks.py's finalize_upload_task
    # adds sales/inventory/expenses rows on the same session and calls
    # generate_report() without an intervening flush, and SessionLocal has
    # autoflush=False -- generate_report() must flush internally, or its
    # own queries won't see these rows. Regression test for that bug.
    return business, upload_session


def _add_upload_session_data(db_session, business, sale_date, expense_date, raw_row_number):
    upload_session = UploadSession(
        business_id=business.id,
        sales_file_url="s3://fake/sales2.csv",
        inventory_file_url="s3://fake/inventory2.csv",
        expenses_file_url="s3://fake/expenses2.csv",
        status="PROCESSING",
    )
    db_session.add(upload_session)
    db_session.flush()

    db_session.add(
        Sale(
            business_id=business.id,
            upload_session_id=upload_session.id,
            sale_date=sale_date,
            product_name="Rice",
            quantity=10,
            total_amount=Decimal("100.00"),
            discount=Decimal("0"),
            payment_method="Cash",
            raw_row_number=raw_row_number,
        )
    )
    db_session.add(
        Expense(
            business_id=business.id,
            upload_session_id=upload_session.id,
            expense_date=expense_date,
            category="Rent",
            amount=Decimal("50.00"),
        )
    )
    return upload_session


def test_generate_report_writes_report_sections_and_agent_runs(monkeypatch, db_session):
    calls = []

    def recording_fake_call_llm(system_prompt, user_content):
        calls.append((system_prompt, user_content))
        return fake_call_llm(system_prompt, user_content)

    monkeypatch.setattr("app.agents._call_llm", recording_fake_call_llm)
    # generate_report populates RAG embeddings for the report as a side
    # effect (app/embedding_generation.py) -- a real OpenAI call if unmocked.
    monkeypatch.setattr("app.embedding_generation.generate_embedding", lambda text: [0.0] * 1536)
    business, upload_session = _seed_business_with_data(db_session)

    report = generate_report(
        db_session, business, period_start=PERIOD_START, period_end=PERIOD_END, upload_session_id=upload_session.id
    )

    finance_call_content = next(content for prompt, content in calls if "Finance analyst" in prompt)
    assert "100.0" in finance_call_content  # the seeded sale's total_amount -- proves metrics saw real data

    assert report.executive_summary == "Overall the business is healthy."
    assert report.forecast == "Stable growth expected next quarter."
    assert report.status == "COMPLETED"
    assert report.period_start == PERIOD_START
    assert report.period_end == PERIOD_END

    sections = db_session.query(ReportSection).filter(ReportSection.report_id == report.id).all()
    by_type = {"risk": [], "opportunity": [], "action_item": []}
    for section in sections:
        by_type[section.section_type].append(section.content)

    assert by_type["risk"] == ["Cash flow is tight this month"]
    assert by_type["opportunity"] == ["Expand the best-selling product line"]
    assert by_type["action_item"] == ["Review supplier pricing", "Restock low inventory items"]

    from app.models import AgentOutput, AgentRun

    agent_runs = db_session.query(AgentRun).filter(AgentRun.report_id == report.id).all()
    assert {run.agent_name for run in agent_runs} == {"finance", "inventory", "marketing", "operations", "manager"}
    for run in agent_runs:
        assert run.execution_time_ms is not None
        assert run.status == "completed"

    outputs = db_session.query(AgentOutput).join(AgentRun).filter(AgentRun.report_id == report.id).all()
    assert len(outputs) == 5


def test_generate_report_is_cumulative_across_upload_sessions_within_period(monkeypatch, db_session):
    """A report scoped to a date range must pull data from every upload
    session whose rows fall in that range, not just one -- this is the
    core behavior change from the old upload_session_id-scoped query."""
    calls = []

    def recording_fake_call_llm(system_prompt, user_content):
        calls.append((system_prompt, user_content))
        return fake_call_llm(system_prompt, user_content)

    monkeypatch.setattr("app.agents._call_llm", recording_fake_call_llm)
    monkeypatch.setattr("app.embedding_generation.generate_embedding", lambda text: [0.0] * 1536)

    business, first_upload_session = _seed_business_with_data(
        db_session, sale_date=date(2026, 1, 5), expense_date=date(2026, 1, 5), raw_row_number=1
    )
    second_upload_session = _add_upload_session_data(
        db_session, business, sale_date=date(2026, 1, 20), expense_date=date(2026, 1, 20), raw_row_number=1
    )

    report = generate_report(
        db_session,
        business,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        upload_session_id=second_upload_session.id,
    )

    finance_call_content = next(content for prompt, content in calls if "Finance analyst" in prompt)
    # $100 from each of the two upload sessions' sales -- proves both were included.
    assert "200.0" in finance_call_content
    assert first_upload_session.id != second_upload_session.id
