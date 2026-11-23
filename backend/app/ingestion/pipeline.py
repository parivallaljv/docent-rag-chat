"""Orchestrates document ingestion end to end:

    download bytes -> parse -> chunk -> embed (batched) -> insert chunks -> mark ready

Designed to be kicked off as a FastAPI BackgroundTask from routers.documents,
so it has no request left to raise exceptions to -- failures are caught and
recorded on the document row (status='failed', error_message=...) instead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from supabase import Client, create_client

from ..core.config import settings
from ..db import queries
from ..db.client import get_pool
from .chunker import chunk_pages
from .embedder import embed_chunks
from .ocr import OcrUnavailable, ocr_pdf
from .parser import extract_document_pages

logger = logging.getLogger(__name__)

_supabase_client: Client | None = None

# Belt-and-suspenders cap matching the frontend's own 25MB check and the
# Storage bucket's file_size_limit (migrations/003_validation.sql) -- the
# bucket limit is the real enforcement point since uploads go browser ->
# Storage directly, but a stale/bypassed client shouldn't be trusted either.
_MAX_PDF_BYTES = 25 * 1024 * 1024


def _get_supabase_client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _supabase_client


def download_from_storage(storage_path: str, bucket: str | None = None) -> bytes:
    """Download raw file bytes from Supabase Storage using the service-role
    key. Server-side only -- this key must never be exposed to the frontend;
    the frontend uploads directly to Storage using its own (RLS-scoped)
    session and only sends us the resulting storage_path."""
    client = _get_supabase_client()
    bucket_name = bucket or settings.SUPABASE_STORAGE_BUCKET
    return client.storage.from_(bucket_name).download(storage_path)


def delete_from_storage(storage_path: str, bucket: str | None = None) -> None:
    client = _get_supabase_client()
    client.storage.from_(bucket or settings.SUPABASE_STORAGE_BUCKET).remove([storage_path])


async def recover_stuck_documents() -> int:
    """Re-run ingestion for documents a restart left pending/processing.
    Sequential on purpose (embedding quota). Returns how many were retried."""
    pool = get_pool()
    rows = await queries.get_stuck_documents(
        pool, older_than_minutes=settings.STUCK_DOCUMENT_MINUTES
    )
    for row in rows:
        logger.warning("Recovering stuck document %s", row["id"])
        await run_ingestion_pipeline(row["id"], row["user_id"], row["storage_path"])
    return len(rows)


async def run_ingestion_pipeline(document_id: Any, user_id: Any, storage_path: str) -> None:
    pool = get_pool()
    try:
        # Defense-in-depth: the router already rejects a storage_path that
        # doesn't belong to this user, but this function bypasses Storage RLS
        # via the service-role key, so it must never trust a caller that
        # skipped (or a future caller that forgets) that check.
        if not storage_path.startswith(f"{user_id}/"):
            await queries.update_document_status(
                pool,
                document_id=document_id,
                status="failed",
                error_message="This file path doesn't belong to your account.",
            )
            return

        await queries.update_document_status(pool, document_id=document_id, status="processing")

        # supabase-py is synchronous; keep it off the event loop.
        pdf_bytes = await asyncio.to_thread(download_from_storage, storage_path)

        if len(pdf_bytes) > _MAX_PDF_BYTES:
            await queries.update_document_status(
                pool,
                document_id=document_id,
                status="failed",
                error_message="This file is larger than 25 MB.",
            )
            return

        try:
            pages = extract_document_pages(storage_path, pdf_bytes)
        except Exception:
            logger.exception("Failed to parse document %s", document_id)
            await queries.update_document_status(
                pool,
                document_id=document_id,
                status="failed",
                error_message=(
                    "This file couldn't be read. It may be corrupted, "
                    "password-protected or in an unsupported format."
                ),
            )
            return

        text_chunks = chunk_pages(
            pages,
            target_tokens=settings.CHUNK_TARGET_TOKENS,
            overlap_ratio=settings.CHUNK_OVERLAP_RATIO,
        )

        if not text_chunks and storage_path.lower().endswith(".pdf"):
            # Scanned PDF? Try OCR before giving up.
            try:
                logger.info("No text layer in document %s; trying OCR", document_id)
                ocr_pages = await ocr_pdf(pdf_bytes)
                text_chunks = chunk_pages(
                    ocr_pages,
                    target_tokens=settings.CHUNK_TARGET_TOKENS,
                    overlap_ratio=settings.CHUNK_OVERLAP_RATIO,
                )
            except OcrUnavailable as exc:
                logger.warning("OCR unavailable for document %s: %s", document_id, exc)

        if not text_chunks:
            await queries.update_document_status(
                pool,
                document_id=document_id,
                status="failed",
                error_message="No extractable text was found in this file.",
            )
            return

        embeddings = await embed_chunks([c.content for c in text_chunks])

        records = [
            {
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "embedding": embedding,
            }
            for c, embedding in zip(text_chunks, embeddings)
        ]
        await queries.replace_chunks_and_mark_ready(
            pool, document_id=document_id, user_id=user_id, chunks=records
        )
        logger.info("Ingestion complete for document %s: %d chunks", document_id, len(records))
    except Exception as exc:  # noqa: BLE001 - genuinely want to catch everything here
        logger.exception("Ingestion pipeline failed for document %s", document_id)
        await queries.update_document_status(
            pool,
            document_id=document_id,
            status="failed",
            error_message=str(exc)[:500],
        )
