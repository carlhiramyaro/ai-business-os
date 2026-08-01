"""v0.5 slice 3 (multi-tenant hardening): expired-refresh-token cleanup.

Deliberately separated from the Celery task shape (see app/tasks.py's
cleanup_expired_refresh_tokens_task) so this can be tested with the
standard SAVEPOINT-rollback db_session fixture instead of the heavier
commit-for-real pattern test_uploads.py needs for Celery-triggering tests
-- per docs/agent-instructions.md's "deterministic stages independently
testable" rule.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import RefreshToken


def delete_expired_refresh_tokens(db: Session) -> int:
    """"Expired" is precisely expires_at < now(UTC) -- no grace period. A
    token past that instant is already rejected by
    app/routers/auth.py's /refresh check, so the row has zero remaining
    function the moment it crosses that line."""
    cutoff = datetime.now(timezone.utc)
    deleted = db.query(RefreshToken).filter(RefreshToken.expires_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted
