"""add customers suppliers entities

Revision ID: 3ba371cf2741
Revises: 585b412b0f84
Create Date: 2026-07-21 13:52:37.265828

First-class customer/supplier entities (v0.2, see decisions.md
[2026-07-21]). Additive only: two new tables, three new nullable columns;
existing sales.customer_name / inventory.supplier string columns are kept
as the raw as-ingested values. Backfill derives entities from those
strings — the SQL normalization (trim, collapse whitespace, lowercase)
must match app/entities.py's normalize_entity_name.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3ba371cf2741'
down_revision: Union[str, Sequence[str], None] = '585b412b0f84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# LOWER + trim + collapse internal whitespace, matching normalize_entity_name
_NORMALIZE = "LOWER(REGEXP_REPLACE(BTRIM({col}), '\\s+', ' ', 'g'))"
_DISPLAY = "REGEXP_REPLACE(BTRIM({col}), '\\s+', ' ', 'g')"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'customers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('normalized_name', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('business_id', 'normalized_name', name='uq_customers_business_normalized_name'),
    )
    op.create_index(op.f('ix_customers_business_id'), 'customers', ['business_id'])

    op.create_table(
        'suppliers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('normalized_name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('business_id', 'normalized_name', name='uq_suppliers_business_normalized_name'),
    )
    op.create_index(op.f('ix_suppliers_business_id'), 'suppliers', ['business_id'])

    op.add_column('sales', sa.Column('customer_phone', sa.String(), nullable=True))
    op.add_column(
        'sales',
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('customers.id'), nullable=True),
    )
    op.create_index(op.f('ix_sales_customer_id'), 'sales', ['customer_id'])

    op.add_column(
        'inventory',
        sa.Column('supplier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('suppliers.id'), nullable=True),
    )
    op.create_index(op.f('ix_inventory_supplier_id'), 'inventory', ['supplier_id'])

    # Backfill: one entity per (business, normalized name); display name is
    # the alphabetically-first cleaned variant (deterministic).
    norm_customer = _NORMALIZE.format(col='customer_name')
    op.execute(f"""
        INSERT INTO customers (id, business_id, name, normalized_name)
        SELECT gen_random_uuid(), business_id,
               MIN({_DISPLAY.format(col='customer_name')}),
               {norm_customer}
        FROM sales
        WHERE customer_name IS NOT NULL AND BTRIM(customer_name) <> ''
        GROUP BY business_id, {norm_customer}
    """)
    op.execute(f"""
        UPDATE sales s
        SET customer_id = c.id
        FROM customers c
        WHERE s.customer_name IS NOT NULL AND BTRIM(s.customer_name) <> ''
          AND c.business_id = s.business_id
          AND c.normalized_name = {_NORMALIZE.format(col='s.customer_name')}
    """)

    norm_supplier = _NORMALIZE.format(col='supplier')
    op.execute(f"""
        INSERT INTO suppliers (id, business_id, name, normalized_name)
        SELECT gen_random_uuid(), business_id,
               MIN({_DISPLAY.format(col='supplier')}),
               {norm_supplier}
        FROM inventory
        WHERE supplier IS NOT NULL AND BTRIM(supplier) <> ''
        GROUP BY business_id, {norm_supplier}
    """)
    op.execute(f"""
        UPDATE inventory i
        SET supplier_id = sup.id
        FROM suppliers sup
        WHERE i.supplier IS NOT NULL AND BTRIM(i.supplier) <> ''
          AND sup.business_id = i.business_id
          AND sup.normalized_name = {_NORMALIZE.format(col='i.supplier')}
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_inventory_supplier_id'), table_name='inventory')
    op.drop_column('inventory', 'supplier_id')
    op.drop_index(op.f('ix_sales_customer_id'), table_name='sales')
    op.drop_column('sales', 'customer_id')
    op.drop_column('sales', 'customer_phone')
    op.drop_index(op.f('ix_suppliers_business_id'), table_name='suppliers')
    op.drop_table('suppliers')
    op.drop_index(op.f('ix_customers_business_id'), table_name='customers')
    op.drop_table('customers')
