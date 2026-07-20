from datetime import date

from app.models import Business, UploadSession
from app.report_generation import generate_report

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 1, 31)


def fake_call_llm(system_prompt, user_content):
    if "Manager agent" in system_prompt:
        return {
            "summary": "Business is healthy.",
            "risks": ["Risk one", "Risk two", "Risk three"],
            "opportunities": ["Opportunity one"],
            "actionPlan": ["Action one"],
            "forecast": "Growth expected.",
        }
    return {"findings": "Fine.", "confidence": 0.8}


def register_and_login(client, email):
    client.post(
        "/api/v1/auth/register",
        json={"fullName": "Test User", "email": email, "password": "password123"},
    )
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return login_response.json()["accessToken"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def _create_report(monkeypatch, client, db_session, email):
    monkeypatch.setattr("app.agents._call_llm", fake_call_llm)
    token = register_and_login(client, email)

    created = client.post(
        "/api/v1/businesses/", json={"businessName": "Reports Co"}, headers=auth_header(token)
    ).json()
    business_id = created["id"]

    business = db_session.get(Business, business_id)
    upload_session = UploadSession(
        business_id=business.id,
        sales_file_url="s3://fake/sales.csv",
        inventory_file_url="s3://fake/inventory.csv",
        expenses_file_url="s3://fake/expenses.csv",
        status="COMPLETED",
    )
    db_session.add(upload_session)
    db_session.commit()

    report = generate_report(
        db_session, business, period_start=PERIOD_START, period_end=PERIOD_END, upload_session_id=upload_session.id
    )
    return token, business_id, str(report.id)


def test_list_reports_includes_derived_business_health(monkeypatch, client, db_session):
    token, business_id, _ = _create_report(monkeypatch, client, db_session, "reports1@example.com")

    response = client.get(f"/api/v1/businesses/{business_id}/reports/", headers=auth_header(token))
    assert response.status_code == 200
    reports = response.json()
    assert len(reports) == 1
    # 3 risk sections seeded above -> "Needs Attention" per app/routers/report.py's thresholds
    assert reports[0]["businessHealth"] == "Needs Attention"


def test_get_report_groups_sections_by_type(monkeypatch, client, db_session):
    token, business_id, report_id = _create_report(monkeypatch, client, db_session, "reports2@example.com")

    response = client.get(f"/api/v1/businesses/{business_id}/reports/{report_id}", headers=auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Business is healthy."
    assert body["forecast"] == "Growth expected."
    assert body["risks"] == ["Risk one", "Risk two", "Risk three"]
    assert body["opportunities"] == ["Opportunity one"]
    assert body["actionPlan"] == ["Action one"]


def test_get_report_forbidden_for_non_owner(monkeypatch, client, db_session):
    _, business_id, report_id = _create_report(monkeypatch, client, db_session, "reports3@example.com")
    other_token = register_and_login(client, "intruder_reports@example.com")

    response = client.get(
        f"/api/v1/businesses/{business_id}/reports/{report_id}", headers=auth_header(other_token)
    )
    assert response.status_code == 403


def test_delete_report_removes_sections_and_agent_runs(monkeypatch, client, db_session):
    token, business_id, report_id = _create_report(monkeypatch, client, db_session, "reports4@example.com")

    delete_response = client.delete(
        f"/api/v1/businesses/{business_id}/reports/{report_id}", headers=auth_header(token)
    )
    assert delete_response.status_code == 204

    get_response = client.get(
        f"/api/v1/businesses/{business_id}/reports/{report_id}", headers=auth_header(token)
    )
    assert get_response.status_code == 404


def test_generate_report_endpoint_rejects_inverted_range(monkeypatch, client, db_session):
    # No Celery/eager-task DB-visibility concern here (see test_uploads.py's
    # comment on that) -- this request 400s in the router before .delay() is
    # ever called, so the SAVEPOINT-rollback client/db_session fixtures are fine.
    monkeypatch.setattr("app.agents._call_llm", fake_call_llm)
    token = register_and_login(client, "reports6@example.com")

    created = client.post(
        "/api/v1/businesses/", json={"businessName": "Inverted Range Co"}, headers=auth_header(token)
    ).json()
    business_id = created["id"]

    response = client.post(
        f"/api/v1/businesses/{business_id}/reports/generate",
        json={"periodStart": "2026-02-01", "periodEnd": "2026-01-01"},
        headers=auth_header(token),
    )
    assert response.status_code == 400
