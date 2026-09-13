import uuid

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=True)
    # Nullable during the Clerk migration: existing rows are backfilled by
    # scripts/import_users_to_clerk.py, new rows get it at JIT-provisioning
    # time in app/clerk_auth.py. password_hash stays until docs/decisions.md's
    # Clerk-migration entry's final cleanup migration drops it.
    clerk_user_id = Column(String, nullable=True, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
