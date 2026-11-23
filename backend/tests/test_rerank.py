"""Unit tests for app.retrieval.rerank's pure-python MMR reranking, using
synthetic embeddings/relevance scores. No external calls, no credentials.
"""

from app.retrieval.rerank import cosine_similarity, mmr_rerank


def _candidate(cid, embedding, relevance):
    return {"id": cid, "embedding": embedding, "relevance": relevance}


EMBED = lambda c: c["embedding"]  # noqa: E731
REL = lambda c: c["relevance"]  # noqa: E731


def test_empty_candidates_returns_empty_list():
    assert mmr_rerank([], EMBED, REL, top_k=5) == []


def test_top_k_limits_number_of_results():
    candidates = [_candidate(i, [1.0, 0.0], 1.0 - i * 0.01) for i in range(10)]
    result = mmr_rerank(candidates, EMBED, REL, top_k=3, lambda_mult=0.5)
    assert len(result) == 3


def test_top_k_larger_than_pool_returns_all():
    candidates = [_candidate(i, [1.0, 0.0], 1.0 - i * 0.1) for i in range(3)]
    result = mmr_rerank(candidates, EMBED, REL, top_k=10)
    assert len(result) == 3


def test_lambda_one_degenerates_to_pure_relevance_ranking():
    # With lambda_mult=1.0 the diversity term is fully suppressed, so the
    # order should exactly match sorting by relevance descending, even
    # though candidate A and B share an identical embedding.
    a = _candidate("a", [1.0, 0.0], 0.95)
    b = _candidate("b", [1.0, 0.0], 0.90)  # near-duplicate embedding of a
    c = _candidate("c", [0.0, 1.0], 0.80)
    result = mmr_rerank([a, b, c], EMBED, REL, top_k=3, lambda_mult=1.0)
    assert [r["id"] for r in result] == ["a", "b", "c"]


def test_diversity_term_prefers_distinct_chunk_over_near_duplicate():
    # A: highest relevance. B: near-duplicate embedding of A, slightly lower
    # relevance. C: orthogonal (diverse) embedding, lower relevance still.
    # With lambda_mult=0.5, after selecting A first, C should be preferred
    # over B for the second slot because B is redundant with A.
    a = _candidate("a", [1.0, 0.0], 0.90)
    b = _candidate("b", [1.0, 0.0], 0.85)
    c = _candidate("c", [0.0, 1.0], 0.70)
    result = mmr_rerank([a, b, c], EMBED, REL, top_k=2, lambda_mult=0.5)
    assert [r["id"] for r in result] == ["a", "c"]


def test_first_selection_is_always_highest_relevance():
    a = _candidate("a", [1.0, 0.0, 0.0], 0.5)
    b = _candidate("b", [0.0, 1.0, 0.0], 0.99)
    c = _candidate("c", [0.0, 0.0, 1.0], 0.3)
    result = mmr_rerank([a, b, c], EMBED, REL, top_k=1, lambda_mult=0.5)
    assert [r["id"] for r in result] == ["b"]


def test_cosine_similarity_basic_properties():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0
    # Zero vector is defined as similarity 0 (guards against div-by-zero).
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_selection_order_has_no_duplicates():
    candidates = [_candidate(i, [1.0, i * 0.01], 1.0 - i * 0.05) for i in range(8)]
    result = mmr_rerank(candidates, EMBED, REL, top_k=8, lambda_mult=0.4)
    ids = [r["id"] for r in result]
    assert len(ids) == len(set(ids)) == 8
