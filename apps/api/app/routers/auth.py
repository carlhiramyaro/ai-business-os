import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import RefreshToken, User
from app.rate_limit import RateLimit, check_rate_limit, client_ip
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# v0.5 slice 3 (multi-tenant hardening, docs/decisions.md [2026-08-01]):
# these endpoints were wide open to brute-force/credential-stuffing/
# enumeration before this -- rate limiting closes that. Every spec is
# env-tunable via SSM without a redeploy; see .env.example for the full
# list and reasoning per limit.
_RATE_LIMIT_REGISTER = os.getenv("RATE_LIMIT_REGISTER", "5/hour")
_RATE_LIMIT_LOGIN_IP = os.getenv("RATE_LIMIT_LOGIN_IP", "100/hour")
_RATE_LIMIT_LOGIN_EMAIL = os.getenv("RATE_LIMIT_LOGIN_EMAIL", "10/hour")
_RATE_LIMIT_REFRESH = os.getenv("RATE_LIMIT_REFRESH", "60/hour")


def _limit_login(request: Request, payload: LoginRequest) -> None:
    """Two separate limits, not one: per-IP (generous -- carrier-grade NAT
    is common for this product's target market, so a strict IP limit would
    punish a whole shared network for one bad actor) and per-email (tight
    -- the actual defense against a targeted brute force against one known
    account, which an attacker rotating IPs would otherwise evade
    entirely). FastAPI parses the JSON body once and injects the same
    LoginRequest into both this dependency and the route handler, so there
    is no double body-read.

    Deliberately not account lockout: lockout hands an attacker a trivial
    way to deny a real user access to their own account just by repeatedly
    guessing their email with a wrong password. Rate limiting achieves the
    same brute-force defense without that footgun. See docs/decisions.md.
    """
    check_rate_limit(_RATE_LIMIT_LOGIN_IP, "login-ip", f"ip:{client_ip(request)}")
    check_rate_limit(_RATE_LIMIT_LOGIN_EMAIL, "login-email", f"email:{payload.email.lower()}")


def _issue_tokens(db: Session, user: User) -> TokenResponse:
    raw_refresh_token, token_hash, expires_at = generate_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=raw_refresh_token,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimit(_RATE_LIMIT_REGISTER, "register"))],
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(_limit_login)])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
    )

    user = db.query(User).filter(User.email == payload.email).first()
    # Deliberately the same error whether the email doesn't exist or the
    # password is wrong — distinguishing the two lets an attacker enumerate
    # registered emails.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise invalid_credentials

    return _issue_tokens(db, user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimit(_RATE_LIMIT_REFRESH, "refresh"))],
)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    invalid_token = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    token_hash = hash_refresh_token(payload.refresh_token)
    stored_token = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if stored_token is None:
        raise invalid_token
    if stored_token.expires_at < datetime.now(timezone.utc):
        db.delete(stored_token)
        db.commit()
        raise invalid_token

    user = db.get(User, stored_token.user_id)
    if user is None:
        raise invalid_token

    # Rotate: the presented refresh token is single-use — delete it and
    # issue a brand-new access/refresh pair, so a stolen-but-unused token
    # can't be replayed after the legitimate client has refreshed.
    db.delete(stored_token)
    db.commit()

    return _issue_tokens(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)
    db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).delete()
    db.commit()


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user
