import uuid
from datetime import datetime

from app.schemas.base import CamelModel


class ConversationCreateResponse(CamelModel):
    conversation_id: uuid.UUID


class SendMessageRequest(CamelModel):
    message: str


class SendMessageResponse(CamelModel):
    answer: str


class MessageItem(CamelModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class ConversationHistory(CamelModel):
    conversation_id: uuid.UUID
    messages: list[MessageItem]
