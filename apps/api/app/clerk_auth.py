import os

import jwt
from dotenv import load_dotenv

load_dotenv()

CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")
CLERK_ISSUER = os.getenv("CLERK_ISSUER")

# PyJWKClient caches keys by kid and refetches on a cache miss, so a Clerk
# key rotation doesn't require a redeploy. One client per process, reused
# across requests.
_jwk_client = jwt.PyJWKClient(CLERK_JWKS_URL) if CLERK_JWKS_URL else None


def decode_clerk_token(token: str) -> dict:
    """Verifies a Clerk session token's RS256 signature against Clerk's
    published JWKS, plus issuer and expiry. Raises jwt.PyJWTError (or a
    subclass) on any failure -- callers treat that uniformly as "reject
    this token", matching the old decode_access_token contract."""
    if _jwk_client is None:
        raise jwt.InvalidTokenError("CLERK_JWKS_URL is not configured")

    signing_key = _jwk_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=CLERK_ISSUER,
        options={"require": ["exp", "iss", "sub"]},
    )
