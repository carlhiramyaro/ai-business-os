import uuid
from datetime import datetime

from app.schemas.base import CamelModel


class LinkCodeResponse(CamelModel):
    code: str
    expires_at: datetime
    whatsapp_number: str | None


class ChannelIdentitySummary(CamelModel):
    id: uuid.UUID
    channel: str
    display_name: str | None
    masked_external_id: str
    verified_at: datetime
