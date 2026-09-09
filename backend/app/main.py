"""FastAPI application entrypoint: CORS, router wiring, and the asyncpg
connection pool's startup/shutdown lifecycle.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .db.client import close_pool, create_pool
from .routers import chat, documents, health

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: creating asyncpg connection pool")
    await create_pool()
    try:
        yield
    finally:
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
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(chat.router)
