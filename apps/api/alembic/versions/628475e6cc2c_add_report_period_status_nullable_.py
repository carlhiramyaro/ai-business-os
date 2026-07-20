"""add report period status nullable upload session

Revision ID: 628475e6cc2c
Revises: 54e302e6112e
Create Date: 2026-07-20 10:08:21.500291

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '628475e6cc2c'
down_revision: Union[str, Sequence[str], None] = '54e302e6112e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('reports', sa.Column('period_start', sa.Date(), nullable=True))
    op.add_column('reports', sa.Column('period_end', sa.Date(), nullable=True))
    op.add_column('reports', sa.Column('status', sa.String(), nullable=True))
    op.alter_column('reports', 'upload_session_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    # Backfill from the dates of the sales/expenses rows tied to each report's
    # (pre-existing, single) upload session; fall back to created_at's date if
    # that upload session has no dated rows.
    op.execute("""
        UPDATE reports r
        SET period_start = COALESCE(
                (SELECT MIN(d) FROM (
                    SELECT sale_date AS d FROM sales
                     WHERE upload_session_id = r.upload_session_id AND sale_date IS NOT NULL
                    UNION ALL
                    SELECT expense_date AS d FROM expenses
                     WHERE upload_session_id = r.upload_session_id AND expense_date IS NOT NULL
                ) dates),
                r.created_at::date
            ),
            period_end = COALESCE(
                (SELECT MAX(d) FROM (
                    SELECT sale_date AS d FROM sales
                     WHERE upload_session_id = r.upload_session_id AND sale_date IS NOT NULL
                    UNION ALL
                    SELECT expense_date AS d FROM expenses
                     WHERE upload_session_id = r.upload_session_id AND expense_date IS NOT NULL
                ) dates),
                r.created_at::date
            ),
            status = 'COMPLETED'
    """)

    op.alter_column('reports', 'period_start', nullable=False)
    op.alter_column('reports', 'period_end', nullable=False)
    op.alter_column('reports', 'status', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('reports', 'upload_session_id', existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column('reports', 'status')
    op.drop_column('reports', 'period_end')
    op.drop_column('reports', 'period_start')
