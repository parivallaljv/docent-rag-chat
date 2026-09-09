"""POST /documents and GET /documents. Both require a valid Supabase JWT.

The frontend uploads the PDF straight to Supabase Storage from the browser
(using its own session), then calls POST /documents with the resulting
storage_path so this backend can pick it up asynchronously.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..core.auth import get_current_user_id
from ..db import queries
from ..db.client import get_pool
from ..db.models import DocumentCreateRequest, DocumentResponse
from ..ingestion.pipeline import run_ingestion_pipeline

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
    if not payload.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

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


@router.get("", response_model=List[DocumentResponse])
async def list_user_documents(user_id: str = Depends(get_current_user_id)) -> List[DocumentResponse]:
    pool = get_pool()
    rows = await queries.list_documents(pool, user_id=user_id)
    return [DocumentResponse(**row) for row in rows]
