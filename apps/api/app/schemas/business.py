import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel


class BusinessCreate(CamelModel):
    business_name: str = Field(min_length=1)
    industry: str | None = None
    currency: str | None = None
    country: str | None = None
    timezone: str | None = None


class BusinessUpdate(CamelModel):
    business_name: str | None = Field(default=None, min_length=1)
    industry: str | None = None
    currency: str | None = None
    country: str | None = None
    timezone: str | None = None


class BusinessResponse(CamelModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    business_name: str
    industry: str | None
    currency: str | None
    country: str | None
    timezone: str | None
    created_at: datetime
    updated_at: datetime
