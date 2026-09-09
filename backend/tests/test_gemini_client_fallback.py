"""Unit tests for stream_chat's per-model fallback loop.

Regression coverage for a real bug found via live testing (2026-09-09): a
transient overload (503/UNAVAILABLE) on the primary model was re-raised
immediately after its quick same-model retries, without ever trying the
other models in CHAT_MODEL_FALLBACKS -- even though that fallback list
exists precisely so a demo visitor can fail over to a healthier model. Only
quota-exhaustion (429/RESOURCE_EXHAUSTED) triggered the fallback before this
fix. These tests mock the genai client so no live API key/network is needed.
"""
from __future__ import annotations

import asyncio
import time
from typing import List

import pytest

from app.llm import gemini_client


def _collect(prompt: str, model: str) -> List[str]:
    """Run stream_chat to completion outside of a running event loop. The
    project has no pytest-asyncio dependency, so tests drive the async
    generator manually via asyncio.run rather than an @pytest.mark.asyncio
    test function."""

    async def _run() -> List[str]:
        return [token async for token in gemini_client.stream_chat(prompt=prompt, model=model)]

    return asyncio.run(_run())


class _FakeGeminiError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


class _FakeChunk:
    def __init__(self, text: str):
        self.text = text


async def _fake_stream(chunks: List[_FakeChunk]):
    for chunk in chunks:
        yield chunk


class _FakeModels:
    """Records which models were attempted and raises/returns per a
    caller-supplied script, mimicking client.aio.models.generate_content_stream."""

    def __init__(self, script: dict):
        self.script = script
        self.attempted: List[str] = []

    async def generate_content_stream(self, *, model, contents, config):
        self.attempted.append(model)
        outcome = self.script[model]
        if isinstance(outcome, Exception):
            raise outcome
        return _fake_stream(outcome)


class _FakeAio:
    def __init__(self, models: _FakeModels):
        self.models = models


class _FakeClient:
    def __init__(self, models: _FakeModels):
        self.aio = _FakeAio(models)


def _patch_client(monkeypatch, script: dict) -> _FakeModels:
    models = _FakeModels(script)
    monkeypatch.setattr(gemini_client, "get_client", lambda: _FakeClient(models))
    # chat_model_fallbacks_list is a derived read-only property; patch the
    # underlying field it parses instead.
    monkeypatch.setattr(gemini_client.settings, "CHAT_MODEL_FALLBACKS", "backup-model")
    # Force Groq off by default regardless of what's in the developer's real
    # .env (it may well have a real GROQ_API_KEY configured) -- tests that
    # want a Groq candidate in play set this back explicitly afterwards.
    monkeypatch.setattr(gemini_client.settings, "GROQ_API_KEY", "")
    # call_with_backoff's same-model retry sleeps for real between attempts;
    # skip that delay so these tests aren't slow.
    monkeypatch.setattr(gemini_client.asyncio, "sleep", lambda *_a, **_kw: _instant())
    return models


async def _instant() -> None:
    return None


def _unique_models_tried(models: _FakeModels) -> List[str]:
    """Which distinct models were attempted, in order -- ignoring how many
    same-model retries call_with_backoff made internally before giving up on
    each one, which isn't what these tests are about."""
    seen: List[str] = []
    for name in models.attempted:
        if not seen or seen[-1] != name:
            seen.append(name)
    return seen


def test_falls_back_to_next_model_on_transient_overload(monkeypatch):
    script = {
        "primary-model": _FakeGeminiError(503, "503 UNAVAILABLE. The model is overloaded."),
        "backup-model": [_FakeChunk("hello")],
    }
    models = _patch_client(monkeypatch, script)

    tokens = _collect(prompt="hi", model="primary-model")

    assert tokens == ["hello"]
    assert _unique_models_tried(models) == ["primary-model", "backup-model"]


def test_falls_back_to_next_model_on_quota_exhaustion(monkeypatch):
    script = {
        "primary-model": _FakeGeminiError(429, "429 RESOURCE_EXHAUSTED. Quota exceeded."),
        "backup-model": [_FakeChunk("hello")],
    }
    models = _patch_client(monkeypatch, script)

    tokens = _collect(prompt="hi", model="primary-model")

    assert tokens == ["hello"]
    assert _unique_models_tried(models) == ["primary-model", "backup-model"]


def test_raises_after_every_model_fails(monkeypatch):
    script = {
        "primary-model": _FakeGeminiError(503, "503 UNAVAILABLE. The model is overloaded."),
        "backup-model": _FakeGeminiError(503, "503 UNAVAILABLE. The model is overloaded."),
    }
    models = _patch_client(monkeypatch, script)

    with pytest.raises(_FakeGeminiError):
        _collect(prompt="hi", model="primary-model")

    assert _unique_models_tried(models) == ["primary-model", "backup-model"]


def test_does_not_fall_back_on_non_retryable_error(monkeypatch):
    script = {
        "primary-model": ValueError("bad request: missing field"),
        "backup-model": [_FakeChunk("hello")],
    }
    models = _patch_client(monkeypatch, script)

    with pytest.raises(ValueError):
        _collect(prompt="hi", model="primary-model")

    # Should not have wasted a call on the backup model for a permanent error.
    assert models.attempted == ["primary-model"]


def test_falls_back_to_next_model_on_bare_timeout_error(monkeypatch):
    # Regression test: a hung/slow model previously skipped the fallback
    # chain entirely on a plain TimeoutError (the exact bug behind a live
    # "The AI took too long to respond" report) because is_retryable_error
    # didn't recognize it. See test_rate_limit.py's companion unit test.
    script = {
        "primary-model": TimeoutError(),
        "backup-model": [_FakeChunk("hello")],
    }
    models = _patch_client(monkeypatch, script)

    tokens = _collect(prompt="hi", model="primary-model")

    assert tokens == ["hello"]
    assert _unique_models_tried(models) == ["primary-model", "backup-model"]


def test_falls_back_to_groq_after_every_gemini_model_fails(monkeypatch):
    # Simulate a Gemini-wide slowdown (not just one flaky model): both
    # configured Gemini models fail, so the last resort -- a completely
    # different vendor -- must be reached.
    script = {
        "primary-model": _FakeGeminiError(503, "503 UNAVAILABLE. The model is overloaded."),
        "backup-model": _FakeGeminiError(503, "503 UNAVAILABLE. The model is overloaded."),
    }
    models = _patch_client(monkeypatch, script)
    monkeypatch.setattr(gemini_client.settings, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(gemini_client.settings, "GROQ_MODEL", "groq-model")

    async def fake_open_groq_connection(*, model, prompt, system_instruction, temperature):
        assert model == "groq-model"

        async def _gen():
            yield "from groq"

        return _gen()

    monkeypatch.setattr(gemini_client, "_open_groq_connection", fake_open_groq_connection)

    tokens = _collect(prompt="hi", model="primary-model")

    assert tokens == ["from groq"]
    assert _unique_models_tried(models) == ["primary-model", "backup-model"]


def test_groq_not_attempted_when_api_key_unset(monkeypatch):
    # Default/unconfigured state: GROQ_API_KEY is "" (falsy), so Groq must
    # never be added to the candidate list -- behavior identical to before
    # Groq support existed.
    script = {
        "primary-model": _FakeGeminiError(503, "503 UNAVAILABLE. The model is overloaded."),
        "backup-model": _FakeGeminiError(503, "503 UNAVAILABLE. The model is overloaded."),
    }
    models = _patch_client(monkeypatch, script)
    monkeypatch.setattr(gemini_client.settings, "GROQ_API_KEY", "")

    def fail_if_called(**_kwargs):
        raise AssertionError("Groq should not be attempted when GROQ_API_KEY is unset")

    monkeypatch.setattr(gemini_client, "_open_groq_connection", fail_if_called)

    with pytest.raises(_FakeGeminiError):
        _collect(prompt="hi", model="primary-model")

    assert _unique_models_tried(models) == ["primary-model", "backup-model"]


def test_falls_back_to_groq_on_quota_exhausted_gemini_chain(monkeypatch):
    # A Groq 429 (per-minute rate limit) must not be reported as "daily AI
    # budget exhausted" -- that message belongs to Gemini's quota only. This
    # exercises the full path: Gemini quota-exhausted -> Groq's own 429 ->
    # raised as UpstreamChatError, and confirms it is NOT misclassified as
    # quota exhaustion (see test_rate_limit.py for the unit-level check).
    script = {
        "primary-model": _FakeGeminiError(429, "429 RESOURCE_EXHAUSTED. Quota exceeded."),
    }
    models = _patch_client(monkeypatch, script)
    # No sibling Gemini model configured for this test -- go straight from
    # the single Gemini candidate to Groq.
    monkeypatch.setattr(gemini_client.settings, "CHAT_MODEL_FALLBACKS", "")
    monkeypatch.setattr(gemini_client.settings, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(gemini_client.settings, "GROQ_MODEL", "groq-model")

    async def fake_open_groq_connection(**_kwargs):
        raise gemini_client.UpstreamChatError(429, "rate_limit_exceeded: Rate limit reached")

    monkeypatch.setattr(gemini_client, "_open_groq_connection", fake_open_groq_connection)

    with pytest.raises(gemini_client.UpstreamChatError):
        _collect(prompt="hi", model="primary-model")

    assert _unique_models_tried(models) == ["primary-model"]


def test_establish_budget_is_shared_across_all_candidates(monkeypatch):
    # Regression test for a live latency bug (2026-09-09): each candidate
    # used to get its own full connect timeout, so N slow-but-not-failing
    # candidates multiplied into N times the latency (with Groq added, up to
    # ~2 minutes for one chat turn). Now every candidate shares ONE deadline.
    # Uses real asyncio.sleep (not the instant-patched one _patch_client's
    # other tests use) with tiny budgets, so this test measures genuine
    # elapsed time while still running fast.
    attempted: List[str] = []

    class _HangingModels:
        async def generate_content_stream(self, *, model, contents, config):
            attempted.append(model)
            await asyncio.sleep(10)  # far longer than the shared budget
            raise AssertionError("unreachable -- should be cut off by the deadline")

    class _HangingAio:
        models = _HangingModels()

    class _HangingClient:
        aio = _HangingAio()

    monkeypatch.setattr(gemini_client, "get_client", lambda: _HangingClient())
    monkeypatch.setattr(gemini_client.settings, "CHAT_MODEL_FALLBACKS", "backup-model")
    monkeypatch.setattr(gemini_client.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(gemini_client, "_ESTABLISH_BUDGET_SECONDS", 0.3)
    monkeypatch.setattr(gemini_client, "_MIN_CANDIDATE_TIMEOUT_SECONDS", 0.05)

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        _collect(prompt="hi", model="primary-model")
    elapsed = time.monotonic() - start

    # Both candidates attempted (each cut off by the shared deadline, not
    # given their own full budget), and total wall-clock time stays close to
    # the ONE shared budget instead of multiplying per candidate.
    assert attempted == ["primary-model", "backup-model"]
    assert elapsed < 1.0
