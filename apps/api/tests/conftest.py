import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

load_dotenv()

# Redundant with app/observability.py's own "no LANGFUSE_PUBLIC_KEY -> skip
# init" guard and ci.yml's env block -- three independent layers so tests
# can never start making real network calls to Langfuse regardless of
# what's in a developer's local .env. Set unconditionally (not
# setdefault): even a real key present locally shouldn't make the test
# suite itself trace anything -- manual local verification happens outside
# pytest (docker compose up). See docs/infra-guide.md.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

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
