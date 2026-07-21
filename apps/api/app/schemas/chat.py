import uuid
from datetime import datetime

from app.schemas.base import CamelModel


class ConversationCreateResponse(CamelModel):
    conversation_id: uuid.UUID


class SendMessageRequest(CamelModel):
    message: str


class ToolCallItem(CamelModel):
    tool: str
    arguments: dict


class SendMessageResponse(CamelModel):
    answer: str
    tool_calls: list[ToolCallItem] = []


class MessageItem(CamelModel):
    id: uuid.UUID
    role: str
    content: str
    tool_calls: list[ToolCallItem] | None = None
    created_at: datetime


class ConversationHistory(CamelModel):
    conversation_id: uuid.UUID
    messages: list[MessageItem]
