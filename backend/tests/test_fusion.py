import asyncio

from app.core.config import settings
from app.retrieval import rewrite
from app.retrieval.fusion import reciprocal_rank_fusion
from eval.bm25 import BM25


def test_rrf_rewards_agreement_and_is_deterministic():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "d"]], key=lambda x: x)
    assert set(fused[:2]) == {"b", "c"}  # items both rankings agree on outrank singletons
    assert set(fused) == {"a", "b", "c", "d"}
    assert fused == reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "d"]], key=lambda x: x)


def test_rrf_single_list_preserves_order():
    assert reciprocal_rank_fusion([["x", "y", "z"]], key=lambda x: x) == ["x", "y", "z"]


def test_bm25_prefers_term_match():
    s = BM25(["adam optimizer settings", "sine cosine positions", "gpu hardware"]).scores("adam")
    assert s[0] > 0 and s[1] == 0 and s[2] == 0


def test_rewrite_disabled_or_no_history_skips_llm(monkeypatch):
    monkeypatch.setattr(settings, "QUERY_REWRITE", True)
    assert asyncio.run(rewrite.rewrite_query("hi", [])) is None
    monkeypatch.setattr(settings, "QUERY_REWRITE", False)
    assert asyncio.run(rewrite.rewrite_query("hi", [object()])) is None


def test_rewrite_failure_falls_back(monkeypatch):
    class Turn:
        role, content = "user", "tell me about BERT"

    async def boom(*a, **k):
        raise RuntimeError("quota")
        yield  # pragma: no cover

    monkeypatch.setattr(settings, "QUERY_REWRITE", True)
    monkeypatch.setattr(rewrite.gemini_client, "stream_chat", boom)
    assert asyncio.run(rewrite.rewrite_query("how big is it?", [Turn()])) is None


def test_rewrite_returns_clean_text(monkeypatch):
    class Turn:
        role, content = "user", "tell me about BERT"

    async def fake(*a, **k):
        yield ' "How many parameters does BERT have?" '

    monkeypatch.setattr(settings, "QUERY_REWRITE", True)
    monkeypatch.setattr(rewrite.gemini_client, "stream_chat", fake)
    assert (
        asyncio.run(rewrite.rewrite_query("how big is it?", [Turn()]))
        == "How many parameters does BERT have?"
    )
