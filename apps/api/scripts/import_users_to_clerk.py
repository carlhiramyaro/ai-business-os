"""One-off migration: create a Clerk user for every local User row that
doesn't have one yet, carrying the existing bcrypt hash over so nobody's
password changes. See docs/decisions.md's Clerk-migration entry and
CLAUDE.md's auth section for the full plan.

Idempotent: rows with clerk_user_id already set are skipped, and a
duplicate-email response from Clerk (e.g. a re-run after a crash between
"user created" and "clerk_user_id committed") is resolved by looking the
existing Clerk user up instead of failing.

Usage (from apps/api, with CLERK_SECRET_KEY set):
    python -m scripts.import_users_to_clerk [--dry-run]
"""
import argparse
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

import os

from app.database import SessionLocal
from app.models import User

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
CLERK_API_BASE = "https://api.clerk.com/v1"
# Clerk's backend API allows ~20 requests/10s; stay comfortably under it
# rather than parsing rate-limit headers for a script that runs once.
REQUEST_DELAY_SECONDS = 0.6


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")


def _find_existing_clerk_user(client: httpx.Client, email: str) -> str | None:
    response = client.get(f"{CLERK_API_BASE}/users", params={"email_address": [email]})
    response.raise_for_status()
    results = response.json()
    return results[0]["id"] if results else None


def _create_clerk_user(client: httpx.Client, user: User) -> str:
    first_name, last_name = _split_name(user.full_name)
    payload = {
        "email_address": [user.email],
        "first_name": first_name,
        "last_name": last_name,
        "skip_password_checks": True,
    }
    if user.password_hash:
        payload["password_digest"] = user.password_hash
        payload["password_hasher"] = "bcrypt"

    response = client.post(f"{CLERK_API_BASE}/users", json=payload)
    if response.status_code == 422 and any(
        e.get("code") == "form_identifier_exists" for e in response.json().get("errors", [])
    ):
        existing_id = _find_existing_clerk_user(client, user.email)
        if existing_id is not None:
            return existing_id
    response.raise_for_status()
    return response.json()["id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not CLERK_SECRET_KEY:
        sys.exit("CLERK_SECRET_KEY is not set")

    db = SessionLocal()
    client = httpx.Client(headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"}, timeout=10.0)
    try:
        users = db.query(User).filter(User.clerk_user_id.is_(None)).all()
        print(f"{len(users)} user(s) to import")

        for i, user in enumerate(users):
            if args.dry_run:
                print(f"[dry-run] would import {user.email}")
                continue

            clerk_user_id = _create_clerk_user(client, user)
            user.clerk_user_id = clerk_user_id
            db.commit()
            print(f"imported {user.email} -> {clerk_user_id}")

            if i < len(users) - 1:
                time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    main()
