import uuid

from app.models import Business, BusinessFact, Embedding


def register_and_login(client, email):
    client.post("/api/v1/auth/register", json={"fullName": "Test User", "email": email, "password": "password123"})
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return login_response.json()["accessToken"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_memory_list_and_delete(monkeypatch, client, db_session):
    monkeypatch.setattr("app.embedding_generation.generate_embedding", lambda text: [0.0] * 1536)
    token = register_and_login(client, f"{uuid.uuid4()}@example.com")
    created = client.post(
        "/api/v1/businesses/", json={"businessName": "Memory Co"}, headers=auth_header(token)
    ).json()
    business_id = created["id"]
    business = db_session.get(Business, business_id)

    from app.business_facts import remember_fact

    fact = remember_fact(db_session, business.id, "December is our peak season")
    db_session.commit()

    list_response = client.get(f"/api/v1/businesses/{business_id}/memory/", headers=auth_header(token))
    assert list_response.status_code == 200
    body = list_response.json()
    assert len(body) == 1
    assert body[0]["content"] == "December is our peak season"
    assert body[0]["source"] == "chat"

    delete_response = client.delete(
        f"/api/v1/businesses/{business_id}/memory/{fact.id}", headers=auth_header(token)
    )
    assert delete_response.status_code == 204

    assert db_session.query(BusinessFact).filter(BusinessFact.id == fact.id).first() is None
    assert db_session.query(Embedding).filter(Embedding.source_id == fact.id).first() is None

    empty_list = client.get(f"/api/v1/businesses/{business_id}/memory/", headers=auth_header(token))
    assert empty_list.json() == []


def test_memory_scoped_to_owning_business(client, db_session):
    token_a = register_and_login(client, f"{uuid.uuid4()}@example.com")
    token_b = register_and_login(client, f"{uuid.uuid4()}@example.com")
    business_a = client.post(
        "/api/v1/businesses/", json={"businessName": "Business A"}, headers=auth_header(token_a)
    ).json()

    response = client.get(f"/api/v1/businesses/{business_a['id']}/memory/", headers=auth_header(token_b))
    assert response.status_code == 403
