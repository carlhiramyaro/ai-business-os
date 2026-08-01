import os
import uuid
from contextlib import asynccontextmanager

import structlog
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import configure_logging
from app.observability import flush_observability, init_observability
from app.routers import auth, business, chat, documents, entities, entries, insights, memory, report, upload
from app.worker_health import workers_online

load_dotenv()

# Before anything else -- including `app = FastAPI()` -- so every log line
# from here on, including FastAPI/uvicorn's own, goes through structlog,
# and Sentry's FastAPI auto-instrumentation is in place before the app
# object it instruments is created. See app/logging_config.py,
# app/observability.py.
configure_logging("api")
init_observability("api")
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Langfuse batches spans on a background thread -- flush on graceful
    # shutdown (e.g. a deploy's container swap) so in-flight traces aren't
    # silently dropped.
    flush_observability()


app = FastAPI(lifespan=lifespan)

# Comma-separated list of allowed frontend origins. Defaults to local dev;
# production sets this via SSM (e.g. "https://app.example.com") so the
# hardcoded-localhost trap docs/learning-guide.md warns about (section 3.7)
# never bites on deploy day. See docs/infra-guide.md.
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Binds a request_id to every log line emitted while handling this
    request (via structlog's contextvars, which the JSON renderer picks up
    automatically -- see app/logging_config.py) and echoes it back on the
    response, so a tester/support conversation can quote an ID that's
    directly greppable in CloudWatch. Accepts an inbound X-Request-ID so a
    request can be traced across services that set their own.

    Catches unhandled exceptions here directly rather than relying on a
    separate @app.exception_handler(Exception): with BaseHTTPMiddleware
    (what @app.middleware("http") is) anywhere in the stack, an exception
    raised by a route handler propagates out of call_next() itself rather
    than being converted to a response by ExceptionMiddleware first --
    confirmed against this FastAPI/Starlette version via
    tests/test_logging.py. HTTPException (every deliberate 4xx raised
    throughout app/routers/) is unaffected -- FastAPI's default handler for
    it still runs inside call_next() and returns normally."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("unhandled_exception", error=str(exc), exc_info=True)
            response = JSONResponse(
                status_code=500, content={"detail": "Internal server error", "requestId": request_id}
            )
    finally:
        structlog.contextvars.clear_contextvars()
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(auth.router)
app.include_router(business.router)
app.include_router(upload.router)
app.include_router(report.router)
app.include_router(chat.router)
app.include_router(entities.router)
app.include_router(entries.router)
app.include_router(documents.router)
app.include_router(insights.router)
app.include_router(memory.router)


@app.get("/")
def root():
    return {"message": "AI Business OS API"}


@app.get("/health/db")
def db_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.get("/health/worker")
def worker_health():
    """One-command answer to "is a Celery worker actually running" --
    added after a stuck-upload incident where the worker had silently not
    been started and nothing surfaced the failure until the DB was
    inspected by hand. See app/worker_health.py."""
    online = workers_online()
    return {"status": "ok" if online else "down", "worker": "online" if online else "not running"}


@app.get("/debug/observability-drill")
def observability_drill():
    """TEMPORARY -- v0.5 slice 2's production timed drill (docs/decisions.md
    [2026-08-01]): deliberately raises an unhandled exception to verify the
    request-ID/CloudWatch/Sentry pipeline end to end. Removed in the very
    next commit after the drill confirms it."""
    1 / 0
