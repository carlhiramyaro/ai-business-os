import uuid

from sqlalchemy.orm import Session

from app.embeddings import generate_embedding
from app.models import Embedding

DEFAULT_TOP_K = 5


def retrieve_relevant_chunks(
    db: Session,
    business_id: uuid.UUID,
    query_text: str,
    top_k: int = DEFAULT_TOP_K,
    source_types: list[str] | None = None,
) -> list[str]:
    """Embeds the query and returns the top_k closest chunks (by cosine
    distance) scoped to this business -- the tenant filter applies here too,
    same as every other business-owned table. source_types optionally
    restricts which embeddings.source_type values are searched (e.g. v0.4
    slice 3's insight narration wants only "business_fact" rows, not report
    content) -- None (the default) searches every source type, preserving
    chat's existing unfiltered behavior."""
    query_vector = generate_embedding(query_text)

    filters = [Embedding.business_id == business_id, Embedding.vector.isnot(None)]
    if source_types is not None:
        filters.append(Embedding.source_type.in_(source_types))

    rows = (
        db.query(Embedding)
        .filter(*filters)
        .order_by(Embedding.vector.cosine_distance(query_vector))
        .limit(top_k)
        .all()
    )
    return [row.chunk_text for row in rows]
