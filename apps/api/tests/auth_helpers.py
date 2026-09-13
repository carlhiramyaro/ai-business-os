"""Shared Clerk-shaped auth helpers for tests. See docs/decisions.md's
Clerk-migration entry: there is no /auth/register or /auth/login endpoint
anymore. app/dependencies.py's get_current_user just-in-time provisions a
User row from a verified token's email/sub claims on the first
authenticated request, so minting a token IS the "registration" step now
-- no HTTP call or direct DB insert needed.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from tests.conftest import TEST_RSA_PRIVATE_KEY


def mint_token(clerk_user_id: str, email: str, full_name: str = "Test User") -> str:
    """Lower-level than register_and_login: for tests that create a `User`
    row directly (the real_client/TestSessionLocal pattern, see CLAUDE.md's
    Celery-task-tests note) rather than relying on JIT provisioning. The
    row's own `clerk_user_id` must be set to this same value, or
    get_current_user won't find it and will JIT-provision a second row."""
    payload = {
        "sub": clerk_user_id,
        "iss": os.environ["CLERK_ISSUER"],
        "email": email,
        "full_name": full_name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, TEST_RSA_PRIVATE_KEY, algorithm="RS256")


def register_and_login(email: str, full_name: str = "Test User") -> str:
    return mint_token(f"user_{uuid.uuid4().hex}", email, full_name)


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
