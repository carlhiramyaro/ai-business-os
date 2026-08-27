"""default business currency to GHS

Backfills existing NULL `businesses.currency` values, then gives the column
a server default and a NOT NULL constraint.

Follows the project's additive convention (CLAUDE.md): backfill first, then
constrain -- never the reverse, which would fail on the existing rows. The
column already existed and is not being retyped or renamed; only its
default/nullability changes, so existing data is preserved.

Why GHS: Ledger's market is African SMEs, Ghana first
(docs/product-vision.md). A NULL currency silently degraded the chat
agent's system prompt (app/chat_generation.py) to "amounts are in the
business's local currency", so answers came back as bare unlabelled
numbers. See docs/decisions.md [2026-08-27].

Revision ID: b1c4d7e92f30
Revises: 6cee3eac28bd
Create Date: 2026-08-27

"""

import sqlalchemy as sa
from alembic import op

revision = "b1c4d7e92f30"
down_revision = "6cee3eac28bd"
branch_labels = None
depends_on = None

DEFAULT_CURRENCY = "GHS"


def upgrade() -> None:
    # Existing rows first -- the NOT NULL below fails if any remain NULL.
    # Empty strings are treated as unset too: they carry no more meaning
    # than NULL and would defeat the constraint.
    op.execute(
        f"UPDATE businesses SET currency = '{DEFAULT_CURRENCY}' "
        "WHERE currency IS NULL OR btrim(currency) = ''"
    )
    op.alter_column(
        "businesses",
        "currency",
        existing_type=sa.String(),
        nullable=False,
        server_default=DEFAULT_CURRENCY,
    )


def downgrade() -> None:
    # Only the constraint and default are reversible. The backfilled values
    # are deliberately NOT reverted to NULL: this migration cannot tell a
    # row it defaulted from one an owner explicitly set to GHS, and
    # blanking a real setting is worse than leaving a correct one in place.
    op.alter_column(
        "businesses",
        "currency",
        existing_type=sa.String(),
        nullable=True,
        server_default=None,
    )
