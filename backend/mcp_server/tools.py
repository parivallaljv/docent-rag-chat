"""Transport-independent tool implementations for the Docent MCP server.

Each function takes an explicit pool and the *verified* user id, so the same
per-user isolation as the HTTP API applies: every query is scoped by user_id.
Returned values are plain JSON-friendly dicts/lists."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db import queries
from app.insights import SCHEMAS, generate_insight
from app.retrieval.search import search

MAX_K = 10
SNIPPET_CHARS = 1200


async def search_documents(
    pool, user_id: str, query: str, k: int = 5, document_id: str | None = None
) -> list[dict[str, Any]]:
    k = max(1, min(int(k), MAX_K))
    doc = UUID(document_id) if document_id else None
    candidates = await search(pool, user_id=user_id, query_text=query, document_id=doc, top_n=k)
    return [
        {
            "document_id": str(c.document_id),
            "filename": c.filename,
            "page": c.page_number,
            "similarity": round(float(c.similarity), 3),
            "text": c.content[:SNIPPET_CHARS],
        }
        for c in candidates[:k]
    ]


async def list_documents(pool, user_id: str) -> list[dict[str, Any]]:
    rows = await queries.list_documents(pool, user_id=user_id)
    return [{"id": str(r["id"]), "filename": r["filename"], "status": r["status"]} for r in rows]


async def get_document_insight(pool, user_id: str, document_id: str, kind: str) -> dict[str, Any]:
    """Return a cached insight, or generate and cache one (summary/key_facts/quiz)."""
    if kind not in SCHEMAS:
        raise ValueError(f"kind must be one of {sorted(SCHEMAS)}")
    doc = await queries.get_document(pool, user_id=user_id, document_id=document_id)
    if doc is None:
        raise ValueError("Document not found.")
    if doc["status"] != "ready":
        raise ValueError(f"Document is not ready (status: {doc['status']}).")
    cached = await queries.get_insight(pool, user_id=user_id, document_id=document_id, kind=kind)
    if cached is not None:
        return cached if isinstance(cached, dict) else dict(cached)
    chunks = await queries.get_document_chunks(pool, user_id=user_id, document_id=document_id)
    result = await generate_insight(kind, doc["filename"], chunks)
    await queries.upsert_insight(
        pool, user_id=user_id, document_id=document_id, kind=kind, result=result
    )
    return result
