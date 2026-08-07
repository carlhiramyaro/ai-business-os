import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class PendingEntry(Base):
    """v0.6 slice 3 (roadmap.md "Data entry by message") -- a sale/expense/
    inventory entry the chat agent extracted from a natural-language
    message (e.g. "sold 3 bags of rice at 50 each") but hasn't written to
    sales/expenses/inventory yet. Staged by a propose_*_entry chat tool
    (app/data_entry.py), finalized by confirm_pending_entry or
    cancel_pending_entry -- both also chat tools, called by the model on
    the owner's NEXT message, using ordinary conversation history the way
    it already resolves any other follow-up. No separate confirmation
    state machine outside the existing tool-calling loop.

    `fields` is a snake_case-keyed dict of RAW (uncast) values ready for
    app/ingestion.py's ingest_rows -- casting happens once, there, at
    confirm time, same deterministic-vs-LLM split as the CSV/document
    paths. `summary` is a deterministically-composed confirmation string
    (app/data_entry.py computes it, never the LLM) so the number the
    owner is asked to confirm can never silently differ from what
    actually gets recorded.

    Scoped to business_id, not conversation_id: generate_chat_answer
    (app/chat_generation.py) is channel-agnostic and carries no
    conversation concept. At most one "pending" row per business at a
    time -- a new proposal supersedes (cancels) whatever was pending
    before it. See docs/decisions.md."""

    __tablename__ = "pending_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    dataset_type = Column(String, nullable=False)
    fields = Column(JSONB, nullable=False)
    summary = Column(Text, nullable=False)
    # "pending" | "confirmed" | "cancelled" (also used for "superseded by a
    # newer proposal" -- no separate status needed for that case).
    status = Column(String, nullable=False, server_default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
