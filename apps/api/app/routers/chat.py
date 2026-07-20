from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.chat_generation import generate_chat_answer
from app.database import get_db
from app.dependencies import get_owned_business, get_owned_conversation
from app.models import Business, Conversation, Message
from app.retrieval import retrieve_relevant_chunks
from app.schemas.chat import (
    ConversationCreateResponse,
    ConversationHistory,
    MessageItem,
    SendMessageRequest,
    SendMessageResponse,
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

    context_chunks = retrieve_relevant_chunks(db, business.id, payload.message)
    answer = generate_chat_answer(payload.message, context_chunks, history)

    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer))
    db.commit()

    return SendMessageResponse(answer=answer)


@router.get("/{conversation_id}", response_model=ConversationHistory)
def get_conversation(conversation: Conversation = Depends(get_owned_conversation), db: Session = Depends(get_db)):
    messages = (
        db.query(Message).filter(Message.conversation_id == conversation.id).order_by(Message.created_at).all()
    )
    return ConversationHistory(
        conversation_id=conversation.id,
        messages=[MessageItem(id=m.id, role=m.role, content=m.content, created_at=m.created_at) for m in messages],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation: Conversation = Depends(get_owned_conversation), db: Session = Depends(get_db)):
    db.query(Message).filter(Message.conversation_id == conversation.id).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
