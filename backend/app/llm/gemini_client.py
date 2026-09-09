"""Thin wrapper around the google-genai SDK for chat generation and
embeddings. Both entry points go through core.rate_limit's backoff helper so
transient upstream 429/503 errors from Gemini are retried instead of failing
the request outright.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, List, Optional, Tuple

import httpx
from google import genai
from google.genai import types

from ..core.config import settings
from ..core.rate_limit import (
    call_with_backoff,
    is_quota_exhausted_error,
    is_retryable_error,
    with_backoff,
)

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None

# Bounds on a single stream_chat() call, so a hung upstream connection or a
# stalled response can't leave a request (and the client's SSE connection)
# hanging indefinitely with no error and no timeout of any kind.
#
# _CONNECT_TIMEOUT_SECONDS is a low-level, per-HTTP-call socket timeout (used
# directly by httpx.AsyncClient for the Groq path). It is NOT how long the
# candidate loop below can spend establishing a stream -- that's bounded
# separately by _ESTABLISH_BUDGET_SECONDS, shared across every candidate, so
# that trying up to 4 candidates (3 Gemini models + Groq) can't multiply into
# minutes of latency the way one fixed timeout PER candidate would.
_CONNECT_TIMEOUT_SECONDS = 20.0
_STALL_TIMEOUT_SECONDS = 20.0
_ESTABLISH_BUDGET_SECONDS = 25.0
_MIN_CANDIDATE_TIMEOUT_SECONDS = 3.0

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class UpstreamChatError(Exception):
    """A non-2xx response from an OpenAI-compatible chat provider (Groq).
    Carries `.status_code` so core.rate_limit's is_retryable_error /
    is_quota_exhausted_error classify Groq failures the same way they
    already classify Gemini SDK errors, with no provider-specific branching
    needed in rate_limit.py itself."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


async def _iter_groq_sse(response: httpx.Response) -> AsyncIterator[str]:
    """Parse an OpenAI-style chat-completions SSE stream into plain text
    deltas, ignoring content-less events (e.g. the role-only opening delta)."""
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        if payload == "[DONE]":
            break
        chunk = json.loads(payload)
        delta = chunk["choices"][0].get("delta", {})
        text = delta.get("content")
        if text:
            yield text


async def _open_groq_connection(
    model: str,
    prompt: str,
    system_instruction: Optional[str],
    temperature: float,
) -> AsyncIterator[str]:
    """Open a Groq chat-completions stream and return an async iterator of
    plain text deltas. Raises UpstreamChatError immediately on a non-2xx
    response -- httpx.AsyncClient.send(..., stream=True) already waits for
    the response headers/status before returning, so (unlike the Gemini SDK
    below) no "peek the first chunk to trigger the real request" trick is
    needed to surface a bad status this early."""
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    client = httpx.AsyncClient(timeout=_CONNECT_TIMEOUT_SECONDS)
    request = client.build_request(
        "POST",
        _GROQ_CHAT_URL,
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        },
    )
    response = await client.send(request, stream=True)
    if response.status_code >= 400:
        body = await response.aread()
        await response.aclose()
        await client.aclose()
        raise UpstreamChatError(response.status_code, body.decode(errors="replace"))

    async def _generator() -> AsyncIterator[str]:
        try:
            async for text in _iter_groq_sse(response):
                yield text
        finally:
            await response.aclose()
            await client.aclose()

    return _generator()


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


@with_backoff()
async def embed_texts(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    """Embed a batch of texts. Returns the *native*-dimensional (3072-d)
    vectors as-is; truncation to 768-d + renormalization happens in
    ingestion.embedder, which is the pure-math layer that's unit-testable
    without a live API key."""
    client = get_client()
    result = await client.aio.models.embed_content(
        model=model or settings.EMBEDDING_MODEL,
        contents=texts,
    )
    return [list(embedding.values) for embedding in result.embeddings]


async def stream_chat(
    prompt: str,
    system_instruction: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    """Stream a chat/generation response as incremental text deltas.

    Backoff/retry is only applied to *establishing* the stream (the initial
    request); once tokens have started arriving we can't safely retry
    without duplicating output already sent to the client, so a mid-stream
    error simply propagates to the caller (routers.chat turns it into a
    terminal SSE `error` event).

    Establishing the stream also falls back through
    settings.CHAT_MODEL_FALLBACKS if the primary model's daily quota is
    exhausted (confirmed empirically: Gemini enforces this per-model, not
    per-project, so a sibling model often still has budget left even when
    the primary one doesn't). A quota-exhausted model is not worth backing
    off and retrying -- a fresh quota only arrives the next day -- and
    neither is a merely transient error (503/timeout) at establishment time
    -- both are skipped immediately in favor of the next candidate (see the
    shared deadline below for why no same-candidate retry happens here).

    As a last resort, after every configured Gemini model has failed, this
    falls back to Groq (a different vendor entirely, see settings.GROQ_*) if
    GROQ_API_KEY is configured -- cycling Gemini models alone can't recover
    from a Gemini-wide slowdown, since they all share one vendor's capacity.
    Groq is skipped silently when no key is set (existing behavior,
    unchanged).

    Establishing a stream (across all candidates combined) is bounded by one
    shared _ESTABLISH_BUDGET_SECONDS deadline rather than a fixed timeout PER
    candidate -- with up to 4 candidates now in play, a flat per-candidate
    timeout could multiply into minutes of latency for a single slow-but-not-
    fast-failing model. Each candidate gets whatever time remains until that
    shared deadline (floored at _MIN_CANDIDATE_TIMEOUT_SECONDS so the last
    candidate always gets a fair shot), and no same-candidate retry is
    attempted here (unlike before) -- with several other candidates already
    queued, moving on immediately is more useful than re-trying one that's
    already struggling.
    """
    client = get_client()
    config = types.GenerateContentConfig(
        temperature=temperature,
        system_instruction=system_instruction,
    )

    candidates: List[Tuple[str, str]] = [("gemini", model or settings.CHAT_MODEL)]
    candidates += [("gemini", m) for m in settings.chat_model_fallbacks_list]
    if settings.GROQ_API_KEY:
        candidates.append(("groq", settings.GROQ_MODEL))

    stream_iter = None
    first_chunk = None
    last_exc: Optional[Exception] = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _ESTABLISH_BUDGET_SECONDS

    def _time_left() -> float:
        return max(deadline - loop.time(), _MIN_CANDIDATE_TIMEOUT_SECONDS)

    for provider, candidate_model in candidates:
        try:
            if provider == "gemini":
                response_stream = await asyncio.wait_for(
                    call_with_backoff(
                        client.aio.models.generate_content_stream,
                        model=candidate_model,
                        contents=prompt,
                        config=config,
                        max_retries=0,
                    ),
                    timeout=_time_left(),
                )
            else:
                response_stream = await asyncio.wait_for(
                    call_with_backoff(
                        _open_groq_connection,
                        model=candidate_model,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=temperature,
                        max_retries=0,
                    ),
                    timeout=_time_left(),
                )
            stream_iter = response_stream.__aiter__()
            # Critical: generate_content_stream() above does NOT actually
            # make the HTTP request -- confirmed empirically -- it just
            # constructs a lazy async generator. The request (and thus any
            # quota-exhaustion error) only fires on the first __anext__(),
            # so that has to happen inside THIS per-candidate try/except too,
            # or a failing model would raise past the fallback loop entirely
            # (which is exactly what happened before this fix: every
            # request landed on the primary model with no fallback ever
            # attempted). Groq's connection step already raises eagerly (see
            # _open_groq_connection), so this is a no-op first pull for it.
            first_chunk = await asyncio.wait_for(stream_iter.__anext__(), timeout=_time_left())
            break
        except StopAsyncIteration:
            first_chunk = None
            break
        except Exception as exc:  # noqa: BLE001 - classified below, not swallowed
            last_exc = exc
            stream_iter = None
            if (provider, candidate_model) == candidates[-1]:
                raise
            if is_quota_exhausted_error(exc):
                logger.warning(
                    "Model %s exhausted its daily quota, falling back to next model", candidate_model
                )
                continue
            if is_retryable_error(exc):
                # A transient overload/timeout that didn't clear after
                # call_with_backoff's quick same-model retries -- rather than
                # surfacing "temporarily overloaded" to the user, try the
                # next configured model/provider. It's a different
                # deployment/capacity pool, so it's often healthy even when
                # the current one isn't.
                logger.warning(
                    "%s model %s failed with a transient error, falling back to next candidate: %s",
                    provider,
                    candidate_model,
                    exc,
                )
                continue
            raise

    if stream_iter is None:
        raise last_exc  # pragma: no cover - unreachable, loop always breaks or raises

    if first_chunk is not None:
        text = first_chunk if isinstance(first_chunk, str) else getattr(first_chunk, "text", None)
        if text:
            yield text

    while True:
        try:
            chunk = await asyncio.wait_for(stream_iter.__anext__(), timeout=_STALL_TIMEOUT_SECONDS)
        except StopAsyncIteration:
            break
        text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
        if text:
            yield text
