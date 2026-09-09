"""Raw SQL access to Postgres via the shared asyncpg pool. No ORM: every
query here is hand-written SQL, scoped to a user_id (and, for search,
optionally a single document_id).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Sequence

import asyncpg


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
    error_message: Optional[str] = None,
) -> None:
    query = """
        UPDATE documents
        SET status = $2, error_message = $3
        WHERE id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute(query, _as_uuid(document_id), status, error_message)


async def list_documents(pool: asyncpg.Pool, *, user_id: Any) -> List[asyncpg.Record]:
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
    chunks: Sequence[Dict[str, Any]],
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
    document_id: Optional[Any] = None,
    limit: int = 20,
) -> List[asyncpg.Record]:
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

    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)
