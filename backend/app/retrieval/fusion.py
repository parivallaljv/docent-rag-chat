"""Reciprocal Rank Fusion: merge several best-first rankings into one without
having to calibrate their (incomparable) scores against each other."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import TypeVar

T = TypeVar("T")


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[T]],
    key: Callable[[T], Hashable],
    k: int = 60,
) -> list[T]:
    """score(d) = sum over rankings of 1 / (k + rank(d)), rank starting at 1.
    Returns each distinct item (first-seen instance) best-first. Ties keep the
    order of first appearance, so the result is deterministic."""
    scores: dict[Hashable, float] = {}
    items: dict[Hashable, T] = {}
    order: dict[Hashable, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            ident = key(item)
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (k + rank)
            items.setdefault(ident, item)
            order.setdefault(ident, len(order))
    return [items[i] for i in sorted(scores, key=lambda i: (-scores[i], order[i]))]
