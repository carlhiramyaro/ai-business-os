import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import auth, business, chat, documents, entities, entries, insights, memory, report, upload
from app.worker_health import workers_online

load_dotenv()

app = FastAPI()

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
