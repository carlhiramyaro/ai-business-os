import uuid
from datetime import datetime, timedelta, timezone

from app.auth_maintenance import delete_expired_refresh_tokens
from app.models import RefreshToken, User
from app.security import hash_password


def _seed_user(db_session):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.flush()
    return user


def _add_token(db_session, user, expires_at):
    token = RefreshToken(user_id=user.id, token_hash=uuid.uuid4().hex, expires_at=expires_at)
    db_session.add(token)
    return token


def test_delete_expired_refresh_tokens_removes_only_expired_rows(db_session):
    user = _seed_user(db_session)
    now = datetime.now(timezone.utc)
    expired = _add_token(db_session, user, now - timedelta(days=1))
    expiring_soon = _add_token(db_session, user, now + timedelta(seconds=1))
    far_future = _add_token(db_session, user, now + timedelta(days=30))
    db_session.flush()
    expired_id, expiring_soon_id, far_future_id = expired.id, expiring_soon.id, far_future.id

    deleted = delete_expired_refresh_tokens(db_session)

    assert deleted == 1
    remaining_ids = {row.id for row in db_session.query(RefreshToken).all()}
    assert remaining_ids == {expiring_soon_id, far_future_id}
    assert expired_id not in remaining_ids


def test_delete_expired_refresh_tokens_on_empty_table_returns_zero(db_session):
    assert delete_expired_refresh_tokens(db_session) == 0


def test_cleanup_task_is_registered_in_beat_schedule():
    """Guards against the task existing but never being scheduled -- the
    exact silent-failure mode this cleanup exists to avoid in the first
    place (see app/tasks.py's cleanup_expired_refresh_tokens_task
    docstring)."""
    from app.celery_app import celery_app

    entry = celery_app.conf.beat_schedule.get("cleanup-expired-refresh-tokens")
    assert entry is not None
    assert entry["task"] == "cleanup_expired_refresh_tokens"
