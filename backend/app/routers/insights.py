"""POST /documents/{id}/insights: summary, key facts or quiz for one document.
Results are cached per (document, kind); `refresh` regenerates."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import insights as insights_mod
from ..core.auth import get_current_user_id
from ..core.metrics import RATE_LIMITED
from ..core.rate_limit import check_user_rate_limit, enforce_gemini_quota
from ..db import queries
from ..db.client import get_pool
from ..llm.structured import StructuredGenerationError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["insights"])


class InsightRequest(BaseModel):
    kind: insights_mod.InsightKind
    refresh: bool = False


class InsightResponse(BaseModel):
    kind: insights_mod.InsightKind
    cached: bool
    result: dict


@router.post("/{document_id}/insights", response_model=InsightResponse)
async def create_insight(
    document_id: uuid.UUID,
    payload: InsightRequest,
    user_id: str = Depends(get_current_user_id),
) -> InsightResponse:
    pool = get_pool()
    doc = await queries.get_document(pool, user_id=user_id, document_id=document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc["status"] != "ready":
        raise HTTPException(status_code=409, detail="This document hasn't finished processing yet.")

    if not payload.refresh:
        cached = await queries.get_insight(
            pool, user_id=user_id, document_id=document_id, kind=payload.kind
        )
        if cached is not None:
            return InsightResponse(kind=payload.kind, cached=True, result=cached)

    if not check_user_rate_limit(user_id):
        RATE_LIMITED.labels(kind="user").inc()
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")
    await enforce_gemini_quota()  # raises a clean 429 when the daily AI budget is spent

    chunks = await queries.get_document_chunks(pool, user_id=user_id, document_id=document_id)
    if not chunks:
        raise HTTPException(status_code=409, detail="This document has no extracted text.")
    try:
        result = await insights_mod.generate_insight(payload.kind, doc["filename"], chunks)
    except StructuredGenerationError:
        logger.exception("insight generation failed")
        raise HTTPException(
            status_code=503, detail="The AI is unavailable right now. Please try again shortly."
        ) from None
    await queries.upsert_insight(
        pool, user_id=user_id, document_id=document_id, kind=payload.kind, result=result
    )
    return InsightResponse(kind=payload.kind, cached=False, result=result)
