"""Embeds a query string and fetches candidate chunks from Postgres via
pgvector kNN search, scoped to a user (and optionally a single document).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from ..core.config import settings
from ..db import queries
from ..ingestion.embedder import embed_query
from .fusion import reciprocal_rank_fusion
from .hyde import hypothetical_answer
from .llm_rerank import llm_rerank
from .rerank import dot
from .rewrite import rewrite_query

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
logger = logging.getLogger(__name__)

_HISTORY_TURNS_FOR_QUERY_EXPANSION = 4


@dataclass
class Candidate:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    content: str
    embedding: list[float]
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
    document_id: UUID | None = None,
    top_n: int = 20,
    history: Sequence[Any] | None = None,
) -> list[Candidate]:
    """Embed `query_text` (expanded with recent chat `history`, if given, so
    reference-heavy follow-ups retain their topical anchor) and return the
    top_n most similar chunks for this user (optionally scoped to a single
    document), as raw candidates ready for MMR reranking."""
    rewritten = await rewrite_query(query_text, history or [])
    expanded_query = rewritten or _expand_query_with_history(query_text, history or [])
    query_embedding = await embed_query(expanded_query)
    dense_vec = query_embedding
    if settings.HYDE:
        hypo = await hypothetical_answer(query_text)
        if hypo:
            dense_vec = await embed_query(hypo)
    dense_rows = await queries.search_chunks(
        pool,
        user_id=user_id,
        query_embedding=dense_vec,
        document_id=document_id,
        limit=top_n,
    )
    rows = list(dense_rows)
    if settings.HYBRID_SEARCH:
        try:
            keyword_rows = await queries.keyword_search_chunks(
                pool,
                user_id=user_id,
                query_text=rewritten or query_text,
                document_id=document_id,
                limit=top_n,
            )
        except asyncpg.UndefinedColumnError:
            # Migration 005 not applied yet: degrade to dense-only, don't fail chat.
            logger.warning("chunks.content_tsv missing; apply migration 005. Using dense only.")
            keyword_rows = []
        by_id = {r["id"]: r for r in [*dense_rows, *keyword_rows]}
        fused = reciprocal_rank_fusion(
            [[r["id"] for r in dense_rows], [r["id"] for r in keyword_rows]],
            key=lambda i: i,
            k=settings.RRF_K,
        )
        rows = [by_id[i] for i in fused[:top_n]]

    candidates = []
    for row in rows:
        embedding = row["embedding"].to_list()
        candidates.append(
            Candidate(
                chunk_id=row["id"],
                document_id=row["document_id"],
                filename=row["filename"],
                page_number=row["page_number"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                embedding=embedding,
                # True cosine for every candidate (keyword-only hits carry no
                # dense score), so the relevance guardrail stays meaningful.
                similarity=dot(embedding, query_embedding),
            )
        )
    if settings.RERANKER == "llm":
        candidates = await llm_rerank(query_text, candidates)
    return candidates
