import os

import pytest
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

load_dotenv()

# Clerk auth (app/clerk_auth.py). A dummy, never-fetched JWKS URL --
# _patch_clerk_jwks below replaces the actual key lookup, so this only
# needs to be non-empty for app.clerk_auth's module-level _jwk_client to
# get constructed at all. CLERK_ISSUER must match what tests/auth_helpers.py
# puts in the `iss` claim of every token it mints.
os.environ.setdefault("CLERK_JWKS_URL", "https://clerk.example.test/.well-known/jwks.json")
os.environ.setdefault("CLERK_ISSUER", "https://clerk.example.test")

# Fixed, not generated at import time: without __init__.py, this module
# can end up imported under two different names in the same process (bare
# `conftest` via pytest's own plugin loading, `tests.conftest` via this
# file's explicit `from tests.conftest import ...`) -- two live module
# objects, so a key generated at import time would exist twice, and
# tests/auth_helpers.py's tokens would sign with one instance while this
# file's _patch_clerk_jwks verifies against the other. A fixed PEM sidesteps
# that entirely: both "copies" parse the same bytes into equal key material.
# Test-only, never used outside this process -- fine to hardcode.
_TEST_RSA_PRIVATE_KEY_PEM = b"""-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCPdp7uv9NkaVn6
VoTnBekbaSxbXpKbNVSR5Ajg4C7NQTUOJPYbi2pviU6zRIDJlpgWIBRV9PutZy1e
4AOQBG6vY8+HrVPt9I/3UP663uoKxf8z4fY3gB3JtGW1fzgNJ0IDtrzvQ7izhgWz
iFhqrjqELk3fd55hdgEQtDrzKDToc+pWtd8NB90SqvdrR8e84LT1pQJh6cqec/ha
XWUU7HiUDG5Ckl9t/17KzurWkjZ4gKu4Hr6g3Ai+/8SQssY69H/mLyRrr9GHpcva
rZLnGCm+vX3J3a2bjsyszEy5DdHbZsC+Ju3qrEPfnSys7Yexsv6kW49w+3gW+EeA
W7fDdqiLAgMBAAECggEAKE6Olsuka+jBk/ks+++IL+BbywwGKr9QFHE6IVw7KgXx
DxlJYDHKZK3yQ6GygXDjKAw5SnE7KNv9PlO4DIWCR5rGWvtSwl9c94J1HzG0FfTN
H9mToMJJHDun+9dTezaVcI+uA5dGVIIKJgfft5Fd9XdA/9EO2Zka8YOBsIGSY+CJ
mH+U3i1+sLfopQY+dOSu0AmYKRWHmCPxp0deM3kdg/MSGMIHx+UY6dll1mW+QCS8
/b2PA/DoSu+G22Oe0DwoR0jbCBeqBIERN+P96BFgmiE//yRfowAGLQMzaG0facaQ
Rww9HTwSQvSntiFVsc/p7tovbgV1EDmtzdWZo6ExcQKBgQDJ080X5AxAuoT2Hi8/
8AviW1IohPYuKeg9ef5k4D5rOSMDFSoOq9LLO9/yE/8kJms702LcVtBC9ROpjXAW
nKzk/7korvhkEIsOvWyE+FvX00uIzzQH69VCRJIpq6MfP2LtvcpC2/Q7XTsiIYF1
t22fxe5daoctGCS5TVg4sC7HmQKBgQC1+HHUsPcYEO2GcHeYEKKp97S2ihtLoGOb
sDzjuGUEyjLsofTXe1MzxBE4PrjhGtUecRfbbZHdrTqCN67Si5D+N/zMaU0p68sB
8x/bOggRv9GjHI23/eS1LEVrpXR83/llZNHJY0MET2apZFNd2/7GCLRgQCPq0T3G
kdeHH0D3wwKBgQCoEAvP4iFl4SuI+tejqVNsGVlPznBlPpZaYvS4sZaomLqT/ZK5
BtGQVPqFzar/QlK3Ta4cBtqDdyr5XILDAZJjWqKnwxOp17DEBG6SR3HLRfK3KLuO
AQ7jkNAZjQhXo+PQTuNXS2uT522vXTE9ghHyItL7zRJlNZ6XA1X8VpGNuQKBgQCZ
vlYWeIncKHk2jBFPRkbYyfNCAr97DwD5ilZ3o9SdzmRmL5PY91ZdtztBRSUY8326
oZyhhRqnq3Nyj69CLi8Lyqvo3NMYJyM2+34f0BD/RgzN/hLysC2qsMPaZklcNDPX
ae4hc58sphU76wrQk03XbYVQiQCPpcfG3HO3sz1F1wKBgC32faKZ6XJYvX6VJx5+
HpJVHDhy5XtB3XOG2OqqQkQNFnacnThxoNrPSZxlURGgK8MBgVpGWTxXaYoEU8aX
OftWQmX72bVKd1I4x55rj0s/E7uvWhsLrISq+Bh2n/L/4YvcbMfGyLq//f3j230l
1OBf8jLMjKkmCer0xtzTlsWy
-----END PRIVATE KEY-----
"""
TEST_RSA_PRIVATE_KEY = serialization.load_pem_private_key(_TEST_RSA_PRIVATE_KEY_PEM, password=None)

# Redundant with app/observability.py's own "no LANGFUSE_PUBLIC_KEY -> skip
# init" guard and ci.yml's env block -- three independent layers so tests
# can never start making real network calls to Langfuse regardless of
# what's in a developer's local .env. Set unconditionally (not
# setdefault): even a real key present locally shouldn't make the test
# suite itself trace anything -- manual local verification happens outside
# pytest (docker compose up). See docs/infra-guide.md.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

# Same reasoning as LANGFUSE_TRACING_ENABLED above, unconditional not
# setdefault: without this, a developer's local .env silently decides
# whether the entire existing test suite intermittently fails on rate
# limits it was never written to expect. tests/test_rate_limit.py
# re-enables this per-test via monkeypatch.setenv. See app/rate_limit.py.
os.environ["RATE_LIMIT_ENABLED"] = "false"

TEST_DATABASE_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:"
    f"{os.getenv('POSTGRES_PASSWORD')}@"
    f"{os.getenv('POSTGRES_HOST')}:"
    f"{os.getenv('POSTGRES_PORT')}/"
    "ai_business_os_test"
)

test_engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def _celery_eager():
    from app.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True


@pytest.fixture(scope="session", autouse=True)
def _patch_clerk_jwks():
    """Replaces only the network fetch of Clerk's public JWKS with our
    locally-generated TEST_RSA_PRIVATE_KEY -- signature and issuer
    verification in app/clerk_auth.py still run for real against tokens
    tests/auth_helpers.py mints. Consistent with this project's
    only-the-LLM-call-gets-mocked rule (docs/agent-instructions.md): this
    is a network-boundary substitution, not a mock of app logic."""
    from app import clerk_auth

    class _FakeSigningKey:
        key = TEST_RSA_PRIVATE_KEY.public_key()

    clerk_auth._jwk_client.get_signing_key_from_jwt = lambda token: _FakeSigningKey()


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    from app import models  # noqa: F401  registers all models on Base.metadata
    from app.database import Base

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def db_session():
    """One real transaction per test, wrapping a SAVEPOINT that gets
    restarted every time app code calls session.commit() — so route
    handlers can commit freely, but everything is rolled back at the end
    of the test regardless. See SQLAlchemy's "join a session into an
    external transaction" recipe."""
    connection = test_engine.connect()
    outer_transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    from app.database import get_db
    from main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
