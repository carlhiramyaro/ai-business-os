"""add upload sessions duplicate warning flag

Revision ID: bb0084e5c354
Revises: dacab68b1e75
Create Date: 2026-07-24 13:14:27.357579

v0.3 dedup safeguard (docs/roadmap.md, docs/decisions.md [2026-07-24]):
whether THIS session's ingestion detected content_hash collisions against
rows that existed before it ran is a point-in-time fact, not something
reconstructable later by querying current hash collisions (a later,
unrelated upload could introduce a matching hash and falsely implicate an
earlier session) -- so unlike `progress`/`businessHealth` (derived at read
time, decisions.md [2026-07-12]), this one has to be persisted by the
Celery task at ingestion time. Defaults false for existing rows, meaning
"not evaluated" (dedup detection didn't exist yet), which is accurate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb0084e5c354'
down_revision: Union[str, Sequence[str], None] = 'dacab68b1e75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'upload_sessions',
        sa.Column('duplicate_warning', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('upload_sessions', 'duplicate_warning', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('upload_sessions', 'duplicate_warning')
