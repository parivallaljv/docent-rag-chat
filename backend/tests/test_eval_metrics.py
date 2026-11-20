import math

from eval.metrics import hit_at_k, mrr, ndcg_at_k, recall_at_k

REL = {"a:1", "a:2"}


def test_hit_and_recall():
    ranked = ["b:1", "a:2", "c:3", "a:1"]
    assert hit_at_k(ranked, REL, 1) == 0.0
    assert hit_at_k(ranked, REL, 2) == 1.0
    assert recall_at_k(ranked, REL, 2) == 0.5
    assert recall_at_k(ranked, REL, 4) == 1.0
    assert recall_at_k(ranked, set(), 4) == 0.0


def test_mrr():
    assert mrr(["x", "a:1"], REL) == 0.5
    assert mrr(["x", "y"], REL) == 0.0


def test_ndcg_perfect_and_duplicates():
    assert ndcg_at_k(["a:1", "a:2"], REL, 5) == 1.0
    # a repeated page must not be counted twice
    assert math.isclose(ndcg_at_k(["a:1", "a:1"], {"a:1"}, 5), 1.0)
    assert ndcg_at_k(["x", "y"], REL, 5) == 0.0
