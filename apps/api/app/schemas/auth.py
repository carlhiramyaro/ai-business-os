import uuid
from datetime import datetime

from pydantic import EmailStr

from app.schemas.base import CamelModel


class UserResponse(CamelModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    created_at: datetime
