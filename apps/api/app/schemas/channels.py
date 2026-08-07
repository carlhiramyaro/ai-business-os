import uuid
from datetime import datetime
from typing import Literal

from app.schemas.base import CamelModel

# Mirrors app/models/channel.py's NOTIFICATION_FREQUENCIES -- Literal here
# gives FastAPI/Pydantic a real 422 on an invalid value instead of it
# reaching the DB.
NotificationFrequency = Literal["off", "immediate", "daily_digest"]


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
    notification_frequency: NotificationFrequency


class ChannelIdentityUpdate(CamelModel):
    notification_frequency: NotificationFrequency
