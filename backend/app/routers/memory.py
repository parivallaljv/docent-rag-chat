"""Editable user memory: GET/PUT/DELETE /memory. Injected into prompts as a
fenced block of the user's own notes (tone/context only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core.auth import get_current_user_id
from ..db import queries
from ..db.client import get_pool

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryBody(BaseModel):
    content: str = Field(max_length=2000)


@router.get("", response_model=MemoryBody)
async def get_memory(user_id: str = Depends(get_current_user_id)):
    return MemoryBody(content=await queries.get_memory(get_pool(), user_id=user_id) or "")


@router.put("", response_model=MemoryBody)
async def put_memory(body: MemoryBody, user_id: str = Depends(get_current_user_id)):
    text = body.content.strip()
    if text:
        await queries.upsert_memory(get_pool(), user_id=user_id, content=text)
    else:
        await queries.delete_memory(get_pool(), user_id=user_id)
    return MemoryBody(content=text)
