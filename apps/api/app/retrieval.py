import uuid

from sqlalchemy.orm import Session

from app.embeddings import generate_embedding
from app.models import Embedding

DEFAULT_TOP_K = 5


def retrieve_relevant_chunks(db: Session, business_id: uuid.UUID, query_text: str, top_k: int = DEFAULT_TOP_K) -> list[str]:
    """Embeds the query and returns the top_k closest chunks (by cosine
    distance) scoped to this business -- the tenant filter applies here too,
    same as every other business-owned table."""
    query_vector = generate_embedding(query_text)

    rows = (
        db.query(Embedding)
        .filter(Embedding.business_id == business_id, Embedding.vector.isnot(None))
        .order_by(Embedding.vector.cosine_distance(query_vector))
        .limit(top_k)
        .all()
    )
    return [row.chunk_text for row in rows]
