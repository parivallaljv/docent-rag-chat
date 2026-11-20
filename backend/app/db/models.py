"""Pydantic models: DB row shapes plus API request/response bodies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal["pending", "processing", "ready", "failed"]


class Document(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    storage_path: str
    status: DocumentStatus = "pending"
    error_message: str | None = None
    created_at: datetime


class Chunk(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID
    page_number: int
    chunk_index: int
    content: str
    embedding: list[float] | None = None


# --- /documents ---


class DocumentCreateRequest(BaseModel):
    storage_path: str
    filename: str


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: DocumentStatus
    error_message: str | None = None
    created_at: datetime


# --- /chat ---


MAX_HISTORY_ITEMS = 20


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    document_id: uuid.UUID | None = None
    # When set, history is loaded from (and the turn saved to) this chat
    # server-side; client-sent `history` is then ignored.
    chat_id: uuid.UUID | None = None
    history: list[ChatMessage] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)


class Citation(BaseModel):
    marker: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int
    similarity: float


# --- /chats ---


class ChatCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ChatResponse(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class StoredMessage(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[dict] | None = None
    created_at: datetime
