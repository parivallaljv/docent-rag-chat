"""Pydantic models: DB row shapes plus API request/response bodies."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

DocumentStatus = Literal["pending", "processing", "ready", "failed"]


class Document(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    storage_path: str
    status: DocumentStatus = "pending"
    error_message: Optional[str] = None
    created_at: datetime


class Chunk(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID
    page_number: int
    chunk_index: int
    content: str
    embedding: Optional[List[float]] = None


# --- /documents ---


class DocumentCreateRequest(BaseModel):
    storage_path: str
    filename: str


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: DocumentStatus
    error_message: Optional[str] = None
    created_at: datetime


# --- /chat ---


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    document_id: Optional[uuid.UUID] = None
    history: List[ChatMessage] = Field(default_factory=list)


class Citation(BaseModel):
    marker: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int
    similarity: float
