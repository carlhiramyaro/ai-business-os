"""normalize product name casing

Converges existing casing/spacing variants of the same product onto one
spelling per business ("Rice" + "rice" -> "Rice"), so `GROUP BY
product_name` (top products, inventory matching) stops splitting a single
product into several.

Data-only: no schema change, nothing added or dropped. New rows are kept
consistent by `canonicalize_product_name` at the `ingest_rows()` boundary
(app/entities.py); this fixes the rows that predate it. See
docs/decisions.md [2026-08-27].

Winner per business+normalized-name is the EARLIEST-created spelling,
matching the "first-seen casing" rule the customer/supplier resolvers
already use, so the backfill and the runtime path agree. `sales` has no
created_at, so it orders by the row's own date then id -- any deterministic
tie-break would do; what matters is that one spelling wins and it is stable
across reruns.

The normalization expression here MUST stay in sync with
`normalize_entity_name` / `_normalized_sql` in app/entities.py: trim,
collapse internal whitespace, lowercase.

Revision ID: c8f2a91d40b7
Revises: b1c4d7e92f30
Create Date: 2026-08-27

"""

from alembic import op

revision = "c8f2a91d40b7"
down_revision = "b1c4d7e92f30"
branch_labels = None
depends_on = None

_NORMALIZED = "lower(regexp_replace(btrim({col}), '\\s+', ' ', 'g'))"


def _backfill(table: str, order_by: str) -> str:
    normalized = _NORMALIZED.format(col="product_name")
    return f"""
        WITH canonical AS (
            SELECT DISTINCT ON (business_id, {normalized})
                   business_id,
                   {normalized} AS norm,
                   btrim(regexp_replace(product_name, '\\s+', ' ', 'g')) AS winner
            FROM {table}
            WHERE product_name IS NOT NULL AND btrim(product_name) <> ''
            ORDER BY business_id, {normalized}, {order_by}
        )
        UPDATE {table} t
        SET product_name = c.winner
        FROM canonical c
        WHERE t.business_id = c.business_id
          AND {normalized.replace("product_name", "t.product_name")} = c.norm
          AND t.product_name IS DISTINCT FROM c.winner
    """


def upgrade() -> None:
    op.execute(_backfill("sales", "sale_date, id"))
    op.execute(_backfill("inventory", "id"))


def downgrade() -> None:
    # Irreversible by nature: the original per-row casing is not recorded
    # anywhere once overwritten, and restoring it would mean re-splitting
    # products that are now correctly merged. Deliberately a no-op rather
    # than a lossy guess -- consistent with the currency migration's
    # reasoning in b1c4d7e92f30.
    pass
