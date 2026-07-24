"""add document extractions table

Revision ID: e3851ec73ac3
Revises: bb0084e5c354
Create Date: 2026-07-24 13:35:51.320414

v0.3 document processing (docs/roadmap.md, docs/decisions.md
[2026-07-24]): a new table, not a column addition, so purely additive.
document_extractions is the document-era sibling of column_mappings --
holds a photographed receipt/invoice's vision-extracted rows pending user
review, before app.ingestion.ingest_rows turns them into real sales/
inventory/expenses rows. One row per document upload_session (unique FK).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e3851ec73ac3'
down_revision: Union[str, Sequence[str], None] = 'bb0084e5c354'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'document_extractions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'upload_session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('upload_sessions.id'),
            nullable=False,
        ),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False),
        sa.Column('dataset_type', sa.String(), nullable=False),
        sa.Column('extracted_rows', postgresql.JSONB(), nullable=False),
        sa.Column('overall_confidence', sa.Numeric(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('upload_session_id', name='uq_document_extractions_upload_session_id'),
    )
    op.create_index(
        op.f('ix_document_extractions_upload_session_id'), 'document_extractions', ['upload_session_id']
    )
    op.create_index(op.f('ix_document_extractions_business_id'), 'document_extractions', ['business_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_document_extractions_business_id'), table_name='document_extractions')
    op.drop_index(op.f('ix_document_extractions_upload_session_id'), table_name='document_extractions')
    op.drop_table('document_extractions')
