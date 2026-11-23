"""FastAPI application entrypoint: CORS, router wiring, and the asyncpg
connection pool's startup/shutdown lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.logging import new_request_id, request_id_var, setup_logging
from .db.client import close_pool, create_pool
from .ingestion.pipeline import recover_stuck_documents
from .routers import chat, chats, documents, health, insights, memory, messages, usage

setup_logging()
logger = logging.getLogger(__name__)


async def _recover() -> None:
    try:
        n = await recover_stuck_documents()
        if n:
            logger.info("Recovered %d stuck document(s)", n)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Stuck-document recovery failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: creating asyncpg connection pool")
    await create_pool()
    recovery = None
    if settings.RECOVER_STUCK_ON_STARTUP:
        recovery = asyncio.create_task(_recover())
    try:
        yield
    finally:
        if recovery is not None:
            recovery.cancel()
        logger.info("Shutting down: closing asyncpg connection pool")
        await close_pool()


app = FastAPI(title="RAG Chat Backend", version="0.1.0", lifespan=lifespan)

# The frontend calls this API directly, cross-origin -- never proxied through
# Next.js -- because a streaming chat response would exceed Vercel's
# free-tier function timeout (10s). We use an explicit origin allowlist
# (never "*") from settings, which is what a real deployment needs anyway
# and keeps the door open to cookie-based auth later.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(chats.router)
app.include_router(messages.router)
app.include_router(memory.router)
app.include_router(usage.router)
app.include_router(insights.router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Correlate every log line of an HTTP request; echo the id back."""
    rid = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(rid[:64])
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["x-request-id"] = rid[:64]
    return response
