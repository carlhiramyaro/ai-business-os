"""reparse document dates dayfirst

Re-derives dates for rows ingested from photographed documents, using the
DD/MM reading this product's market writes.

`pd.to_datetime` defaulted to the US MM/DD reading, so a receipt saying
06/08/2022 was stored as 8 June instead of 6 August -- silently, and for
roughly 39% of dates (any where both parts are <= 12). See
docs/decisions.md [2026-09-04].

Only document-sourced rows are touched, and only where the re-parsed date
actually differs. The original strings the vision model read are still
held verbatim in `document_extractions.extracted_rows`, which is what makes
this recoverable at all -- CSV-sourced rows are deliberately left alone:
their source files live in S3 rather than the database, so re-deriving them
belongs in a one-off script with the file to hand, not in a migration that
must run anywhere.

Rows are matched within their own upload session by the fields that
identify a line item, so a session whose lines carry different dates is
handled correctly rather than being flattened to one.

Revision ID: e5b93c2a71d4
Revises: d4a71b58e6c2
Create Date: 2026-09-04

"""

import datetime as dt

import sqlalchemy as sa
from alembic import op

revision = "e5b93c2a71d4"
down_revision = "d4a71b58e6c2"
branch_labels = None
depends_on = None

# Matches app/ingestion.py's parse_date_value: ISO first (unambiguous, and
# what the extraction prompt asks for), then day-first slash formats.
_SLASH_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y")

_DATASETS = {
    "expenses": ("expense_date", "expenseDate", ("description", "amount"), ("description", "amount")),
    "sales": ("sale_date", "saleDate", ("product_name", "total_amount"), ("productName", "totalAmount")),
}


def _parse(value):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        pass
    for fmt in _SLASH_FORMATS:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def upgrade() -> None:
    conn = op.get_bind()
    extractions = conn.execute(
        sa.text(
            "SELECT upload_session_id, dataset_type, extracted_rows "
            "FROM document_extractions WHERE dataset_type IN ('expenses', 'sales')"
        )
    ).fetchall()

    for session_id, dataset_type, rows in extractions:
        date_col, date_key, (col_a, col_b), (key_a, key_b) = _DATASETS[dataset_type]
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            corrected = _parse(row.get(date_key))
            if corrected is None:
                continue
            conn.execute(
                sa.text(
                    f"UPDATE {dataset_type} SET {date_col} = :corrected "
                    f"WHERE upload_session_id = :sid "
                    f"AND {col_a} IS NOT DISTINCT FROM :a "
                    f"AND {col_b} = CAST(:b AS numeric) "
                    f"AND {date_col} IS DISTINCT FROM :corrected"
                ),
                {
                    "corrected": corrected,
                    "sid": session_id,
                    "a": row.get(key_a),
                    "b": row.get(key_b),
                },
            )


def downgrade() -> None:
    # Not reversible: the previously-stored (mis-parsed) dates are not
    # recorded anywhere once corrected, and restoring them would mean
    # deliberately re-introducing dates that are wrong for this market.
    # Same reasoning as c8f2a91d40b7's casing backfill.
    pass
