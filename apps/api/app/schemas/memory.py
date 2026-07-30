import uuid
from datetime import datetime

from app.schemas.base import CamelModel


class BusinessFactSummary(CamelModel):
    id: uuid.UUID
    content: str
    source: str
    created_at: datetime
