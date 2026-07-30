import uuid

from app.business_facts import delete_fact, remember_fact
from app.models import Business, BusinessFact, Embedding, User
from app.security import hash_password


def _seed_business(db_session):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.flush()
    business = Business(owner_id=user.id, business_name="Memory Test Co")
    db_session.add(business)
    db_session.flush()
    return business


def test_remember_fact_creates_fact_and_embedding(monkeypatch, db_session):
    business = _seed_business(db_session)
    monkeypatch.setattr("app.embedding_generation.generate_embedding", lambda text: [0.0] * 1536)

    fact = remember_fact(db_session, business.id, "December is our peak season")

    assert fact.content == "December is our peak season"
    assert fact.source == "chat"

    embedding = db_session.query(Embedding).filter(Embedding.source_id == fact.id).one()
    assert embedding.source_type == "business_fact"
    assert embedding.business_id == business.id
    assert embedding.chunk_text == "December is our peak season"


def test_delete_fact_removes_fact_and_embedding(monkeypatch, db_session):
    business = _seed_business(db_session)
    monkeypatch.setattr("app.embedding_generation.generate_embedding", lambda text: [0.0] * 1536)
    fact = remember_fact(db_session, business.id, "Supplier X always delivers late")
    fact_id = fact.id

    delete_fact(db_session, fact)
    db_session.flush()

    assert db_session.query(BusinessFact).filter(BusinessFact.id == fact_id).first() is None
    assert db_session.query(Embedding).filter(Embedding.source_id == fact_id).first() is None
