import uuid

import app.retrieval as retrieval_module
from app.models import Business, Embedding, User
from app.security import hash_password


def make_vector(active_index: int, dim: int = 1536) -> list[float]:
    vector = [0.0] * dim
    vector[active_index] = 1.0
    return vector


def _seed_business(db_session):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.flush()
    business = Business(owner_id=user.id, business_name="Retrieval Test Co")
    db_session.add(business)
    db_session.flush()
    return business


def test_retrieve_relevant_chunks_returns_closest_match_first(monkeypatch, db_session):
    business = _seed_business(db_session)

    db_session.add(
        Embedding(
            business_id=business.id,
            source_type="report_section",
            source_id=uuid.uuid4(),
            chunk_text="chunk A",
            vector=make_vector(0),
        )
    )
    db_session.add(
        Embedding(
            business_id=business.id,
            source_type="report_section",
            source_id=uuid.uuid4(),
            chunk_text="chunk B",
            vector=make_vector(1),
        )
    )
    db_session.add(
        Embedding(
            business_id=business.id,
            source_type="report_section",
            source_id=uuid.uuid4(),
            chunk_text="chunk C",
            vector=make_vector(2),
        )
    )
    db_session.commit()

    monkeypatch.setattr(retrieval_module, "generate_embedding", lambda text: make_vector(1))

    results = retrieval_module.retrieve_relevant_chunks(db_session, business.id, "irrelevant query text", top_k=2)
    assert results[0] == "chunk B"
    assert len(results) == 2


def test_retrieve_relevant_chunks_is_scoped_to_business(monkeypatch, db_session):
    business_a = _seed_business(db_session)
    business_b = _seed_business(db_session)

    db_session.add(
        Embedding(
            business_id=business_a.id,
            source_type="report_section",
            source_id=uuid.uuid4(),
            chunk_text="business A's data",
            vector=make_vector(0),
        )
    )
    db_session.add(
        Embedding(
            business_id=business_b.id,
            source_type="report_section",
            source_id=uuid.uuid4(),
            chunk_text="business B's data",
            vector=make_vector(0),
        )
    )
    db_session.commit()

    monkeypatch.setattr(retrieval_module, "generate_embedding", lambda text: make_vector(0))

    results = retrieval_module.retrieve_relevant_chunks(db_session, business_a.id, "query", top_k=5)
    assert results == ["business A's data"]


def test_retrieve_relevant_chunks_filters_by_source_types(monkeypatch, db_session):
    """v0.4 slice 3: insight narration wants only business_fact rows, not
    report content -- source_types=None (chat's default) stays unfiltered."""
    business = _seed_business(db_session)

    db_session.add(
        Embedding(
            business_id=business.id,
            source_type="report_section",
            source_id=uuid.uuid4(),
            chunk_text="report content",
            vector=make_vector(0),
        )
    )
    db_session.add(
        Embedding(
            business_id=business.id,
            source_type="business_fact",
            source_id=uuid.uuid4(),
            chunk_text="December is our peak season",
            vector=make_vector(0),
        )
    )
    db_session.commit()

    monkeypatch.setattr(retrieval_module, "generate_embedding", lambda text: make_vector(0))

    unfiltered = retrieval_module.retrieve_relevant_chunks(db_session, business.id, "query", top_k=5)
    assert set(unfiltered) == {"report content", "December is our peak season"}

    filtered = retrieval_module.retrieve_relevant_chunks(
        db_session, business.id, "query", top_k=5, source_types=["business_fact"]
    )
    assert filtered == ["December is our peak season"]
