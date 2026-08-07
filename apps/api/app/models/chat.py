import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small's native output size


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # v0.6 slice 1 (WhatsApp channel): both nullable so every pre-existing
    # conversation is unaffected -- NULL/"web" means the web chat UI (the
    # only channel that existed before this). A channel_identity_id is set
    # only for channel="whatsapp" conversations; app/channels.py's
    # get_or_create_channel_conversation keeps one rolling conversation per
    # identity rather than one per web-style "session".
    channel = Column(String, nullable=True)
    channel_identity_id = Column(UUID(as_uuid=True), ForeignKey("channel_identities.id"), nullable=True, index=True)


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    # [{"tool": ..., "arguments": {...}}] for assistant messages; NULL for
    # user messages and assistant messages predating the v0.2 agent loop.
    tool_calls = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    source_type = Column(String, nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    embedding_id = Column(String, nullable=True)
    vector = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    chunk_text = Column(Text, nullable=False)
    embedding_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
