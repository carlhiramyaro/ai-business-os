import io
import uuid

import pytest
from fastapi.testclient import TestClient

import app.document_extraction as document_extraction
import app.routers.documents as documents_router
import app.tasks as tasks
from app.database import get_db
from app.models import (
    Business,
    Customer,
    DocumentExtraction,
    Expense,
    Sale,
    Supplier,
    UploadSession,
    User,
)
from app.security import create_access_token, hash_password
from main import app
from tests.conftest import TestSessionLocal

# Same rationale as tests/test_uploads.py's module docstring: the Celery
# task opens its own DB connection via app.tasks.SessionLocal, so this
# module commits for real against ai_business_os_test rather than using the
# SAVEPOINT-rollback client/db_session fixtures.

FAKE_S3: dict[str, bytes] = {}
FAKE_IMAGE_BYTES = b"fake-jpeg-bytes"


def fake_upload_fileobj(fileobj, key):
    FAKE_S3[key] = fileobj.read()
    return f"fake://{key}"


def fake_download_fileobj(key):
    return io.BytesIO(FAKE_S3[key])


def fake_call_vision_llm(system_prompt, image_bytes, mime_type):
    return {
        "rows": [
            {"saleDate": "2026-04-01", "productName": "Rice", "quantity": 5, "totalAmount": "12.5"},
        ],
        "confidence": 0.9,
    }


@pytest.fixture(autouse=True)
def _patch_storage_and_db(monkeypatch):
    monkeypatch.setattr(documents_router, "upload_fileobj", fake_upload_fileobj)
    # v0.6 slice 4: the S3 download moved from app/tasks.py's
    # extract_document_task into app/document_extraction.py's
    # run_document_extraction (shared with the new WhatsApp photo flow) --
    # patch it where it's actually called now.
    monkeypatch.setattr(document_extraction, "download_fileobj", fake_download_fileobj)
    monkeypatch.setattr(tasks, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(document_extraction, "_call_vision_llm", fake_call_vision_llm)
    FAKE_S3.clear()
    yield
    with TestSessionLocal() as db:
        db.query(DocumentExtraction).delete()
        db.query(Sale).delete()
        db.query(Expense).delete()
        db.query(Customer).delete()
        db.query(Supplier).delete()
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
        business = Business(owner_id=user.id, business_name="Documents Test Co")
        db.add(business)
        db.commit()
        return str(business.id), create_access_token(str(user.id))


def _upload_document(real_client, business_id, headers, dataset_type="sales"):
    return real_client.post(
        f"/api/v1/businesses/{business_id}/documents/",
        data={"datasetType": dataset_type},
        files={"image": ("receipt.jpg", io.BytesIO(FAKE_IMAGE_BYTES), "image/jpeg")},
        headers=headers,
    )


def test_upload_document_extracts_and_needs_review(real_client, business_id):
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}

    response = _upload_document(real_client, business_id, headers)
    assert response.status_code == 202
    session_id = response.json()["uploadSessionId"]

    status_response = real_client.get(f"/api/v1/businesses/{business_id}/documents/{session_id}", headers=headers)
    body = status_response.json()
    assert body["status"] == "NEEDS_REVIEW"
    assert body["datasetType"] == "sales"
    assert body["extractedRows"] == [
        {"saleDate": "2026-04-01", "productName": "Rice", "quantity": 5, "totalAmount": "12.5"}
    ]
    assert body["overallConfidence"] == 0.9

    with TestSessionLocal() as db:
        session = db.get(UploadSession, session_id)
        assert session.source_type == "document"
        assert session.document_url is not None
        # nothing ingested yet -- still pending review
        assert db.query(Sale).filter(Sale.business_id == uuid.UUID(business_id)).count() == 0


def test_edit_rows_then_confirm_ingests_and_completes(real_client, business_id):
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}

    session_id = _upload_document(real_client, business_id, headers).json()["uploadSessionId"]

    patch_response = real_client.patch(
        f"/api/v1/businesses/{business_id}/documents/{session_id}",
        json={
            "extractedRows": [
                {
                    "saleDate": "2026-04-01",
                    "productName": "Rice (corrected)",
                    "quantity": 5,
                    "totalAmount": "12.5",
                    "customerName": "Ama Mensah",
                }
            ]
        },
        headers=headers,
    )
    assert patch_response.json()["extractedRows"][0]["productName"] == "Rice (corrected)"

    confirm_response = real_client.post(
        f"/api/v1/businesses/{business_id}/documents/{session_id}/confirm", headers=headers
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json() == {"status": "COMPLETED", "duplicateWarning": False}

    with TestSessionLocal() as db:
        session = db.get(UploadSession, session_id)
        assert session.status == "COMPLETED"

        sale = db.query(Sale).filter(Sale.upload_session_id == session_id).one()
        assert sale.product_name == "Rice (corrected)"
        assert sale.total_amount == 12.5
        assert sale.sale_date.isoformat() == "2026-04-01"

        customer = db.query(Customer).filter(Customer.business_id == uuid.UUID(business_id)).one()
        assert customer.name == "Ama Mensah"
        assert sale.customer_id == customer.id


def test_confirm_before_extraction_ready_returns_409(real_client, business_id):
    """The Celery task runs eagerly in tests, so to exercise the
    not-ready-yet path we hit confirm on a session with no
    DocumentExtraction row at all (simulating a session created but not
    yet processed)."""
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}

    with TestSessionLocal() as db:
        session = UploadSession(business_id=uuid.UUID(business_id), source_type="document", status="PROCESSING")
        db.add(session)
        db.commit()
        session_id = str(session.id)

    response = real_client.post(f"/api/v1/businesses/{business_id}/documents/{session_id}/confirm", headers=headers)
    assert response.status_code == 409


def test_document_confirm_duplicate_warning(real_client, business_id):
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}

    first_session_id = _upload_document(real_client, business_id, headers).json()["uploadSessionId"]
    real_client.post(f"/api/v1/businesses/{business_id}/documents/{first_session_id}/confirm", headers=headers)

    second_session_id = _upload_document(real_client, business_id, headers).json()["uploadSessionId"]
    confirm_response = real_client.post(
        f"/api/v1/businesses/{business_id}/documents/{second_session_id}/confirm", headers=headers
    )
    assert confirm_response.json()["duplicateWarning"] is True

    with TestSessionLocal() as db:
        assert db.query(Sale).filter(Sale.business_id == uuid.UUID(business_id)).count() == 2


def test_documents_forbidden_for_non_owner(real_client, business_id):
    business_id, token = business_id
    headers = {"Authorization": f"Bearer {token}"}
    session_id = _upload_document(real_client, business_id, headers).json()["uploadSessionId"]

    with TestSessionLocal() as db:
        intruder = User(
            full_name="Intruder", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123")
        )
        db.add(intruder)
        db.commit()
        intruder_token = create_access_token(str(intruder.id))

    response = real_client.get(
        f"/api/v1/businesses/{business_id}/documents/{session_id}",
        headers={"Authorization": f"Bearer {intruder_token}"},
    )
    assert response.status_code == 403
