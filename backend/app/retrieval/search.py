"""Embeds a query string and fetches candidate chunks from Postgres via
pgvector kNN search, scoped to a user (and optionally a single document).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence
from uuid import UUID

import asyncpg

from ..db import queries
from ..ingestion.embedder import embed_query

# How many recent chat turns to fold into the embedded query text. A short
# follow-up like "What year did that happen?" carries almost no retrievable
# signal on its own -- measured directly against this project's live data,
# a bare pronoun follow-up scored ~0.49 cosine similarity against the chunk
# that actually answers it (below the 0.55 guardrail), while the original
# question that established the topic scored ~0.70. Concatenating recent
# history ahead of the new message before embedding fixes this cheaply: no
# extra Gemini call is needed (a "real" query-rewrite would cost one LLM
# round-trip per follow-up, doubling quota usage for every multi-turn
# conversation), at the cost of some signal dilution on longer histories --
# hence keeping this window short.
_HISTORY_TURNS_FOR_QUERY_EXPANSION = 4


@dataclass
class Candidate:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    content: str
    embedding: List[float]
    similarity: float


def _expand_query_with_history(query_text: str, history: Sequence[Any]) -> str:
    if not history:
        return query_text
    recent = list(history)[-_HISTORY_TURNS_FOR_QUERY_EXPANSION:]
    context = " ".join(turn.content for turn in recent if turn.content)
    if not context:
        return query_text
    return f"{context} {query_text}"


async def search(
    pool: asyncpg.Pool,
    *,
    user_id: Any,
    query_text: str,
    document_id: Optional[UUID] = None,
    top_n: int = 20,
    history: Optional[Sequence[Any]] = None,
) -> List[Candidate]:
    """Embed `query_text` (expanded with recent chat `history`, if given, so
    reference-heavy follow-ups retain their topical anchor) and return the
    top_n most similar chunks for this user (optionally scoped to a single
    document), as raw candidates ready for MMR reranking."""
    expanded_query = _expand_query_with_history(query_text, history or [])
    query_embedding = await embed_query(expanded_query)
    rows = await queries.search_chunks(
        pool,
        user_id=user_id,
        query_embedding=query_embedding,
        document_id=document_id,
        limit=top_n,
    )
    return [
        Candidate(
            chunk_id=row["id"],
            document_id=row["document_id"],
            filename=row["filename"],
            page_number=row["page_number"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            embedding=row["embedding"].to_list(),
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]
