import io
import uuid

import pytest
from fastapi.testclient import TestClient

import app.column_mapping as column_mapping
import app.routers.upload as upload_router
import app.tasks as tasks
from app.database import get_db
from app.models import (
    AgentOutput,
    AgentRun,
    Business,
    ColumnMapping,
    DatasetProfile,
    Embedding,
    Expense,
    Inventory,
    Report,
    ReportSection,
    Sale,
    UploadSession,
    User,
)
from app.security import create_access_token, hash_password
from main import app
from tests.conftest import TestSessionLocal


def fake_call_llm(system_prompt, user_content):
    if "Manager agent" in system_prompt:
        return {
            "summary": "Business is healthy.",
            "risks": ["Risk one"],
            "opportunities": ["Opportunity one"],
            "actionPlan": ["Action one"],
            "forecast": "Growth expected.",
        }
    return {"findings": "Fine.", "confidence": 0.8}


def fake_generate_embedding(text):
    return [0.0] * 1536

# These tests can't use the SAVEPOINT-rollback `client`/`db_session`
# fixtures from conftest.py: the Celery task (run synchronously here via
# task_always_eager) opens its own DB connection via app.tasks.SessionLocal,
# a completely separate connection from the one backing an uncommitted
# outer transaction -- it would never see a business/user row that only
# exists inside that other connection's not-yet-committed transaction.
# So this module commits for real against ai_business_os_test and cleans up
# explicitly afterward -- the other of the two test strategies
# agent-instructions.md sanctions ("a dedicated local test database ... or
# transaction rollback per test").

FAKE_S3: dict[str, bytes] = {}


def fake_upload_fileobj(fileobj, key):
    FAKE_S3[key] = fileobj.read()
    return f"fake://{key}"


def fake_download_fileobj(key):
    return io.BytesIO(FAKE_S3[key])


@pytest.fixture(autouse=True)
def _patch_storage_and_db(monkeypatch):
    monkeypatch.setattr(upload_router, "upload_fileobj", fake_upload_fileobj)
    monkeypatch.setattr(tasks, "download_fileobj", fake_download_fileobj)
    monkeypatch.setattr(tasks, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.agents._call_llm", fake_call_llm)
    monkeypatch.setattr("app.embedding_generation.generate_embedding", fake_generate_embedding)
    FAKE_S3.clear()
    yield
    with TestSessionLocal() as db:
        db.query(Embedding).delete()
        db.query(AgentOutput).delete()
        db.query(AgentRun).delete()
        db.query(ReportSection).delete()
        db.query(Report).delete()
        db.query(DatasetProfile).delete()
        db.query(ColumnMapping).delete()
        db.query(Sale).delete()
        db.query(Inventory).delete()
        db.query(Expense).delete()
        db.query(UploadSession).delete()
        db.query(Business).delete()
        db.query(User).delete()
        db.commit()


@pytest.fixture()
def real_client():
    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def business_id():
    with TestSessionLocal() as db:
        user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
        db.add(user)
        db.flush()
        business = Business(owner_id=user.id, business_name="Test Biz")
        db.add(business)
        db.commit()
        return str(business.id), create_access_token(str(user.id))


CLEAN_SALES_CSV = (
    b"Date,Item,Category,Qty,Unit Price,Discount,Total Amount,Customer,Payment Method\n"
    b"2026-01-01,Rice,Grocery,10,2.5,0,25.0,John Doe,Cash\n"
)
CLEAN_INVENTORY_CSV = (
    b"Product,Category,Quantity,Reorder Level,Supplier,Cost Price,Selling Price\n"
    b"Rice,Grocery,100,20,Acme Supplies,2.0,2.5\n"
)
CLEAN_EXPENSES_CSV = b"Date,Category,Vendor,Amount,Description\n2026-01-02,Utilities,Power Co,150.0,Electricity bill\n"


def _upload_files(sales=CLEAN_SALES_CSV, inventory=CLEAN_INVENTORY_CSV, expenses=CLEAN_EXPENSES_CSV):
    return {
        "sales": ("sales.csv", io.BytesIO(sales), "text/csv"),
        "inventory": ("inventory.csv", io.BytesIO(inventory), "text/csv"),
        "expenses": ("expenses.csv", io.BytesIO(expenses), "text/csv"),
    }


def test_upload_with_clean_headers_completes_synchronously(real_client, business_id):
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}

    response = real_client.post(
        f"/api/v1/businesses/{business_id}/uploads/", files=_upload_files(), headers=headers
    )
    assert response.status_code == 202
    upload_session_id = response.json()["uploadSessionId"]

    status_response = real_client.get(
        f"/api/v1/businesses/{business_id}/uploads/{upload_session_id}", headers=headers
    )
    assert status_response.json() == {"status": "COMPLETED", "progress": 100, "pendingReview": None}

    with TestSessionLocal() as db:
        assert db.query(Sale).filter(Sale.upload_session_id == upload_session_id).count() == 1
        assert db.query(Inventory).filter(Inventory.upload_session_id == upload_session_id).count() == 1
        assert db.query(Expense).filter(Expense.upload_session_id == upload_session_id).count() == 1

        sale = db.query(Sale).filter(Sale.upload_session_id == upload_session_id).first()
        assert sale.product_name == "Rice"
        assert float(sale.total_amount) == 25.0
        assert sale.raw_row_number == 1

        profiles = db.query(DatasetProfile).filter(DatasetProfile.upload_session_id == upload_session_id).all()
        assert {p.dataset_type: p.total_rows for p in profiles} == {"sales": 1, "inventory": 1, "expenses": 1}

    mappings = real_client.get(
        f"/api/v1/businesses/{business_id}/uploads/{upload_session_id}/column-mappings", headers=headers
    ).json()
    assert len(mappings) == 9 + 7 + 5
    assert all(m["mappingMethod"] == "heuristic" and m["confidenceScore"] == 1.0 for m in mappings)


def test_upload_with_ambiguous_header_needs_review_then_resumes(monkeypatch, real_client, business_id):
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(column_mapping, "llm_match", lambda header, dataset_type, samples: ("productName", 0.4))

    ambiguous_sales_csv = (
        b"Date,X1,Category,Qty,Unit Price,Discount,Total Amount,Customer,Payment Method\n"
        b"2026-01-01,Rice,Grocery,10,2.5,0,25.0,John Doe,Cash\n"
    )

    response = real_client.post(
        f"/api/v1/businesses/{business_id}/uploads/",
        files=_upload_files(sales=ambiguous_sales_csv),
        headers=headers,
    )
    upload_session_id = response.json()["uploadSessionId"]

    status_response = real_client.get(
        f"/api/v1/businesses/{business_id}/uploads/{upload_session_id}", headers=headers
    ).json()
    assert status_response["status"] == "NEEDS_REVIEW"
    assert status_response["pendingReview"] == ["sales"]

    mappings = real_client.get(
        f"/api/v1/businesses/{business_id}/uploads/{upload_session_id}/column-mappings", headers=headers
    ).json()
    low_confidence = next(m for m in mappings if m["sourceColumnName"] == "X1")
    assert low_confidence["mappingMethod"] == "llm"
    assert low_confidence["confidenceScore"] == 0.4

    corrected = real_client.patch(
        f"/api/v1/businesses/{business_id}/uploads/{upload_session_id}/column-mappings/{low_confidence['id']}",
        json={"targetField": "productName"},
        headers=headers,
    )
    assert corrected.json()["mappingMethod"] == "user_confirmed"

    confirm_response = real_client.post(
        f"/api/v1/businesses/{business_id}/uploads/{upload_session_id}/column-mappings/confirm",
        headers=headers,
    )
    assert confirm_response.status_code == 202

    final_status = real_client.get(
        f"/api/v1/businesses/{business_id}/uploads/{upload_session_id}", headers=headers
    ).json()
    assert final_status["status"] == "COMPLETED"

    with TestSessionLocal() as db:
        sale = db.query(Sale).filter(Sale.upload_session_id == upload_session_id).first()
        assert sale.product_name == "Rice"


def test_generate_report_endpoint_runs_via_celery_and_completes(real_client, business_id):
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}

    response = real_client.post(
        f"/api/v1/businesses/{business_id}/reports/generate",
        json={"periodStart": "2026-01-01", "periodEnd": "2026-01-31"},
        headers=headers,
    )
    assert response.status_code == 202
    report_id = response.json()["reportId"]
    assert response.json()["status"] == "PENDING"

    # Celery runs eagerly in tests (task_always_eager, set in conftest.py's
    # _celery_eager fixture), so by the time .delay() returns above inside the
    # router, generation has already run against the same TestSessionLocal
    # connection this module patches app.tasks.SessionLocal to (see the
    # _patch_storage_and_db fixture's comment above for why that patch is
    # required for a Celery-backed test to see data at all).
    get_response = real_client.get(f"/api/v1/businesses/{business_id}/reports/{report_id}", headers=headers)
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["status"] == "COMPLETED"
    assert body["periodStart"] == "2026-01-01"
    assert body["periodEnd"] == "2026-01-31"


def test_upload_report_is_cumulative_across_two_uploads_in_same_period(real_client, business_id):
    """The auto-generated report's period is derived from the date span of
    the rows in the upload that triggered it, but the query for that period
    pulls ALL of the business's rows in that range -- not just the triggering
    upload's own rows. Exercise that by making the second upload's date span
    (Jan 5 - Jan 20) overlap the first upload's single date (Jan 5), so the
    second report should include the first upload's row too."""
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}

    first_sales_csv = b"Date,Item,Category,Qty,Unit Price,Discount,Total Amount,Customer,Payment Method\n2026-01-05,Rice,Grocery,10,2.5,0,25.0,John Doe,Cash\n"
    second_sales_csv = (
        b"Date,Item,Category,Qty,Unit Price,Discount,Total Amount,Customer,Payment Method\n"
        b"2026-01-05,Beans,Grocery,4,3.0,0,12.0,Jane Doe,Card\n"
        b"2026-01-20,Cassava,Grocery,6,1.5,0,9.0,Jane Doe,Card\n"
    )
    # Default CLEAN_EXPENSES_CSV is dated 2026-01-02, which would pull the
    # derived period's start earlier than the sales range being tested here --
    # override with a date inside [Jan 5, Jan 20] so the period stays exactly
    # what the sales rows imply.
    in_range_expenses_csv = b"Date,Category,Vendor,Amount,Description\n2026-01-10,Utilities,Power Co,150.0,Electricity bill\n"

    first_response = real_client.post(
        f"/api/v1/businesses/{business_id}/uploads/", files=_upload_files(sales=first_sales_csv), headers=headers
    )
    assert first_response.status_code == 202

    second_response = real_client.post(
        f"/api/v1/businesses/{business_id}/uploads/",
        files=_upload_files(sales=second_sales_csv, expenses=in_range_expenses_csv),
        headers=headers,
    )
    assert second_response.status_code == 202
    second_upload_session_id = second_response.json()["uploadSessionId"]

    with TestSessionLocal() as db:
        second_report = db.query(Report).filter(Report.upload_session_id == second_upload_session_id).one()
        assert second_report.status == "COMPLETED"
        assert str(second_report.period_start) == "2026-01-05"
        assert str(second_report.period_end) == "2026-01-20"

        sales_in_period = (
            db.query(Sale)
            .filter(
                Sale.business_id == business_id,
                Sale.sale_date.between(second_report.period_start, second_report.period_end),
            )
            .all()
        )
        # "Rice" came from the FIRST upload_session -- proves the second
        # report's query pulled it in by date range, not by upload_session_id.
        assert {s.product_name for s in sales_in_period} == {"Rice", "Beans", "Cassava"}


def test_delete_upload_removes_children(real_client, business_id):
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}

    response = real_client.post(
        f"/api/v1/businesses/{business_id}/uploads/", files=_upload_files(), headers=headers
    )
    upload_session_id = response.json()["uploadSessionId"]

    delete_response = real_client.delete(
        f"/api/v1/businesses/{business_id}/uploads/{upload_session_id}", headers=headers
    )
    assert delete_response.status_code == 204

    with TestSessionLocal() as db:
        assert db.get(UploadSession, upload_session_id) is None
        assert db.query(Sale).filter(Sale.upload_session_id == upload_session_id).count() == 0
        assert db.query(ColumnMapping).filter(ColumnMapping.upload_session_id == upload_session_id).count() == 0
