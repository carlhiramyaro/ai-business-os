import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Business, BusinessFact, Conversation, Insight, Report, UploadSession, User
from app.security import decode_access_token
from app.worker_health import workers_online

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise credentials_error

    if payload.get("type") != "access":
        raise credentials_error

    try:
        user_id = uuid.UUID(payload.get("sub"))
    except (TypeError, ValueError):
        raise credentials_error

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error

    return user


def get_owned_business(
    business_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Business:
    """Shared by every /businesses/{business_id}/... route (and later
    uploads/reports/chat) so the businessId ownership check in
    agent-instructions.md lives in exactly one place."""
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    if business.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this business")
    return business


def get_owned_upload_session(
    upload_session_id: uuid.UUID,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
) -> UploadSession:
    upload_session = db.get(UploadSession, upload_session_id)
    if upload_session is None or upload_session.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found")
    return upload_session


def get_owned_report(
    report_id: uuid.UUID,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
) -> Report:
    report = db.get(Report, report_id)
    if report is None or report.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


def get_owned_insight(
    insight_id: uuid.UUID,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
) -> Insight:
    insight = db.get(Insight, insight_id)
    if insight is None or insight.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
    return insight


def get_owned_fact(
    fact_id: uuid.UUID,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
) -> BusinessFact:
    fact = db.get(BusinessFact, fact_id)
    if fact is None or fact.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")
    return fact


def get_owned_conversation(
    conversation_id: uuid.UUID,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


def require_worker_online() -> None:
    """Guards every route that hands work to Celery via `.delay(...)`.

    Without a worker listening, the task sits queued in Redis forever and
    whatever the route already created (an upload session, S3 objects, a
    report row) hangs in PROCESSING/PENDING with no visible error -- the
    exact "stuck upload" failure mode this guards against. Depend on this
    before doing anything else so a down worker is caught before any
    side effect (S3 write, row insert) happens."""
    if not workers_online():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Background worker is not running, so this request cannot be processed. "
                "Start it with: celery -A app.celery_app worker --pool=solo"
            ),
        )
