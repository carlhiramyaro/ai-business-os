from fastapi import APIRouter, Depends, status
from langfuse import propagate_attributes
from sqlalchemy.orm import Session

from app.chat_generation import generate_chat_answer
from app.database import get_db
from app.dependencies import get_owned_business, get_owned_conversation
from app.models import Business, Conversation, Message
from app.schemas.chat import (
    ConversationCreateResponse,
    ConversationHistory,
    MessageItem,
    SendMessageRequest,
    SendMessageResponse,
    ToolCallItem,
)

router = APIRouter(prefix="/api/v1/businesses/{business_id}/chat", tags=["chat"])


@router.post("/", response_model=ConversationCreateResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    conversation = Conversation(business_id=business.id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ConversationCreateResponse(conversation_id=conversation.id)


@router.post("/{conversation_id}/messages", response_model=SendMessageResponse)
def send_message(
    payload: SendMessageRequest,
    business: Business = Depends(get_owned_business),
    conversation: Conversation = Depends(get_owned_conversation),
    db: Session = Depends(get_db),
):
    db.add(Message(conversation_id=conversation.id, role="user", content=payload.message))
    db.flush()

    history = [
        {"role": message.role, "content": message.content}
        for message in db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
        .all()[:-1]  # exclude the message just added -- passed separately as the question
    ]

    # session_id=conversation_id groups every LLM/embedding call this
    # request makes (up to 6 completions across the tool-calling loop plus
    # tool-call/embedding spans) into one Langfuse trace. See
    # app/chat_generation.py's @observe on generate_chat_answer.
    with propagate_attributes(session_id=str(conversation.id), metadata={"business_id": str(business.id)}):
        result = generate_chat_answer(db, business, payload.message, history)

    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=result.answer,
            # [] (answered without tools) is stored as-is — NULL is reserved
            # for messages predating the agent loop.
            tool_calls=result.tool_calls,
        )
    )
    db.commit()

    return SendMessageResponse(
        answer=result.answer,
        tool_calls=[ToolCallItem(tool=call["tool"], arguments=call["arguments"]) for call in result.tool_calls],
    )


@router.get("/{conversation_id}", response_model=ConversationHistory)
def get_conversation(conversation: Conversation = Depends(get_owned_conversation), db: Session = Depends(get_db)):
    messages = (
        db.query(Message).filter(Message.conversation_id == conversation.id).order_by(Message.created_at).all()
    )
    return ConversationHistory(
        conversation_id=conversation.id,
        messages=[
            MessageItem(id=m.id, role=m.role, content=m.content, tool_calls=m.tool_calls, created_at=m.created_at)
            for m in messages
        ],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation: Conversation = Depends(get_owned_conversation), db: Session = Depends(get_db)):
    db.query(Message).filter(Message.conversation_id == conversation.id).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
