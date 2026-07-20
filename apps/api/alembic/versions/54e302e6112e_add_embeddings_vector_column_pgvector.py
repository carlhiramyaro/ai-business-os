"""add embeddings.vector column (pgvector)

Revision ID: 54e302e6112e
Revises: 49c2cf41c1c0
Create Date: 2026-07-17 14:08:15.352582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = '54e302e6112e'
down_revision: Union[str, Sequence[str], None] = '49c2cf41c1c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column('embeddings', sa.Column('vector', pgvector.sqlalchemy.Vector(dim=1536), nullable=True))
    op.execute(
        "CREATE INDEX ix_embeddings_vector_hnsw_cosine ON embeddings "
        "USING hnsw (vector vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_hnsw_cosine")
    op.drop_column('embeddings', 'vector')
