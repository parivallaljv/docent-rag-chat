import asyncio
from types import SimpleNamespace

from app.core.semantic_cache import SemanticCache
from app.ingestion import contextual
from app.retrieval import hyde, llm_rerank


def run(c):
    return asyncio.run(c)


def test_apply_order_handles_junk():
    assert llm_rerank.apply_order(list("abcd"), [3, 3, 9, 0, 1]) == ["c", "a", "b", "d"]


def test_llm_rerank_orders_and_degrades(monkeypatch):
    items = [SimpleNamespace(content=t) for t in ["x", "y", "z"]]

    async def ok(*a, **k):
        return llm_rerank.Ranking(order=[3, 1, 2])

    monkeypatch.setattr(llm_rerank, "generate_structured", ok)
    assert [i.content for i in run(llm_rerank.llm_rerank("q", items))] == ["z", "x", "y"]

    async def bad(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(llm_rerank, "generate_structured", bad)
    assert run(llm_rerank.llm_rerank("q", items)) == items
    try:
        run(llm_rerank.llm_rerank("q", items, strict=True))
        raise AssertionError("expected raise")
    except RuntimeError:
        pass


def test_hyde_degrades(monkeypatch):
    async def bad(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(hyde, "generate_structured", bad)
    assert run(hyde.hypothetical_answer("q")) is None

    async def ok(*a, **k):
        return hyde.Hypothetical(passage="  An answer.  ")

    monkeypatch.setattr(hyde, "generate_structured", ok)
    assert run(hyde.hypothetical_answer("q")) == "An answer."


def test_contextualize_batches_and_falls_back(monkeypatch):
    calls = []

    async def fake(prompt, schema, **k):
        n = prompt.count("\n[")
        calls.append(n)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return contextual.Contexts(contexts=[f"ctx{i}" for i in range(contextual.BATCH)])

    monkeypatch.setattr(contextual, "generate_structured", fake)
    out = run(contextual.contextualize("doc", [f"c{i}" for i in range(15)]))
    assert len(out) == 15 and out[0] == "ctx0" and out[10:] == [""] * 5
    assert contextual.with_context("", "c") == "c"
    assert contextual.with_context("ctx", "c") == "ctx\n\nc"


def test_semantic_cache_scope_threshold_ttl():
    c = SemanticCache(ttl=100, threshold=0.95)
    c.put("u1", None, [1.0, 0.0], "ans", [{"id": 1}])
    assert c.get("u1", None, [1.0, 0.0]).answer == "ans"
    assert c.get("u1", None, [0.0, 1.0]) is None  # dissimilar
    assert c.get("u2", None, [1.0, 0.0]) is None  # other user
    assert c.get("u1", "doc", [1.0, 0.0]) is None  # other scope
    c.invalidate_user("u1")
    assert c.get("u1", None, [1.0, 0.0]) is None
    c2 = SemanticCache(ttl=-1, threshold=0.9)
    c2.put("u", None, [1.0], "a", [])
    assert c2.get("u", None, [1.0]) is None  # expired
