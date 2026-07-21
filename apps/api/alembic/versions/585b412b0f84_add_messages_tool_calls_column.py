"""add messages tool_calls column

Revision ID: 585b412b0f84
Revises: eed8be674a92
Create Date: 2026-07-21 13:45:06.092970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '585b412b0f84'
down_revision: Union[str, Sequence[str], None] = 'eed8be674a92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add messages.tool_calls — the persisted audit trail of which data
    queries the chat agent ran to produce an assistant message. Nullable
    with no backfill: user messages never have one, and assistant messages
    from before this migration simply predate the trail."""
    op.add_column('messages', sa.Column('tool_calls', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'tool_calls')
