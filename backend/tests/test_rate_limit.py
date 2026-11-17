"""Unit tests for the in-memory daily Gemini quota counter.

Pure logic, no network/credentials needed -- this exists specifically
because the counter's default limit was discovered (via live testing) to
matter a lot in practice: Google's real free-tier cap for chat generation
turned out to be far lower than the ~1500/day generic docs suggested, and
this guard is what stands between that and a raw, unfriendly upstream 429
reaching the user.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.rate_limit import (
    DailyQuotaCounter,
    QuotaExceededError,
    is_quota_exhausted_error,
    is_retryable_error,
)


def test_increments_and_raises_once_limit_reached():
    counter = DailyQuotaCounter()
    for _ in range(3):
        counter.check_and_increment(limit=3)
    with pytest.raises(QuotaExceededError):
        counter.check_and_increment(limit=3)


def test_snapshot_reflects_count_without_incrementing():
    counter = DailyQuotaCounter()
    counter.check_and_increment(limit=10)
    counter.check_and_increment(limit=10)
    _, count = counter.snapshot()
    assert count == 2
    # snapshot() must not itself count as a request.
    _, count_again = counter.snapshot()
    assert count_again == 2


def test_resets_on_a_new_day(monkeypatch):
    counter = DailyQuotaCounter()
    counter.check_and_increment(limit=1)
    with pytest.raises(QuotaExceededError):
        counter.check_and_increment(limit=1)

    tomorrow = date.fromordinal(date.today().toordinal() + 1)

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return tomorrow

    monkeypatch.setattr("app.core.rate_limit.date", _FixedDate)

    # Should succeed again: a new day resets the counter to zero.
    counter.check_and_increment(limit=1)
    day, count = counter.snapshot()
    assert day == tomorrow.isoformat()
    assert count == 1


def test_quota_exceeded_error_message_includes_limit_and_day():
    exc = QuotaExceededError(day="2026-09-07", limit=18)
    assert "18" in str(exc)
    assert "2026-09-07" in str(exc)


class _FakeGeminiClientError(Exception):
    """Mimics google.genai.errors.ClientError's shape closely enough to
    exercise is_quota_exhausted_error's introspection without needing the
    real SDK installed/importable in a pure-logic test."""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


def test_is_quota_exhausted_error_detects_real_429_shape():
    # The exact shape observed live (2026-09-07) from a genuinely exhausted
    # gemini-3.8-flash: code=429 plus a RESOURCE_EXHAUSTED status string.
    exc = _FakeGeminiClientError(
        429,
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
        "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
        "limit: 20, model: gemini-3.8-flash",
    )
    assert is_quota_exhausted_error(exc) is True


def test_is_quota_exhausted_error_detects_by_message_alone():
    # Even without a .code attribute, the RESOURCE_EXHAUSTED substring alone
    # should be enough (defensive against SDK exception shape changes).
    assert is_quota_exhausted_error(Exception("... RESOURCE_EXHAUSTED ...")) is True


def test_is_quota_exhausted_error_false_for_unrelated_error():
    assert is_quota_exhausted_error(ValueError("bad request: missing field")) is False


def test_is_quota_exhausted_error_false_for_transient_503():
    exc = _FakeGeminiClientError(503, "503 UNAVAILABLE. The model is overloaded.")
    assert is_quota_exhausted_error(exc) is False


def test_is_quota_exhausted_error_false_for_a_differently_scoped_429():
    # A 429 alone isn't enough -- e.g. Groq's per-minute rate limit (used as
    # gemini_client.stream_chat's cross-vendor fallback) is also a bare 429
    # but resets in under a minute, not "tomorrow". Classifying it as quota
    # exhaustion would show the user the wrong ("come back tomorrow") message.
    exc = _FakeGeminiClientError(429, "429 rate_limit_exceeded: Rate limit reached for requests")
    assert is_quota_exhausted_error(exc) is False


def test_is_retryable_error_true_for_bare_timeout_error():
    # asyncio.TimeoutError (raised by asyncio.wait_for on a hung/slow model)
    # is an alias of the builtin TimeoutError and carries no .code/.status_code
    # and an empty message -- it must still be recognized as retryable, or a
    # hung model skips the fallback chain entirely instead of trying the next
    # configured model (the exact bug behind a live "took too long to
    # respond" report).
    assert is_retryable_error(TimeoutError()) is True


def test_is_retryable_error_true_for_httpx_style_status_code_attr():
    exc = _FakeGeminiClientError(503, "503 Service Unavailable")
    # Simulate an exception exposing .status_code instead of .code (as
    # gemini_client.UpstreamChatError does for Groq failures).
    del exc.code
    exc.status_code = 503
    assert is_retryable_error(exc) is True
