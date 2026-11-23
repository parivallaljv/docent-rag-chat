"""GET /usage: the caller's approximate token usage and cost, last N days."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..core.auth import get_current_user_id
from ..db import queries
from ..db.client import get_pool

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
async def get_usage(
    days: int = Query(30, ge=1, le=90), user_id: str = Depends(get_current_user_id)
):
    totals, daily = await queries.usage_summary(get_pool(), user_id=user_id, days=days)
    return {"days": days, "totals": totals, "daily": daily, "note": "token counts are approximate"}
