"""add unique index on refresh_tokens token_hash

Revision ID: f10f9c18795a
Revises: 6930a3469643
Create Date: 2026-08-01 14:21:20.250344

v0.5 slice 3 (multi-tenant hardening, docs/decisions.md [2026-08-01]):
/auth/refresh and /auth/logout both look up a RefreshToken by token_hash,
which had no index at all -- a sequential scan that only gets worse as the
table grows. Unique, not just indexed: token_hash is a SHA-256 digest of a
32-byte random token (app/security.py's generate_refresh_token), so a
collision is a "should never happen" invariant worth enforcing at the
database level, not just assumed in application code.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f10f9c18795a'
down_revision: Union[str, Sequence[str], None] = '6930a3469643'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        op.f('ix_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_refresh_tokens_token_hash'), table_name='refresh_tokens')
