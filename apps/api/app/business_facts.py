"""v0.4 slice 3 -- write/delete for durable per-business facts (roadmap.md
"Business memory v1"). Both functions deliberately don't commit: callers
(app/chat_generation.py via the chat router, app/routers/memory.py) commit
once, alongside whatever else is in their transaction -- same precedent as
app/entities.py's get-or-create helpers.
"""

import uuid

from sqlalchemy.orm import Session

from app.embedding_generation import delete_embedding_for_fact, generate_embedding_for_fact
from app.models import BusinessFact


def remember_fact(db: Session, business_id: uuid.UUID, content: str, source: str = "chat") -> BusinessFact:
    fact = BusinessFact(business_id=business_id, content=content, source=source)
    db.add(fact)
    db.flush()  # assigns fact.id before the embedding row references it
    generate_embedding_for_fact(db, business_id, fact)
    # Callers may use autoflush=False sessions (see app/ingestion.py's
    # content_hash comment for the same reasoning) -- flush explicitly so
    # the new Embedding row is visible to any query run immediately after.
    db.flush()
    return fact


def delete_fact(db: Session, fact: BusinessFact) -> None:
    delete_embedding_for_fact(db, fact.id)
    db.delete(fact)
