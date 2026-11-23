"""Answer feedback: POST /messages/{id}/feedback (thumbs up/down)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import get_current_user_id
from ..db import queries
from ..db.client import get_pool
from ..db.models import FeedbackRequest

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("/{message_id}/feedback", status_code=204)
async def post_feedback(
    message_id: uuid.UUID,
    payload: FeedbackRequest,
    user_id: str = Depends(get_current_user_id),
) -> None:
    ok = await queries.upsert_feedback(
        get_pool(),
        user_id=user_id,
        message_id=message_id,
        rating=payload.rating,
        comment=(payload.comment or "").strip() or None,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Answer not found.")
