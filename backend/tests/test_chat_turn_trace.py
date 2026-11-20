"""The instrumented chat turn emits one structured `chat_turn` log + metrics,
with stage timings and approximate token counts, and still returns the same events."""

import asyncio
import logging
import uuid

from app.core.config import settings
from app.core.metrics import CHAT_TURNS
from app.db.models import ChatRequest
from app.ingestion import embedder
from app.routers import chat


def _candidate():
    return {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "filename": "a.pdf",
        "page_number": 1,
        "content": "The refund window is 30 days.",
        "similarity": 0.9,
    }


async def _collect(gen):
    return [e async for e in gen]


def test_turn_emits_trace_and_events(monkeypatch, caplog):
    async def fake_search(*a, **k):
        return [_candidate()]

    async def fake_stream(**k):
        for t in ["30 days ", "[1]."]:
            yield t

    monkeypatch.setattr(chat, "get_pool", lambda: object())
    monkeypatch.setattr(chat.search_mod, "search", fake_search)
    monkeypatch.setattr(chat, "stream_chat", fake_stream)
    monkeypatch.setattr(settings, "MMR_LAMBDA", 1.0)

    before = CHAT_TURNS.labels(outcome="ok")._value.get()
    with caplog.at_level(logging.INFO, logger="docent.trace"):
        events = asyncio.run(
            _collect(
                chat._run_chat_turn(
                    "11111111-1111-1111-1111-111111111111", ChatRequest(message="refund?")
                )
            )
        )

    kinds = [e for e, _ in events]
    assert kinds == ["token", "token", "citations"]
    assert events[-1][1]["citations"][0]["marker"] == 1
    assert CHAT_TURNS.labels(outcome="ok")._value.get() == before + 1

    rec = next(r for r in caplog.records if r.name == "docent.trace")
    assert rec.outcome == "ok" and rec.chunks == 1
    assert {"retrieve", "rank_prompt", "ttft", "generate", "total"} <= set(rec.stages_s)
    assert rec.prompt_tokens_approx > 0 and rec.completion_tokens_approx > 0


def test_no_context_turn_is_labelled(monkeypatch):
    async def fake_search(*a, **k):
        return []

    monkeypatch.setattr(chat, "get_pool", lambda: object())
    monkeypatch.setattr(chat.search_mod, "search", fake_search)
    before = CHAT_TURNS.labels(outcome="no_context")._value.get()
    events = asyncio.run(_collect(chat._run_chat_turn("u", ChatRequest(message="hi"))))
    assert [e for e, _ in events] == ["no_context"]
    assert CHAT_TURNS.labels(outcome="no_context")._value.get() == before + 1


def test_query_embedding_cache(monkeypatch):
    calls = []

    async def fake_embed(texts, model=None, **kw):
        calls.append(texts)
        return [[3.0, 4.0] + [0.0] * 3070]

    monkeypatch.setattr(embedder, "embed_texts", fake_embed)
    embedder._query_cache._data.clear()

    async def go():
        a = await embedder.embed_query("same question")
        b = await embedder.embed_query("same question")
        return a, b

    a, b = asyncio.run(go())
    assert a == b and len(calls) == 1
    a.append(9.9)  # callers can't corrupt the cached copy
    assert asyncio.run(embedder.embed_query("same question"))[-1] != 9.9


def test_agentic_mode_uses_planner_candidates_and_traces(monkeypatch, caplog):
    from app.retrieval.agent import AgentResult

    seen = {}

    async def fake_agentic(search_fn, question, history):
        seen["question"] = question
        extra = await search_fn("refined query", False)  # exercises the search closure
        seen["extra"] = len(extra)
        return AgentResult([_candidate()], [question, "refined query"], 1)

    async def fake_search(*a, **k):
        return [_candidate()]

    async def fake_stream(**k):
        yield "ok [1]"

    monkeypatch.setattr(chat, "get_pool", lambda: object())
    monkeypatch.setattr(chat.search_mod, "search", fake_search)
    monkeypatch.setattr(chat.agent_mod, "agentic_retrieve", fake_agentic)
    monkeypatch.setattr(chat, "stream_chat", fake_stream)
    monkeypatch.setattr(settings, "AGENTIC_SEARCH", True)
    monkeypatch.setattr(settings, "MMR_LAMBDA", 1.0)

    with caplog.at_level(logging.INFO, logger="docent.trace"):
        events = asyncio.run(
            _collect(chat._run_chat_turn("u", ChatRequest(message="compare a and b")))
        )

    assert [e for e, _ in events][-1] == "citations" and seen == {
        "question": "compare a and b",
        "extra": 1,
    }
    rec = next(r for r in caplog.records if r.name == "docent.trace")
    assert rec.agent_queries == ["compare a and b", "refined query"] and rec.agent_rounds == 1
