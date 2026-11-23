"""Rank-based retrieval metrics. `ranked` is the list of page keys returned
(best first, duplicates allowed); `relevant` is the set of correct page keys."""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence


def hit_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    """1.0 if any relevant page appears in the top-k results."""
    return float(any(r in relevant for r in ranked[:k]))


def recall_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Fraction of distinct relevant pages found in the top-k results."""
    if not relevant:
        return 0.0
    found = {r for r in ranked[:k] if r in relevant}
    return len(found) / len(set(relevant))


def mrr(ranked: Sequence[str], relevant: Collection[str]) -> float:
    for i, r in enumerate(ranked, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Binary-relevance nDCG; a page only counts the first time it appears."""
    seen: set[str] = set()
    dcg = 0.0
    for i, r in enumerate(ranked[:k], start=1):
        if r in relevant and r not in seen:
            seen.add(r)
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(set(relevant)), k) + 1))
    return dcg / ideal if ideal else 0.0
