"""generalize upload sessions source type

Revision ID: 3abc4bd09414
Revises: 3ba371cf2741
Create Date: 2026-07-24 13:11:25.256338

v0.3 (see docs/roadmap.md, docs/decisions.md [2026-07-24]): upload_sessions
generalizes from "CSV upload session" to "ingestion source" so manual
entries and photographed documents get one too (provenance + the existing
status/review machinery), alongside CSV uploads. Additive only: a new
source_type column (nullable -> backfilled 'csv' for all existing rows ->
NOT NULL), the three *_file_url columns relaxed to nullable (manual/
document sessions have none), and a new nullable document_url. Table/
column names are kept as-is per the frozen-schema rule even though they
now read as a slight misnomer for non-CSV sessions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3abc4bd09414'
down_revision: Union[str, Sequence[str], None] = '3ba371cf2741'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('upload_sessions', sa.Column('source_type', sa.String(), nullable=True))
    op.add_column('upload_sessions', sa.Column('document_url', sa.String(), nullable=True))

    op.execute("UPDATE upload_sessions SET source_type = 'csv'")

    op.alter_column('upload_sessions', 'source_type', nullable=False)
    op.alter_column('upload_sessions', 'sales_file_url', existing_type=sa.String(), nullable=True)
    op.alter_column('upload_sessions', 'inventory_file_url', existing_type=sa.String(), nullable=True)
    op.alter_column('upload_sessions', 'expenses_file_url', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE upload_sessions SET sales_file_url = '' WHERE sales_file_url IS NULL")
    op.execute("UPDATE upload_sessions SET inventory_file_url = '' WHERE inventory_file_url IS NULL")
    op.execute("UPDATE upload_sessions SET expenses_file_url = '' WHERE expenses_file_url IS NULL")
    op.alter_column('upload_sessions', 'expenses_file_url', existing_type=sa.String(), nullable=False)
    op.alter_column('upload_sessions', 'inventory_file_url', existing_type=sa.String(), nullable=False)
    op.alter_column('upload_sessions', 'sales_file_url', existing_type=sa.String(), nullable=False)
    op.drop_column('upload_sessions', 'document_url')
    op.drop_column('upload_sessions', 'source_type')
