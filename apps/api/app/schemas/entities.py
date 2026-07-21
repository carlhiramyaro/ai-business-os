import uuid
from datetime import datetime

from app.schemas.base import CamelModel


class CustomerItem(CamelModel):
    id: uuid.UUID
    name: str
    phone: str | None
    created_at: datetime


class SupplierItem(CamelModel):
    id: uuid.UUID
    name: str
    created_at: datetime
