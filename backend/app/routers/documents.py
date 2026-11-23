"""POST /documents and GET /documents. Both require a valid Supabase JWT.

The frontend uploads the PDF straight to Supabase Storage from the browser
(using its own session), then calls POST /documents with the resulting
storage_path so this backend can pick it up asynchronously.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from ..agent.tools import run_comparison
from ..core.auth import get_current_user_id
from ..core.rate_limit import check_user_rate_limit, enforce_gemini_quota
from ..core.semantic_cache import semantic_cache
from ..db import queries
from ..db.client import get_pool
from ..db.models import DocumentCreateRequest, DocumentResponse
from ..ingestion.parser import is_supported
from ..ingestion.pipeline import delete_from_storage, run_ingestion_pipeline
from ..llm.structured import StructuredGenerationError
from ..retrieval import search as search_mod

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=201)
async def create_document(
    payload: DocumentCreateRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
) -> DocumentResponse:
    # The Storage bucket's own RLS policies scope uploads to `${user_id}/...`
    # for direct browser uploads, but this endpoint's caller could pass any
    # string here -- and the ingestion pipeline downloads via a service-role
    # key that bypasses Storage RLS entirely. Without this check, a client
    # could point at another user's file and have it ingested into their own
    # chunk store.
    if not payload.storage_path.startswith(f"{user_id}/"):
        raise HTTPException(
            status_code=400, detail="This file path doesn't belong to your account."
        )
    # The frontend already checks this before uploading, but a client is
    # never trusted to have actually done so.
    if not is_supported(payload.filename):
        raise HTTPException(
            status_code=400,
            detail="Supported files: PDF, DOCX, Markdown, TXT, HTML.",
        )

    pool = get_pool()
    try:
        row = await queries.insert_document(
            pool, user_id=user_id, filename=payload.filename, storage_path=payload.storage_path
        )
    except queries.DuplicateDocumentError:
        raise HTTPException(
            status_code=409,
            detail=f"You already have a file named '{payload.filename}'. "
            "Delete it first or rename the new one.",
        ) from None
    # Kick off ingestion after the response is sent; status starts 'pending'
    # and the pipeline moves it to 'processing' -> 'ready'/'failed'.
    background_tasks.add_task(run_ingestion_pipeline, row["id"], user_id, payload.storage_path)
    return DocumentResponse(**row)


@router.get("", response_model=list[DocumentResponse])
async def list_user_documents(
    user_id: str = Depends(get_current_user_id),
) -> list[DocumentResponse]:
    pool = get_pool()
    rows = await queries.list_documents(pool, user_id=user_id)
    return [DocumentResponse(**row) for row in rows]


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID, user_id: str = Depends(get_current_user_id)
) -> None:
    """Delete a document, its chunks/insights (cascade) and its stored file."""
    storage_path = await queries.delete_document(
        get_pool(), user_id=user_id, document_id=document_id
    )
    if storage_path is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    semantic_cache.invalidate_user(user_id)
    try:
        await asyncio.to_thread(delete_from_storage, storage_path)
    except Exception:
        # The DB row is gone (that's what hides it from the user); an orphaned
        # file is a cleanup problem, not a user-facing failure.
        logger.exception("Could not delete stored file %s", storage_path)


@router.post("/{document_id}/retry", response_model=DocumentResponse, status_code=202)
async def retry_document(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
) -> DocumentResponse:
    """Re-run ingestion for a failed document."""
    row = await queries.mark_pending_if_failed(get_pool(), user_id=user_id, document_id=document_id)
    if row is None:
        raise HTTPException(status_code=409, detail="Only your failed documents can be retried.")
    background_tasks.add_task(run_ingestion_pipeline, row["id"], user_id, row["storage_path"])
    return DocumentResponse(**row)


class CompareRequest(BaseModel):
    document_a: str = Field(max_length=200)  # filename or id
    document_b: str = Field(max_length=200)
    topic: str = Field(min_length=1, max_length=300)


@router.post("/compare")
async def compare_documents_endpoint(
    payload: CompareRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """Side-by-side similarities/differences of two of the user's documents."""
    if not check_user_rate_limit(user_id):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")
    await enforce_gemini_quota()
    pool = get_pool()
    docs = [
        d for d in await queries.list_documents(pool, user_id=user_id) if d["status"] == "ready"
    ]

    async def scoped(query: str, doc_id):
        return await search_mod.search(
            pool, user_id=user_id, query_text=query, document_id=doc_id, top_n=8
        )

    try:
        out = await run_comparison(
            docs, scoped, payload.document_a, payload.document_b, payload.topic
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StructuredGenerationError as exc:
        raise HTTPException(
            status_code=502, detail="The AI could not produce a comparison."
        ) from exc
    if out is None:
        raise HTTPException(status_code=409, detail="One document has no passages on that topic.")
    out["sources"] = [
        {"filename": c.filename, "page": c.page_number, "snippet": c.content[:200]}
        for c in out.pop("chunks")
    ]
    return out
