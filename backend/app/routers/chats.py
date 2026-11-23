"""Conversation CRUD: GET/POST /chats, GET /chats/{id}/messages, DELETE /chats/{id}.
Messages are written by the chat WebSocket, not by this router."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import get_current_user_id
from ..db import queries
from ..db.client import get_pool
from ..db.models import ChatCreateRequest, ChatResponse, StoredMessage

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=list[ChatResponse])
async def list_chats(user_id: str = Depends(get_current_user_id)):
    return [ChatResponse(**r) for r in await queries.list_chats(get_pool(), user_id=user_id)]


@router.post("", response_model=ChatResponse, status_code=201)
async def create_chat(
    payload: ChatCreateRequest | None = None, user_id: str = Depends(get_current_user_id)
):
    row = await queries.create_chat(
        get_pool(), user_id=user_id, title=payload.title if payload else None
    )
    return ChatResponse(**row)


@router.get("/{chat_id}/messages", response_model=list[StoredMessage])
async def list_messages(chat_id: uuid.UUID, user_id: str = Depends(get_current_user_id)):
    pool = get_pool()
    if await queries.get_chat(pool, user_id=user_id, chat_id=chat_id) is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    out = []
    for r in await queries.list_messages(pool, user_id=user_id, chat_id=chat_id):
        d = dict(r)
        if isinstance(d.get("citations"), str):
            d["citations"] = json.loads(d["citations"])
        out.append(StoredMessage(**d))
    return out


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: uuid.UUID, user_id: str = Depends(get_current_user_id)) -> None:
    if not await queries.delete_chat(get_pool(), user_id=user_id, chat_id=chat_id):
        raise HTTPException(status_code=404, detail="Chat not found.")
