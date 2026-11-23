"""Raw SQL access to Postgres via the shared asyncpg pool. No ORM: every
query here is hand-written SQL, scoped to a user_id (and, for search,
optionally a single document_id).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import asyncpg

from ..core.config import settings


class DuplicateDocumentError(Exception):
    """Raised when a user already has a document with the given filename
    (enforced by the documents_user_id_filename_key unique constraint,
    migrations/003_validation.sql)."""


def _as_uuid(value: Any) -> uuid.UUID:
    """User ids arrive as the JWT's `sub` claim (a string); document ids may
    already be uuid.UUID (parsed by pydantic) or plain strings. Normalize
    either to uuid.UUID so asyncpg's uuid codec accepts them as query params."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def insert_document(
    pool: asyncpg.Pool, *, user_id: Any, filename: str, storage_path: str
) -> asyncpg.Record:
    """Create a new document row with status='pending'. Returns the full row
    (including the DB-assigned id and created_at) so callers don't need a
    second round trip. Raises DuplicateDocumentError if this user already has
    a document with this filename."""
    query = """
        INSERT INTO documents (user_id, filename, storage_path, status)
        VALUES ($1, $2, $3, 'pending')
        RETURNING id, filename, storage_path, status, error_message, created_at
    """
    async with pool.acquire() as conn:
        try:
            return await conn.fetchrow(query, _as_uuid(user_id), filename, storage_path)
        except asyncpg.UniqueViolationError as exc:
            raise DuplicateDocumentError(filename) from exc


async def update_document_status(
    pool: asyncpg.Pool,
    *,
    document_id: Any,
    status: str,
    error_message: str | None = None,
) -> None:
    query = """
        UPDATE documents
        SET status = $2, error_message = $3
        WHERE id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute(query, _as_uuid(document_id), status, error_message)


async def list_documents(pool: asyncpg.Pool, *, user_id: Any) -> list[asyncpg.Record]:
    query = """
        SELECT id, filename, storage_path, status, error_message, created_at
        FROM documents
        WHERE user_id = $1
        ORDER BY created_at DESC
    """
    async with pool.acquire() as conn:
        return await conn.fetch(query, _as_uuid(user_id))


async def insert_chunks(
    pool: asyncpg.Pool,
    *,
    document_id: Any,
    user_id: Any,
    chunks: Sequence[dict[str, Any]],
) -> None:
    """Batch-insert chunk rows. Each item in `chunks` is a dict with keys
    page_number, chunk_index, content, embedding (a length-768 list of floats)."""
    if not chunks:
        return
    query = """
        INSERT INTO chunks (document_id, user_id, page_number, chunk_index, content, embedding)
        VALUES ($1, $2, $3, $4, $5, $6)
    """
    doc_id = _as_uuid(document_id)
    uid = _as_uuid(user_id)
    records = [
        (doc_id, uid, c["page_number"], c["chunk_index"], c["content"], c["embedding"])
        for c in chunks
    ]
    async with pool.acquire() as conn:
        await conn.executemany(query, records)


async def search_chunks(
    pool: asyncpg.Pool,
    *,
    user_id: Any,
    query_embedding: Sequence[float],
    document_id: Any | None = None,
    limit: int = 20,
) -> list[asyncpg.Record]:
    """Cosine-distance kNN search via pgvector's `<=>` operator, scoped to the
    user (and optionally a single document). `<=>` is cosine *distance*
    (0 = identical, 2 = opposite), so similarity is reported as `1 - distance`.
    Assumes stored embeddings are already unit-normalized (see
    ingestion.embedder), which is what makes plain cosine distance meaningful.
    """
    uid = _as_uuid(user_id)
    if document_id is not None:
        query = """
            SELECT
                c.id,
                c.document_id,
                c.page_number,
                c.chunk_index,
                c.content,
                c.embedding,
                d.filename,
                1 - (c.embedding <=> $1) AS similarity
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.user_id = $2 AND c.document_id = $3
            ORDER BY c.embedding <=> $1
            LIMIT $4
        """
        args = (list(query_embedding), uid, _as_uuid(document_id), limit)
    else:
        query = """
            SELECT
                c.id,
                c.document_id,
                c.page_number,
                c.chunk_index,
                c.content,
                c.embedding,
                d.filename,
                1 - (c.embedding <=> $1) AS similarity
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.user_id = $2
            ORDER BY c.embedding <=> $1
            LIMIT $3
        """
        args = (list(query_embedding), uid, limit)

    async with pool.acquire() as conn, conn.transaction():
        # Query-time HNSW breadth; transaction-local so it can't leak to
        # other users of this pooled connection.
        await conn.execute(
            "SELECT set_config('hnsw.ef_search', $1, true)", str(settings.HNSW_EF_SEARCH)
        )
        return await conn.fetch(query, *args)


async def keyword_search_chunks(
    pool: asyncpg.Pool,
    *,
    user_id: Any,
    query_text: str,
    document_id: Any | None = None,
    limit: int = 20,
) -> list[asyncpg.Record]:
    """Full-text search over chunks.content_tsv (migration 005), ranked by
    ts_rank_cd. websearch_to_tsquery tolerates arbitrary user text. Returns
    the same columns as search_chunks, minus a meaningful `similarity`."""
    query = """
        SELECT c.id, c.document_id, c.page_number, c.chunk_index, c.content,
               c.embedding, d.filename
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.user_id = $2
          AND ($3::uuid IS NULL OR c.document_id = $3::uuid)
          AND c.content_tsv @@ websearch_to_tsquery('english', $1)
        ORDER BY ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', $1)) DESC
        LIMIT $4
    """
    doc = _as_uuid(document_id) if document_id is not None else None
    async with pool.acquire() as conn:
        return await conn.fetch(query, query_text, _as_uuid(user_id), doc, limit)


# --- chats & messages ---------------------------------------------------------

DEFAULT_CHAT_TITLE = "New chat"


async def create_chat(pool: asyncpg.Pool, *, user_id: Any, title: str | None = None):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "INSERT INTO chats (user_id, title) VALUES ($1, $2) "
            "RETURNING id, title, created_at, updated_at",
            _as_uuid(user_id),
            (title or DEFAULT_CHAT_TITLE)[:120],
        )


async def list_chats(pool: asyncpg.Pool, *, user_id: Any, limit: int = 50):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, title, created_at, updated_at FROM chats "
            "WHERE user_id = $1 ORDER BY updated_at DESC LIMIT $2",
            _as_uuid(user_id),
            limit,
        )


async def get_chat(pool: asyncpg.Pool, *, user_id: Any, chat_id: Any):
    """The chat row if it exists AND belongs to this user, else None."""
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = $1 AND user_id = $2",
            _as_uuid(chat_id),
            _as_uuid(user_id),
        )


async def delete_chat(pool: asyncpg.Pool, *, user_id: Any, chat_id: Any) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM chats WHERE id = $1 AND user_id = $2", _as_uuid(chat_id), _as_uuid(user_id)
        )
    return result.endswith(" 1")


async def list_messages(pool: asyncpg.Pool, *, user_id: Any, chat_id: Any, limit: int = 500):
    """Oldest-first messages of one of the user's chats."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, role, content, citations, created_at FROM messages "
            "WHERE chat_id = $1 AND user_id = $2 ORDER BY created_at, id LIMIT $3",
            _as_uuid(chat_id),
            _as_uuid(user_id),
            limit,
        )


async def recent_messages(pool: asyncpg.Pool, *, user_id: Any, chat_id: Any, limit: int):
    """The last `limit` messages, returned oldest-first (prompt order)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM messages WHERE chat_id = $1 AND user_id = $2 "
            "ORDER BY created_at DESC, id DESC LIMIT $3",
            _as_uuid(chat_id),
            _as_uuid(user_id),
            limit,
        )
    return list(reversed(rows))


async def add_message(
    pool: asyncpg.Pool,
    *,
    user_id: Any,
    chat_id: Any,
    role: str,
    content: str,
    citations: list[dict] | None = None,
) -> Any:
    """Append a message (returns its id), bump the chat's updated_at, and title
    a still-untitled chat from its first user message. One transaction."""
    uid, cid = _as_uuid(user_id), _as_uuid(chat_id)
    async with pool.acquire() as conn, conn.transaction():
        message_id = await conn.fetchval(
            "INSERT INTO messages (chat_id, user_id, role, content, citations) "
            "VALUES ($1, $2, $3, $4, $5::jsonb) RETURNING id",
            cid,
            uid,
            role,
            content,
            None if citations is None else json.dumps(citations),
        )
        await conn.execute(
            "UPDATE chats SET updated_at = now() WHERE id = $1 AND user_id = $2", cid, uid
        )
        if role == "user":
            await conn.execute(
                "UPDATE chats SET title = $3 WHERE id = $1 AND user_id = $2 AND title = $4",
                cid,
                uid,
                " ".join(content.split())[:60] or DEFAULT_CHAT_TITLE,
                DEFAULT_CHAT_TITLE,
            )
    return message_id


# --- feedback ------------------------------------------------------------------


async def upsert_feedback(
    pool: asyncpg.Pool, *, user_id: Any, message_id: Any, rating: int, comment: str | None
) -> bool:
    """Record a rating for one of the user's own assistant messages. Returns
    False if the message doesn't exist / isn't theirs / isn't an assistant turn."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO message_feedback (message_id, user_id, rating, comment) "
            "SELECT m.id, m.user_id, $3, $4 FROM messages m "
            "WHERE m.id = $1 AND m.user_id = $2 AND m.role = 'assistant' "
            "ON CONFLICT (message_id, user_id) DO UPDATE "
            "SET rating = EXCLUDED.rating, comment = EXCLUDED.comment, created_at = now() "
            "RETURNING message_id",
            _as_uuid(message_id),
            _as_uuid(user_id),
            rating,
            comment,
        )
    return row is not None


# --- tags, summary, memory ------------------------------------------------------


async def set_document_tags(pool: asyncpg.Pool, *, user_id: Any, document_id: Any, tags: list[str]):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE documents SET tags = $3 WHERE id = $1 AND user_id = $2",
            _as_uuid(document_id),
            _as_uuid(user_id),
            tags,
        )


async def get_chat_summary(pool: asyncpg.Pool, *, user_id: Any, chat_id: Any):
    """(summary | None, summary_upto | None)"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT summary, summary_upto FROM chats WHERE id = $1 AND user_id = $2",
            _as_uuid(chat_id),
            _as_uuid(user_id),
        )
    return (row["summary"], row["summary_upto"]) if row else (None, None)


async def set_chat_summary(
    pool: asyncpg.Pool, *, user_id: Any, chat_id: Any, summary: str, upto: Any
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE chats SET summary = $3, summary_upto = $4 WHERE id = $1 AND user_id = $2",
            _as_uuid(chat_id),
            _as_uuid(user_id),
            summary,
            upto,
        )


async def get_memory(pool: asyncpg.Pool, *, user_id: Any) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT content FROM user_memory WHERE user_id = $1", _as_uuid(user_id)
        )


async def upsert_memory(pool: asyncpg.Pool, *, user_id: Any, content: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_memory (user_id, content) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
            _as_uuid(user_id),
            content,
        )


async def delete_memory(pool: asyncpg.Pool, *, user_id: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM user_memory WHERE user_id = $1", _as_uuid(user_id))


# --- neighbouring chunks (parent-child context) -----------------------------------


async def get_neighbor_chunks(
    pool: asyncpg.Pool, *, user_id: Any, wanted: list[tuple[Any, int]], radius: int
):
    """Chunks within `radius` of each (document_id, chunk_index), for this user."""
    if not wanted:
        return []
    doc_ids = [_as_uuid(d) for d, _ in wanted]
    lows = [max(0, i - radius) for _, i in wanted]
    highs = [i + radius for _, i in wanted]
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT DISTINCT c.document_id, c.chunk_index, c.content FROM chunks c "
            "JOIN unnest($2::uuid[], $3::int[], $4::int[]) AS w(doc, lo, hi) "
            "ON c.document_id = w.doc AND c.chunk_index BETWEEN w.lo AND w.hi "
            "WHERE c.user_id = $1 ORDER BY c.document_id, c.chunk_index",
            _as_uuid(user_id),
            doc_ids,
            lows,
            highs,
        )


# --- usage ---------------------------------------------------------------------


async def add_usage(
    pool: asyncpg.Pool,
    *,
    user_id: Any,
    kind: str,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO usage_events (user_id, kind, model, prompt_tokens, completion_tokens, "
            "cost_usd) VALUES ($1, $2, $3, $4, $5, $6)",
            _as_uuid(user_id),
            kind,
            model,
            prompt_tokens,
            completion_tokens,
            cost_usd,
        )


async def usage_summary(pool: asyncpg.Pool, *, user_id: Any, days: int = 30):
    """(totals dict, [per-day dicts]) for the last `days` days."""
    uid = _as_uuid(user_id)
    async with pool.acquire() as conn:
        t = await conn.fetchrow(
            "SELECT count(*) AS turns, coalesce(sum(prompt_tokens),0) AS prompt_tokens, "
            "coalesce(sum(completion_tokens),0) AS completion_tokens, "
            "coalesce(sum(cost_usd),0) AS cost_usd FROM usage_events "
            "WHERE user_id = $1 AND created_at >= now() - make_interval(days => $2)",
            uid,
            days,
        )
        rows = await conn.fetch(
            "SELECT created_at::date AS day, count(*) AS turns, "
            "sum(prompt_tokens) AS prompt_tokens, sum(completion_tokens) AS completion_tokens, "
            "sum(cost_usd) AS cost_usd FROM usage_events "
            "WHERE user_id = $1 AND created_at >= now() - make_interval(days => $2) "
            "GROUP BY 1 ORDER BY 1",
            uid,
            days,
        )
    totals = {**dict(t), "cost_usd": float(t["cost_usd"])}
    daily = [
        {**dict(r), "day": r["day"].isoformat(), "cost_usd": float(r["cost_usd"])} for r in rows
    ]
    return totals, daily


# --- document insights ---------------------------------------------------------


async def get_document(pool: asyncpg.Pool, *, user_id: Any, document_id: Any):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, filename, status, storage_path FROM documents "
            "WHERE id = $1 AND user_id = $2",
            _as_uuid(document_id),
            _as_uuid(user_id),
        )


async def get_document_chunks(
    pool: asyncpg.Pool, *, user_id: Any, document_id: Any, limit: int = 2000
):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, page_number, chunk_index, content FROM chunks "
            "WHERE document_id = $1 AND user_id = $2 ORDER BY chunk_index LIMIT $3",
            _as_uuid(document_id),
            _as_uuid(user_id),
            limit,
        )


async def get_insight(pool: asyncpg.Pool, *, user_id: Any, document_id: Any, kind: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT result FROM document_insights "
            "WHERE document_id = $1 AND user_id = $2 AND kind = $3",
            _as_uuid(document_id),
            _as_uuid(user_id),
            kind,
        )
    if row is None:
        return None
    return json.loads(row["result"]) if isinstance(row["result"], str) else row["result"]


async def upsert_insight(
    pool: asyncpg.Pool, *, user_id: Any, document_id: Any, kind: str, result: dict
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO document_insights (document_id, user_id, kind, result) "
            "VALUES ($1, $2, $3, $4::jsonb) "
            "ON CONFLICT (document_id, kind) DO UPDATE SET result = EXCLUDED.result, created_at = now()",
            _as_uuid(document_id),
            _as_uuid(user_id),
            kind,
            json.dumps(result),
        )


# --- ingestion robustness ---------------------------------------------------------


async def replace_chunks_and_mark_ready(
    pool: asyncpg.Pool, *, document_id: Any, user_id: Any, chunks: Sequence[dict[str, Any]]
) -> None:
    """Atomically swap a document's chunks for the new set and mark it ready, so a
    crash mid-ingest can't leave half the chunks behind and a re-run (retry or
    startup recovery) is idempotent."""
    doc_id, uid = _as_uuid(document_id), _as_uuid(user_id)
    records = [
        (doc_id, uid, c["page_number"], c["chunk_index"], c["content"], c["embedding"])
        for c in chunks
    ]
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM chunks WHERE document_id = $1", doc_id)
        await conn.executemany(
            "INSERT INTO chunks (document_id, user_id, page_number, chunk_index, content, embedding) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            records,
        )
        await conn.execute(
            "UPDATE documents SET status = 'ready', error_message = NULL WHERE id = $1", doc_id
        )


async def delete_document(pool: asyncpg.Pool, *, user_id: Any, document_id: Any) -> str | None:
    """Delete the user's document (chunks and insights cascade). Returns its
    storage_path so the caller can remove the file, or None if not found."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "DELETE FROM documents WHERE id = $1 AND user_id = $2 RETURNING storage_path",
            _as_uuid(document_id),
            _as_uuid(user_id),
        )


async def get_stuck_documents(pool: asyncpg.Pool, *, older_than_minutes: int):
    """Documents left pending/processing by a restart or crash."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, user_id, storage_path FROM documents "
            "WHERE status IN ('pending', 'processing') "
            "AND created_at < now() - make_interval(mins => $1) ORDER BY created_at",
            older_than_minutes,
        )


async def mark_pending_if_failed(pool: asyncpg.Pool, *, user_id: Any, document_id: Any):
    """Flip failed -> pending for a retry; returns the row, or None if the
    document isn't the user's or isn't in the failed state."""
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "UPDATE documents SET status = 'pending', error_message = NULL "
            "WHERE id = $1 AND user_id = $2 AND status = 'failed' "
            "RETURNING id, filename, storage_path, status, error_message, created_at",
            _as_uuid(document_id),
            _as_uuid(user_id),
        )
