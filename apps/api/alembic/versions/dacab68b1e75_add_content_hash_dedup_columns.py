"""add content hash dedup columns

Revision ID: dacab68b1e75
Revises: 3abc4bd09414
Create Date: 2026-07-24 13:12:21.614894

v0.3 dedup/idempotency safeguard (docs/roadmap.md, docs/decisions.md
[2026-07-24]): a nullable, indexed content_hash on sales/inventory/expenses
lets app/ingestion.py detect (never silently drop) rows that look like a
repeat of one already ingested for the business, across any producer (CSV/
manual/document). Hash = sha256(business_id | dataset_type | natural-key
fields), NULL-coalesced to the literal string 'None' to exactly match
Python's `str(record_kwargs.get(field))` for a missing field (see
app/ingestion.py's _content_hash) -- same "SQL backfill must mirror the
Python function" discipline as migration 3ba371cf2741's entity backfill.
Uses PostgreSQL's built-in sha256(bytea) (core since PG 11, no extension
needed) + encode(...,'hex') to match hashlib.sha256(...).hexdigest().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dacab68b1e75'
down_revision: Union[str, Sequence[str], None] = '3abc4bd09414'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _hash_expr(dataset_type: str, fields: list[str]) -> str:
    parts = [f"business_id::text", f"'{dataset_type}'"] + [f"COALESCE({f}::text, 'None')" for f in fields]
    joined = " || '|' || ".join(parts)
    return f"encode(sha256(({joined})::bytea), 'hex')"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('sales', sa.Column('content_hash', sa.String(), nullable=True))
    op.create_index(op.f('ix_sales_content_hash'), 'sales', ['content_hash'])
    op.add_column('inventory', sa.Column('content_hash', sa.String(), nullable=True))
    op.create_index(op.f('ix_inventory_content_hash'), 'inventory', ['content_hash'])
    op.add_column('expenses', sa.Column('content_hash', sa.String(), nullable=True))
    op.create_index(op.f('ix_expenses_content_hash'), 'expenses', ['content_hash'])

    op.execute(f"UPDATE sales SET content_hash = {_hash_expr('sales', ['sale_date', 'product_name', 'quantity', 'total_amount'])}")
    op.execute(f"UPDATE expenses SET content_hash = {_hash_expr('expenses', ['expense_date', 'category', 'vendor', 'amount'])}")
    op.execute(f"UPDATE inventory SET content_hash = {_hash_expr('inventory', ['product_name', 'quantity', 'cost_price'])}")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_expenses_content_hash'), table_name='expenses')
    op.drop_column('expenses', 'content_hash')
    op.drop_index(op.f('ix_inventory_content_hash'), table_name='inventory')
    op.drop_column('inventory', 'content_hash')
    op.drop_index(op.f('ix_sales_content_hash'), table_name='sales')
    op.drop_column('sales', 'content_hash')
