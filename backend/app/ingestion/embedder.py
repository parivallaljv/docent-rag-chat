"""Batch embedding of text chunks via Gemini's gemini-embedding-001 model.

gemini-embedding-001 natively returns 3072-dimensional vectors that ARE
L2-normalized by the API. To keep the pgvector column small (and search
fast) we store a Matryoshka-truncated 768-dim vector instead: take the first
768 values of the native output, then re-normalize. A truncated slice of a
normalized vector is NOT itself unit-length, so skipping the renormalization
step would silently break cosine-similarity search quality.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence

from ..core.cache import TTLCache
from ..core.config import settings
from ..core.metrics import CACHE
from ..llm.gemini_client import embed_texts

EMBEDDING_OUTPUT_DIM = 768
DEFAULT_BATCH_SIZE = 32  # within the 20-50 chunks/call guidance

# embed_query() sits on the critical path of every live chat turn (query
# embedding happens before retrieval/generation even start), unlike
# embed_chunks()'s background document-ingestion use. embed_texts() itself
# has no timeout of its own -- only call_with_backoff's retry budget (5
# retries, capped at 30s each) -- so a genuinely stalled connection there
# could hang a chat turn indefinitely with zero user-visible feedback. This
# timeout is deliberately scoped to embed_query only: tightening embed_texts
# itself (or its @with_backoff decorator) would also cut short ingestion's
# more-patient retry budget, where a slower but eventually-successful retry
# is preferable to failing a document upload outright.
_QUERY_EMBED_TIMEOUT_SECONDS = 15.0


def _truncate_and_normalize(
    vector: Sequence[float], dim: int = EMBEDDING_OUTPUT_DIM
) -> list[float]:
    truncated = list(vector[:dim])
    norm = math.sqrt(sum(v * v for v in truncated))
    if norm == 0:
        return truncated
    return [v / norm for v in truncated]


_query_cache: TTLCache[list[float]] = TTLCache(
    settings.EMBED_CACHE_SIZE, settings.EMBED_CACHE_TTL_SECONDS
)


def _task_kwargs(task_type: str) -> dict[str, str]:
    """Asymmetric retrieval embeddings: documents and queries get different
    Gemini task types. Off via EMBEDDING_TASK_TYPES=false (e.g. to stay
    compatible with chunks embedded before this was enabled)."""
    return {"task_type": task_type} if settings.EMBEDDING_TASK_TYPES else {}


async def embed_chunks(texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE) -> list[list[float]]:
    """Embed a list of chunk texts, batched (20-50/call), returning
    truncated + renormalized 768-dim vectors in the same order as `texts`."""
    if not texts:
        return []
    all_embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        raw_vectors = await embed_texts(
            batch, model=settings.EMBEDDING_MODEL, **_task_kwargs("RETRIEVAL_DOCUMENT")
        )
        all_embeddings.extend(_truncate_and_normalize(v) for v in raw_vectors)
    return all_embeddings


async def embed_query(text: str) -> list[float]:
    """Embed a single query string (e.g. a chat message) the same way as
    document chunks, so the resulting vector is directly comparable via
    cosine distance to the stored chunk embeddings.

    Bounded by _QUERY_EMBED_TIMEOUT_SECONDS (see module docstring above) so a
    stalled embedding call can't hang a live chat turn indefinitely; a
    timeout here raises asyncio.TimeoutError, which propagates up through
    retrieval.search.search() into routers.chat's existing broad exception
    handler (already yields a clean "Something went wrong preparing a
    response" error to the client)."""
    cache_key = (settings.EMBEDDING_MODEL, settings.EMBEDDING_TASK_TYPES, text)
    cached = _query_cache.get(cache_key)
    if cached is not None:
        CACHE.labels(cache="query_embedding", result="hit").inc()
        return list(cached)
    CACHE.labels(cache="query_embedding", result="miss").inc()
    vectors = await asyncio.wait_for(
        embed_texts([text], model=settings.EMBEDDING_MODEL, **_task_kwargs("RETRIEVAL_QUERY")),
        timeout=_QUERY_EMBED_TIMEOUT_SECONDS,
    )
    result = _truncate_and_normalize(vectors[0])
    _query_cache.set(cache_key, result)
    return list(result)
