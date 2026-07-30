import uuid
from datetime import date, timedelta
from decimal import Decimal

import app.tasks as tasks
from app.business_facts import remember_fact
from app.insights_generation import run_business_analysis
from app.models import Business, BusinessFact, Embedding, Expense, Insight, Inventory, Sale, UploadSession, User
from app.security import hash_password
from tests.conftest import TestSessionLocal

TODAY = date(2026, 3, 1)


def fake_narration_llm(system_prompt, user_content):
    return {"title": "Test insight", "body": "Test narration body."}


def register_and_login(client, email):
    client.post("/api/v1/auth/register", json={"fullName": "Test User", "email": email, "password": "password123"})
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return login_response.json()["accessToken"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# --- Part A: run_business_analysis against a real, committed DB ----------
# Same "can't use the SAVEPOINT-rollback fixture" reasoning as
# tests/test_uploads.py applies to anything hitting app.tasks.SessionLocal.
# These tests call run_business_analysis directly (not via the Celery task)
# so `today` can be injected for deterministic window math -- the same
# precedent as app.chat_tools.get_inactive_customers's injectable `today`.
# The task itself is a thin wrapper (load business, call this function) with
# its own smoke test further down.


def _seed_business_with_signals(db):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db.add(user)
    db.flush()
    business = Business(owner_id=user.id, business_name="Signal Test Co")
    db.add(business)
    db.flush()

    upload_session = UploadSession(business_id=business.id, status="COMPLETED")
    db.add(upload_session)
    db.flush()

    recent_start, recent_end = TODAY - timedelta(days=6), TODAY
    prior_start, prior_end = TODAY - timedelta(days=13), TODAY - timedelta(days=7)

    # Expense spike: Utilities jumps from 100 (baseline/prior week) to 200 (recent week).
    db.add(
        Expense(
            business_id=business.id,
            upload_session_id=upload_session.id,
            expense_date=prior_start + timedelta(days=1),
            category="Utilities",
            amount=Decimal("100.00"),
        )
    )
    db.add(
        Expense(
            business_id=business.id,
            upload_session_id=upload_session.id,
            expense_date=recent_start + timedelta(days=1),
            category="Utilities",
            amount=Decimal("200.00"),
        )
    )

    # Stock depletion: Rice sells 300 units in the trailing 30-day velocity
    # window (10/day) against only 10 units left in stock -> 1 day to stockout.
    db.add(
        Sale(
            business_id=business.id,
            upload_session_id=upload_session.id,
            sale_date=TODAY - timedelta(days=10),
            product_name="Rice",
            quantity=300,
            total_amount=Decimal("3000.00"),
            discount=Decimal("0"),
            payment_method="Cash",
            raw_row_number=1,
        )
    )
    db.add(
        Inventory(
            business_id=business.id,
            upload_session_id=upload_session.id,
            product_name="Rice",
            quantity=10,
            reorder_level=50,
            cost_price=Decimal("2.00"),
        )
    )
    db.commit()
    return business


def test_run_business_analysis_creates_expected_insights(monkeypatch):
    monkeypatch.setattr("app.agents._call_llm", fake_narration_llm)

    db = TestSessionLocal()
    try:
        business = _seed_business_with_signals(db)

        created_count = run_business_analysis(db, business, today=TODAY)
        assert created_count >= 2

        insights = db.query(Insight).filter(Insight.business_id == business.id).all()
        types = {i.insight_type for i in insights}
        assert "expense_spike" in types
        assert "stock_depletion" in types

        expense_insight = next(i for i in insights if i.insight_type == "expense_spike")
        assert expense_insight.metrics["category"] == "Utilities"
        assert expense_insight.metrics["pctChange"] == 1.0
        assert expense_insight.severity == "critical"

        stock_insight = next(i for i in insights if i.insight_type == "stock_depletion")
        assert stock_insight.metrics["productName"] == "Rice"
        assert stock_insight.metrics["daysToStockout"] == 1.0

        # Re-running against unchanged data must not create duplicates.
        first_run_count = len(insights)
        second_created_count = run_business_analysis(db, business, today=TODAY)
        assert second_created_count == 0
        second_run_insights = db.query(Insight).filter(Insight.business_id == business.id).all()
        assert len(second_run_insights) == first_run_count
    finally:
        db.query(Insight).filter(Insight.business_id == business.id).delete()
        db.query(Sale).filter(Sale.business_id == business.id).delete()
        db.query(Inventory).filter(Inventory.business_id == business.id).delete()
        db.query(Expense).filter(Expense.business_id == business.id).delete()
        db.query(UploadSession).filter(UploadSession.business_id == business.id).delete()
        db.query(Business).filter(Business.id == business.id).delete()
        db.query(User).filter(User.id == business.owner_id).delete()
        db.commit()
        db.close()


def test_run_business_analysis_includes_relevant_business_facts_in_narration(monkeypatch):
    """v0.4 slice 3: a stored business_facts row should reach
    narrate_insight as knownContext -- captured here via the real
    _call_llm's user_content payload, since fake_narration_llm's return
    value doesn't otherwise reveal what it was given."""
    monkeypatch.setattr("app.embedding_generation.generate_embedding", lambda text: [0.0] * 1536)

    calls = []

    def recording_fake_call_llm(system_prompt, user_content):
        calls.append((system_prompt, user_content))
        return fake_narration_llm(system_prompt, user_content)

    monkeypatch.setattr("app.agents._call_llm", recording_fake_call_llm)

    db = TestSessionLocal()
    try:
        business = _seed_business_with_signals(db)
        remember_fact(db, business.id, "December is our peak season")
        db.commit()

        run_business_analysis(db, business, today=TODAY)

        narration_calls = [c for c in calls if "narrating a single detected" in c[0]]
        assert narration_calls, "expected at least one narrate_insight call"
        assert any("December is our peak season" in user_content for _, user_content in narration_calls)
    finally:
        db.query(Insight).filter(Insight.business_id == business.id).delete()
        db.query(Embedding).filter(Embedding.business_id == business.id).delete()
        db.query(BusinessFact).filter(BusinessFact.business_id == business.id).delete()
        db.query(Sale).filter(Sale.business_id == business.id).delete()
        db.query(Inventory).filter(Inventory.business_id == business.id).delete()
        db.query(Expense).filter(Expense.business_id == business.id).delete()
        db.query(UploadSession).filter(UploadSession.business_id == business.id).delete()
        db.query(Business).filter(Business.id == business.id).delete()
        db.query(User).filter(User.id == business.owner_id).delete()
        db.commit()
        db.close()


def test_run_business_analysis_task_missing_business_is_a_noop(monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.agents._call_llm", fake_narration_llm)

    tasks.run_business_analysis_task.delay(str(uuid.uuid4()))  # must not raise


def test_run_business_analysis_task_wiring(monkeypatch):
    """Smoke test for the Celery task itself (not the date-sensitive
    detector math, covered above): loads a real business with no
    signal-worthy data and confirms the task runs end to end with no
    exceptions and creates nothing."""
    monkeypatch.setattr(tasks, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.agents._call_llm", fake_narration_llm)

    db = TestSessionLocal()
    try:
        user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
        db.add(user)
        db.flush()
        business = Business(owner_id=user.id, business_name="Empty Co")
        db.add(business)
        db.commit()

        tasks.run_business_analysis_task.delay(str(business.id))

        assert db.query(Insight).filter(Insight.business_id == business.id).count() == 0
    finally:
        db.query(Insight).filter(Insight.business_id == business.id).delete()
        db.query(Business).filter(Business.id == business.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()


# --- Part B: list/unread-count/mark-read via the rollback client fixture --
# No Celery task involved here, so the standard client/db_session fixtures
# (same connection, uncommitted-safe) are fine.


def test_insights_list_unread_count_and_mark_read(client, db_session):
    token = register_and_login(client, f"{uuid.uuid4()}@example.com")
    created = client.post(
        "/api/v1/businesses/", json={"businessName": "Insights Co"}, headers=auth_header(token)
    ).json()
    business_id = created["id"]
    business = db_session.get(Business, business_id)

    db_session.add(
        Insight(
            business_id=business.id,
            insight_type="revenue_trend",
            severity="warning",
            title="Revenue dipped",
            body="Revenue is down week over week.",
            metrics={"pctChange": -0.25},
            fingerprint="test-fingerprint-1",
            period_start=TODAY - timedelta(days=6),
            period_end=TODAY,
        )
    )
    db_session.commit()

    list_response = client.get(f"/api/v1/businesses/{business_id}/insights/", headers=auth_header(token))
    assert list_response.status_code == 200
    body = list_response.json()
    assert len(body) == 1
    assert body[0]["insightType"] == "revenue_trend"
    assert body[0]["isRead"] is False
    insight_id = body[0]["id"]

    unread_response = client.get(f"/api/v1/businesses/{business_id}/insights/unread-count", headers=auth_header(token))
    assert unread_response.json() == {"unreadCount": 1}

    patch_response = client.patch(
        f"/api/v1/businesses/{business_id}/insights/{insight_id}", json={"read": True}, headers=auth_header(token)
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["isRead"] is True

    unread_after = client.get(f"/api/v1/businesses/{business_id}/insights/unread-count", headers=auth_header(token))
    assert unread_after.json() == {"unreadCount": 0}


def test_insights_scoped_to_owning_business(client, db_session):
    token_a = register_and_login(client, f"{uuid.uuid4()}@example.com")
    token_b = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business_a = client.post(
        "/api/v1/businesses/", json={"businessName": "Business A"}, headers=auth_header(token_a)
    ).json()

    response = client.get(f"/api/v1/businesses/{business_a['id']}/insights/", headers=auth_header(token_b))
    assert response.status_code == 403
