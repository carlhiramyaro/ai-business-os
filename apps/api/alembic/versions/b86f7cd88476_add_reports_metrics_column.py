"""add reports metrics column

Revision ID: b86f7cd88476
Revises: e5b93c2a71d4
Create Date: 2026-09-07 11:55:03.241780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b86f7cd88476'
down_revision: Union[str, Sequence[str], None] = 'e5b93c2a71d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add reports.metrics -- the deterministic finance/inventory/marketing/
    operations/forecast figures a report's narration is built from, persisted
    at generation time so a chart never disagrees with the prose next to it
    (docs/decisions.md [2026-09-07]). Nullable with no backfill: reports
    generated before this migration simply predate the figures and render
    text-only, same precedent as messages.tool_calls (585b412b0f84)."""
    op.add_column('reports', sa.Column('metrics', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('reports', 'metrics')
