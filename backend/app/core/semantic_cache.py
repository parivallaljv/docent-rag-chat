"""In-process semantic answer cache: reuse a previous answer when a new
question's embedding is nearly identical (cosine >= threshold) for the same
user and document scope. Per-process and TTL-bound; only used for single-turn
questions (no history), so a hit never ignores conversational context."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from .config import settings


@dataclass
class CachedAnswer:
    answer: str
    citations: list[dict]
    expires: float
    embedding: list[float]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


class SemanticCache:
    def __init__(self, max_entries: int = 256, ttl: float = 3600.0, threshold: float = 0.95):
        self.max_entries, self.ttl, self.threshold = max_entries, ttl, threshold
        self._data: OrderedDict[tuple[Any, Any], list[CachedAnswer]] = OrderedDict()

    def get(self, user_id: Any, scope: Any, embedding: list[float]) -> CachedAnswer | None:
        entries = self._data.get((user_id, scope), [])
        now = time.monotonic()
        entries[:] = [e for e in entries if e.expires > now]
        best = max(entries, key=lambda e: _dot(e.embedding, embedding), default=None)
        if best is not None and _dot(best.embedding, embedding) >= self.threshold:
            return best
        return None

    def put(
        self, user_id: Any, scope: Any, embedding: list[float], answer: str, citations: list[dict]
    ) -> None:
        key = (user_id, scope)
        entries = self._data.setdefault(key, [])
        entries.append(CachedAnswer(answer, citations, time.monotonic() + self.ttl, embedding))
        del entries[:-8]  # at most 8 answers per user/scope
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def invalidate_user(self, user_id: Any) -> None:
        for key in [k for k in self._data if k[0] == user_id]:
            del self._data[key]


semantic_cache = SemanticCache(
    ttl=settings.SEMANTIC_CACHE_TTL_SECONDS, threshold=settings.SEMANTIC_CACHE_THRESHOLD
)
