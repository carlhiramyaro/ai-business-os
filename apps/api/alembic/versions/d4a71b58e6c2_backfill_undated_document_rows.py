"""backfill undated document rows

Gives a date to sales/expenses rows that reached the database without one,
using their upload session's own upload date.

Undated rows are invisible to every date-range query -- reports, "how did I
do this month", any period-scoped profit figure -- so the money sits in the
table but vanishes from the analysis, with totals that still look
plausible. Found in live v0.6 testing: a photographed Costco receipt
produced four expenses totalling 58.46, none of which appeared in any
August report. See docs/decisions.md [2026-08-31].

Data-only: no schema change. New rows are kept dated by
app/document_extraction.py (the vision prompt now reads the document's own
header date, and commit_document_extraction falls back to the upload date
when it cannot be read); this fixes rows that predate that.

Scoped to rows whose upload session is a `document` one. A CSV-ingested row
without a date means the owner's own file had no date in it -- inventing
one there would be putting words in their spreadsheet's mouth, and the CSV
path has always behaved that way. Only the document path silently differed
from its typed sibling, which defaults to today.

Revision ID: d4a71b58e6c2
Revises: c8f2a91d40b7
Create Date: 2026-08-31

"""

from alembic import op

revision = "d4a71b58e6c2"
down_revision = "c8f2a91d40b7"
branch_labels = None
depends_on = None


def _backfill(table: str, date_column: str) -> str:
    return f"""
        UPDATE {table} t
        SET {date_column} = u.uploaded_at::date
        FROM upload_sessions u
        WHERE u.id = t.upload_session_id
          AND u.source_type = 'document'
          AND t.{date_column} IS NULL
    """


def upgrade() -> None:
    op.execute(_backfill("expenses", "expense_date"))
    op.execute(_backfill("sales", "sale_date"))


def downgrade() -> None:
    # Not reversible: which rows were NULL before is not recorded anywhere
    # once filled, and re-NULLing every document-sourced row would also
    # blank dates that were read correctly from the receipt. Leaving a
    # reasonable date in place is strictly better than restoring
    # invisibility -- same reasoning as b1c4d7e92f30's currency backfill.
    pass
