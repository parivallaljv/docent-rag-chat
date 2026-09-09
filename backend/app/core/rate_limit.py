"""Guards against exhausting Gemini's free-tier daily request quota, plus a
retry-with-backoff helper for transient upstream failures (429/503).

The quota counter is a simple in-memory, per-process daily counter. That's
fine for the single small Render instance this portfolio project deploys to,
but it is NOT correct across multiple instances/replicas and does not
survive a process restart without losing count -- swap in a Postgres-backed
(or Redis-backed) counter for that case.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
from datetime import date
from threading import Lock
from typing import Any, Awaitable, Callable, TypeVar

from fastapi import HTTPException, status

from .config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class QuotaExceededError(Exception):
    def __init__(self, day: str, limit: int):
        self.day = day
        self.limit = limit
        super().__init__(f"Daily Gemini request quota of {limit} exhausted for {day}")


class DailyQuotaCounter:
    """Thread-safe in-memory counter of Gemini-bound requests for the current day."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._day = date.today().isoformat()
        self._count = 0

    def _reset_if_new_day_locked(self) -> None:
        today = date.today().isoformat()
        if today != self._day:
            self._day = today
            self._count = 0

    def check_and_increment(self, limit: int) -> int:
        """Raise QuotaExceededError if `limit` has already been reached today,
        otherwise increment and return the new count."""
        with self._lock:
            self._reset_if_new_day_locked()
            if self._count >= limit:
                raise QuotaExceededError(self._day, limit)
            self._count += 1
            return self._count

    def snapshot(self) -> tuple[str, int]:
        with self._lock:
            self._reset_if_new_day_locked()
            return self._day, self._count


_quota_counter = DailyQuotaCounter()


async def enforce_gemini_quota() -> None:
    """FastAPI dependency: raise a clean HTTP 429 *before* calling Gemini once
    today's free-tier request budget has been spent."""
    try:
        _quota_counter.check_and_increment(settings.GEMINI_DAILY_QUOTA)
    except QuotaExceededError as exc:
        logger.warning(str(exc))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "This demo has used up its free daily AI request budget. "
                "Please try again after midnight UTC."
            ),
        ) from exc


def quota_status() -> dict:
    """Snapshot of today's quota usage, handy for a debug/status endpoint."""
    day, count = _quota_counter.snapshot()
    return {"day": day, "used": count, "limit": settings.GEMINI_DAILY_QUOTA}


_RETRYABLE_HINTS = ("429", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "503", "DEADLINE_EXCEEDED")


def is_retryable_error(exc: BaseException) -> bool:
    """Best-effort check for whether an exception raised by an LLM provider
    represents a transient error worth retrying (rate limited / overloaded /
    timed out) as opposed to a permanent failure (bad request, auth error).

    A bare TimeoutError (asyncio.TimeoutError is an alias of it on this
    project's Python version) has no .code/.status_code and an empty message,
    so it's checked explicitly -- otherwise a hung/slow model's timeout would
    fall through both checks below and be treated as non-retryable, skipping
    the fallback chain entirely instead of trying the next configured model.
    """
    if isinstance(exc, TimeoutError):
        return True
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(exc, "status_code", None)
    if isinstance(code, int) and code in (429, 503, 504):
        return True
    return any(hint in str(exc) for hint in _RETRYABLE_HINTS)


def is_quota_exhausted_error(exc: BaseException) -> bool:
    """True specifically for a Gemini free-tier quota-exhaustion error
    (RESOURCE_EXHAUSTED / 429), as opposed to a generic transient failure
    (503/UNAVAILABLE/timeout) or another provider's differently-scoped 429
    (e.g. Groq's per-minute rate limit, used as gemini_client.stream_chat's
    cross-vendor fallback -- that 429 means "wait under a minute", not
    "come back tomorrow", so it must NOT match here). Deliberately keyed off
    the RESOURCE_EXHAUSTED text marker alone rather than a bare numeric 429,
    since a plain status code carries no vendor-specific meaning by itself.
    Confirmed empirically (2026-09-07) that this quota is enforced
    per-model, and retrying the SAME model within a single request is futile
    -- a fresh quota only becomes available the next day. Callers should
    switch to a different model instead (see gemini_client.stream_chat's
    fallback chain) rather than backing off and retrying, and should surface
    a distinct "come back later/tomorrow" message rather than a generic
    "try again in a moment" one."""
    return "RESOURCE_EXHAUSTED" in str(exc)


def compute_backoff_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 30.0) -> float:
    """Exponential backoff with jitter: base_delay * 2^attempt, capped at
    max_delay, plus up to 0.5s of random jitter to avoid thundering-herd
    retries."""
    delay = min(max_delay, base_delay * (2**attempt))
    return delay + random.uniform(0, 0.5)


async def call_with_backoff(
    coro_func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    **kwargs: Any,
) -> T:
    """Await coro_func(*args, **kwargs), retrying with exponential backoff on
    retryable errors. Raises immediately (no retry) for non-retryable errors,
    and re-raises the last error once max_retries is exhausted."""
    attempt = 0
    while True:
        try:
            return await coro_func(*args, **kwargs)
        except Exception as exc:
            if attempt >= max_retries or not is_retryable_error(exc):
                raise
            delay = compute_backoff_delay(attempt, base_delay, max_delay)
            logger.warning(
                "Gemini call failed (attempt %d/%d): %s. Retrying in %.1fs",
                attempt + 1,
                max_retries,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            attempt += 1


def with_backoff(max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 30.0):
    """Decorator form of call_with_backoff for simple one-shot async
    (coroutine) functions, e.g. a batch embedding call.

    Do NOT use this on an async *generator* function (a streaming call): the
    decorator only wraps the initial invocation, and a partially-consumed
    stream can't be safely retried without duplicating already-yielded
    output. See llm.gemini_client.stream_chat, which instead retries only the
    connection-establishment step, manually, via call_with_backoff.
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await call_with_backoff(
                func,
                *args,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                **kwargs,
            )

        return wrapper

    return decorator
