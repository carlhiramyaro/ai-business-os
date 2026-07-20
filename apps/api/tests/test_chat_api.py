import app.routers.chat as chat_router


def fake_retrieve_relevant_chunks(db, business_id, query_text, top_k=5):
    return ["The business had $500 in revenue last month.", "Inventory is low on Rice."]


def fake_generate_chat_answer(question, context_chunks, history):
    return f"Answer based on {len(context_chunks)} chunks and {len(history)} prior messages."


def register_and_login(client, email):
    client.post(
        "/api/v1/auth/register",
        json={"fullName": "Test User", "email": email, "password": "password123"},
    )
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return login_response.json()["accessToken"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def _setup(monkeypatch, client, email):
    monkeypatch.setattr(chat_router, "retrieve_relevant_chunks", fake_retrieve_relevant_chunks)
    monkeypatch.setattr(chat_router, "generate_chat_answer", fake_generate_chat_answer)

    token = register_and_login(client, email)
    business_id = client.post(
        "/api/v1/businesses/", json={"businessName": "Chat Test Co"}, headers=auth_header(token)
    ).json()["id"]
    return token, business_id


def test_create_conversation(monkeypatch, client):
    token, business_id = _setup(monkeypatch, client, "chat1@example.com")

    response = client.post(f"/api/v1/businesses/{business_id}/chat/", headers=auth_header(token))
    assert response.status_code == 201
    assert "conversationId" in response.json()


def test_send_message_returns_answer_and_stores_both_messages(monkeypatch, client):
    token, business_id = _setup(monkeypatch, client, "chat2@example.com")
    conversation_id = client.post(
        f"/api/v1/businesses/{business_id}/chat/", headers=auth_header(token)
    ).json()["conversationId"]

    response = client.post(
        f"/api/v1/businesses/{business_id}/chat/{conversation_id}/messages",
        json={"message": "Why is profit decreasing?"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "Answer based on 2 chunks and 0 prior messages."

    history = client.get(
        f"/api/v1/businesses/{business_id}/chat/{conversation_id}", headers=auth_header(token)
    ).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][0]["content"] == "Why is profit decreasing?"


def test_second_message_includes_prior_history(monkeypatch, client):
    token, business_id = _setup(monkeypatch, client, "chat3@example.com")
    conversation_id = client.post(
        f"/api/v1/businesses/{business_id}/chat/", headers=auth_header(token)
    ).json()["conversationId"]

    client.post(
        f"/api/v1/businesses/{business_id}/chat/{conversation_id}/messages",
        json={"message": "First question"},
        headers=auth_header(token),
    )
    second = client.post(
        f"/api/v1/businesses/{business_id}/chat/{conversation_id}/messages",
        json={"message": "Second question"},
        headers=auth_header(token),
    )
    # 2 prior messages (first question + its answer) by the time the second question is asked
    assert second.json()["answer"] == "Answer based on 2 chunks and 2 prior messages."


def test_chat_forbidden_for_non_owner(monkeypatch, client):
    token, business_id = _setup(monkeypatch, client, "chat4@example.com")
    conversation_id = client.post(
        f"/api/v1/businesses/{business_id}/chat/", headers=auth_header(token)
    ).json()["conversationId"]

    other_token = register_and_login(client, "intruder_chat@example.com")
    response = client.get(
        f"/api/v1/businesses/{business_id}/chat/{conversation_id}", headers=auth_header(other_token)
    )
    assert response.status_code == 403


def test_delete_conversation_removes_messages(monkeypatch, client):
    token, business_id = _setup(monkeypatch, client, "chat5@example.com")
    conversation_id = client.post(
        f"/api/v1/businesses/{business_id}/chat/", headers=auth_header(token)
    ).json()["conversationId"]
    client.post(
        f"/api/v1/businesses/{business_id}/chat/{conversation_id}/messages",
        json={"message": "Hello"},
        headers=auth_header(token),
    )

    delete_response = client.delete(
        f"/api/v1/businesses/{business_id}/chat/{conversation_id}", headers=auth_header(token)
    )
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/businesses/{business_id}/chat/{conversation_id}", headers=auth_header(token))
    assert get_response.status_code == 404
