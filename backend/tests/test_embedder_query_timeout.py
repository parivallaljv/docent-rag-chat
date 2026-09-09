"""Unit test for embed_query's timeout guard.

Regression coverage for a latency bug found alongside the chat-generation
timeout issues (2026-09-09): embed_query() (used on the critical path of
every live chat turn, before retrieval/generation even start) called
embed_texts() with no timeout of any kind -- only call_with_backoff's retry
budget (5 retries, capped at 30s each) bounded it, and a genuinely stalled
embedding call could hang a chat turn indefinitely with zero user-visible
feedback. Mocks embed_texts so no live API key/network is needed.
"""
from __future__ import annotations

import asyncio

import pytest

from app.ingestion import embedder


def _run(coro):
    return asyncio.run(coro)


def test_embed_query_times_out_instead_of_hanging_forever(monkeypatch):
    async def hangs_forever(texts, model=None):
        await asyncio.sleep(10)  # far longer than the timeout under test
        raise AssertionError("unreachable -- should be cut off by the timeout")

    monkeypatch.setattr(embedder, "embed_texts", hangs_forever)
    monkeypatch.setattr(embedder, "_QUERY_EMBED_TIMEOUT_SECONDS", 0.2)

    with pytest.raises(TimeoutError):
        _run(embedder.embed_query("what is the PTO policy?"))


def test_embed_query_still_returns_normally_when_fast(monkeypatch):
    async def fast_embed(texts, model=None):
        assert texts == ["hello"]
        return [[3.0, 4.0] + [0.0] * (embedder.EMBEDDING_OUTPUT_DIM - 2)]

    monkeypatch.setattr(embedder, "embed_texts", fast_embed)
    monkeypatch.setattr(embedder, "_QUERY_EMBED_TIMEOUT_SECONDS", 5.0)

    vector = _run(embedder.embed_query("hello"))

    assert len(vector) == embedder.EMBEDDING_OUTPUT_DIM
    # [3, 4, 0, 0, ...] normalized -> [0.6, 0.8, 0, 0, ...]
    assert vector[0] == pytest.approx(0.6)
    assert vector[1] == pytest.approx(0.8)
