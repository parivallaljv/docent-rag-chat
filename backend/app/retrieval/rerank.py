"""Maximal Marginal Relevance (MMR) reranking over already-fetched
(embedding, chunk) candidates. Pure math, no external API calls -- fully
unit-testable without any credentials.

Relevance-to-query is taken as given (e.g. the cosine similarity pgvector
already computed during the kNN search in db.queries.search_chunks) rather
than recomputed here, so this module never needs the query embedding itself
-- only pairwise similarity *between* candidates, for the diversity term.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TypeVar

Vector = Sequence[float]
T = TypeVar("T")


def dot(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b))


def norm(a: Vector) -> float:
    return math.sqrt(dot(a, a))


def cosine_similarity(a: Vector, b: Vector) -> float:
    na, nb = norm(a), norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return dot(a, b) / (na * nb)


def mmr_rerank(
    candidates: list[T],
    embedding_fn: Callable[[T], Vector],
    relevance_fn: Callable[[T], float],
    top_k: int = 5,
    lambda_mult: float = 0.5,
) -> list[T]:
    """Greedily select up to top_k candidates, at each step maximizing:

        lambda_mult * relevance(c) - (1 - lambda_mult) * max(sim(c, s) for s in selected)

    lambda_mult=1.0 degenerates to pure relevance ranking (diversity term
    ignored); lower values favor diversity more heavily. Returns candidates
    in selection order (most relevant/diverse first).
    """
    if not candidates:
        return []
    top_k = min(top_k, len(candidates))
    remaining = list(candidates)
    relevance = {id(c): relevance_fn(c) for c in remaining}
    embeddings = {id(c): embedding_fn(c) for c in remaining}

    selected: list[T] = []
    while remaining and len(selected) < top_k:
        if not selected:
            best = max(remaining, key=lambda c: relevance[id(c)])
        else:

            def mmr_score(c: T) -> float:
                diversity_penalty = max(
                    cosine_similarity(embeddings[id(c)], embeddings[id(s)]) for s in selected
                )
                return lambda_mult * relevance[id(c)] - (1 - lambda_mult) * diversity_penalty

            best = max(remaining, key=mmr_score)
        selected.append(best)
        remaining.remove(best)
    return selected
