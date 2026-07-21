"""drop inventory sku column

Revision ID: eed8be674a92
Revises: 628475e6cc2c
Create Date: 2026-07-21 11:03:09.443995

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eed8be674a92'
down_revision: Union[str, Sequence[str], None] = '628475e6cc2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('inventory', 'sku')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('inventory', sa.Column('sku', sa.String(), nullable=True))
