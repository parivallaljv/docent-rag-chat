"""Retrieval-augmented, citation-grounded chat over the user's documents,
served over a persistent WebSocket connection at /chat/ws.

Message protocol (JSON frames both ways), all server frames after the auth
handshake carry the `turn_id` the client supplied for that chat turn:

  Client -> server:
    {"type": "auth", "token": "<supabase jwt>"}       required first message
    {"type": "message", "turn_id": "...", "message": "...",
     "document_id": "...|null", "history": [...]}     one per chat turn
    {"type": "stop", "turn_id": "..."}                 cancel a running turn

  Server -> client:
    {"type": "auth_ok"} | {"type": "auth_error", "message": "..."}
    {"type": "token", "turn_id": ..., "content": "..."}
    {"type": "citations", "turn_id": ..., "citations": [...]}
    {"type": "no_context", "turn_id": ..., "message": "..."}
    {"type": "error", "turn_id": ..., "message": "..."}
    {"type": "quota_exceeded", "turn_id": ..., "message": "..."}
    {"type": "stopped", "turn_id": ...}
    {"type": "turn_end", "turn_id": ...}               always last for a turn

Why a first-message auth handshake rather than a `?token=` query param:
browsers' native WebSocket API can't set custom headers on the handshake
request, and a query-string token would land in Render's access logs and
browser history -- a real credential-exposure risk for a bearer JWT, for the
cost of one extra message.

Why WebSocket instead of the SSE this replaced: NOT because SSE couldn't do
the job -- the frontend already calls this backend directly (never proxied
through Next.js), so Vercel's serverless timeout was never a factor for
either transport. This is a persistent-connection preference (no
reconnect-per-turn, room for future bidirectional features), not a bug fix.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .. import memory as memory_mod
from ..agent.critic import critique_answer
from ..agent.loop import GeminiToolPlanner, run_tool_agent
from ..agent.tools import build_tools
from ..agent.workflow import plan_and_execute
from ..core.auth import TokenVerificationError, verify_token_claims
from ..core.background import spawn
from ..core.config import settings
from ..core.logging import new_request_id, request_id_var
from ..core.metrics import RATE_LIMITED, Trace
from ..core.rate_limit import (
    check_user_rate_limit,
    enforce_gemini_quota,
    is_quota_exhausted_error,
)
from ..core.semantic_cache import semantic_cache
from ..core.tracing import export_trace
from ..db import queries
from ..db.client import get_pool
from ..db.models import ChatMessage, ChatRequest
from ..ingestion.chunker import approx_token_count
from ..ingestion.embedder import embed_query
from ..llm.gemini_client import stream_chat
from ..llm.routing import route_model
from ..retrieval import agent as agent_mod
from ..retrieval import prompt as prompt_mod
from ..retrieval import search as search_mod
from ..retrieval.citations import reconcile_citations, select_cited
from ..retrieval.rerank import mmr_rerank

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_AUTH_TIMEOUT_SECONDS = 10.0


async def _run_chat_turn_inner(
    user_id: str, payload: ChatRequest, trace: Trace
) -> AsyncIterator[tuple[str, dict]]:
    """Transport-agnostic retrieval + generation pipeline for one chat turn.
    Yields (event_type, data) pairs; the WebSocket route below is the only
    caller and handles all framing/turn_id/transport concerns itself."""
    pool = get_pool()

    cache_vec: list[float] | None = None
    scope = str(payload.document_id) if payload.document_id else None
    if settings.SEMANTIC_CACHE and not payload.history:
        try:
            cache_vec = await embed_query(payload.message)
            hit = semantic_cache.get(user_id, scope, cache_vec)
        except Exception:  # noqa: BLE001 -- the cache must never break a turn
            cache_vec, hit = None, None
        if hit is not None:
            trace.attrs["cache_hit"] = True
            for i in range(0, len(hit.answer), 48):
                yield ("token", {"content": hit.answer[i : i + 48]})
            yield ("citations", {"citations": hit.citations})
            return

    try:
        _t = time.perf_counter()

        async def search_one(query: str, is_original: bool) -> list:
            return await search_mod.search(
                pool,
                user_id=user_id,
                query_text=query,
                document_id=payload.document_id,
                top_n=settings.RETRIEVAL_TOP_N,
                # Only the user's own wording needs history context; planner
                # queries are already self-contained.
                history=payload.history if is_original else None,
            )

        tool_notes: list[str] = []
        user_memory: str | None = None
        if settings.USER_MEMORY:
            try:
                user_memory = await queries.get_memory(pool, user_id=user_id)
            except Exception:  # noqa: BLE001 -- migration 008 not applied yet: just skip
                logger.warning("user_memory unavailable; apply migration 008", exc_info=True)
        agent_chunks_lack_embeddings = False
        if settings.AGENTIC_SEARCH and settings.AGENT_MODE == "tools":
            first = await search_one(payload.message, True)

            async def scoped(query: str, doc_id):
                return await search_mod.search(
                    pool,
                    user_id=user_id,
                    query_text=query,
                    document_id=doc_id or payload.document_id,
                    top_n=settings.RETRIEVAL_TOP_N,
                )

            tools = build_tools(pool, user_id, scoped)
            res = await run_tool_agent(
                first,
                tools,
                GeminiToolPlanner(payload.message, payload.history, tools),
                max_steps=settings.AGENT_MAX_STEPS,
                max_calls=settings.AGENT_MAX_TOOL_CALLS,
                top_n=settings.RETRIEVAL_TOP_N,
                rrf_k=settings.RRF_K,
                step_timeout=settings.AGENT_STEP_TIMEOUT,
            )
            candidates, tool_notes = res.candidates, res.notes
            agent_chunks_lack_embeddings = True
            trace.attrs["agent_calls"] = res.calls
            trace.attrs["agent_steps"] = res.steps
            if res.error:
                trace.attrs["agent_error"] = res.error
        elif settings.AGENTIC_SEARCH and settings.AGENT_MODE == "plan":
            agent = await plan_and_execute(
                payload.message,
                search_one,
                max_sub=settings.AGENT_MAX_QUERIES - 1,
                top_n=settings.RETRIEVAL_TOP_N,
                rrf_k=settings.RRF_K,
            )
            candidates = agent.candidates
            trace.attrs["agent_queries"] = agent.queries
            if agent.error:
                trace.attrs["agent_error"] = agent.error
        elif settings.AGENTIC_SEARCH:
            agent = await agent_mod.agentic_retrieve(search_one, payload.message, payload.history)
            candidates = agent.candidates
            trace.attrs["agent_queries"] = agent.queries
            trace.attrs["agent_rounds"] = agent.rounds
            if agent.error:
                trace.attrs["agent_error"] = agent.error
        else:
            candidates = await search_one(payload.message, True)
        trace.mark("retrieve", time.perf_counter() - _t)
        _t = time.perf_counter()

        if settings.MMR_LAMBDA >= 1.0 or agent_chunks_lack_embeddings:
            # Pure relevance: keep search()'s order (cosine, or RRF when hybrid).
            ranked = candidates[: settings.RERANK_TOP_K]
        else:
            ranked = mmr_rerank(
                candidates,
                embedding_fn=lambda c: c.embedding,
                relevance_fn=lambda c: c.similarity,
                top_k=settings.RERANK_TOP_K,
                lambda_mult=settings.MMR_LAMBDA,
            )

        history = [prompt_mod.ChatTurn(role=h.role, content=h.content) for h in payload.history]
        assembled = prompt_mod.build_prompt(
            query=payload.message,
            ranked_candidates=ranked,
            history=history,
            similarity_threshold=settings.SIMILARITY_THRESHOLD,
            max_prompt_tokens=settings.MAX_PROMPT_TOKENS,
            history_turns=settings.HISTORY_TURNS,
            tool_notes=tool_notes,
            user_memory=user_memory,
        )
        trace.mark("rank_prompt", time.perf_counter() - _t)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Retrieval/prompt-assembly failures (a DB hiccup, a bad embedding
        # response) aren't wrapped in the same try/except as generation
        # below -- unlike a mid-stream Gemini failure, nothing has been sent
        # to the client yet, so this still needs its own terminal event
        # rather than silently propagating out of an unawaited task (see
        # chat_ws's run_turn/_on_task_done).
        logger.exception("Retrieval/prompt assembly failed")
        yield ("error", {"message": "Something went wrong preparing a response. Please try again."})
        return

    if assembled == prompt_mod.NO_CONTEXT_SENTINEL:
        yield ("no_context", {"message": prompt_mod.NO_CONTEXT_MESSAGE})
        return

    trace.attrs["prompt_tokens_approx"] = approx_token_count(assembled.prompt)
    trace.attrs["chunks"] = len(assembled.citations)
    chat_model = route_model(payload.message)
    trace.attrs["model"] = chat_model
    answer_parts: list[str] = []
    _gen = time.perf_counter()
    try:
        async for token in stream_chat(
            prompt=assembled.prompt,
            system_instruction=assembled.system_instruction,
            model=chat_model,
        ):
            if not answer_parts:
                trace.mark("ttft", time.perf_counter() - _gen)
            answer_parts.append(token)
            yield ("token", {"content": token})
    except TimeoutError:
        logger.exception("Gemini generation timed out mid-stream")
        yield ("error", {"message": "The AI took too long to respond. Please try again."})
        return
    except Exception as exc:
        # stream_chat() already falls back across settings.CHAT_MODEL_FALLBACKS
        # when a model's daily quota is exhausted -- reaching here with a
        # quota-exhaustion error means EVERY configured model was exhausted,
        # not just the primary one. That's a distinct, accurate story from a
        # generic transient failure ("come back tomorrow" vs. "try again in
        # a moment") and already has its own event type the frontend knows
        # how to render (lib/ws.ts / ChatWindow.tsx).
        if is_quota_exhausted_error(exc):
            logger.warning("Gemini daily quota exhausted for every configured model: %s", exc)
            yield (
                "quota_exceeded",
                {
                    "message": (
                        "This demo has used its free daily AI budget for today's "
                        "available models. Please try again tomorrow."
                    )
                },
            )
            return
        logger.exception("Gemini generation failed mid-stream")
        yield (
            "error",
            {"message": "The AI is temporarily overloaded. Please try again in a moment."},
        )
        return

    trace.mark("generate", time.perf_counter() - _gen)
    trace.attrs["completion_tokens_approx"] = approx_token_count("".join(answer_parts))

    # Cite only the excerpts the model actually referenced; surface bad numbers.
    valid, invalid = reconcile_citations(
        "".join(answer_parts), [c.marker for c in assembled.citations]
    )
    if invalid:
        logger.warning("Model cited non-existent excerpt numbers: %s", invalid)
    citations = [
        {
            # Field names match the frontend's ChatCitation type exactly
            # (lib/types.ts) -- id/page/snippet, not chunk_id/page_number/content.
            "id": str(c.chunk_id),
            "marker": c.marker,
            "document_id": str(c.document_id),
            "filename": c.filename,
            "page": c.page_number,
            "snippet": c.content[:280].strip() + ("…" if len(c.content) > 280 else ""),
            "similarity": round(c.similarity, 4),
        }
        for c in select_cited(assembled.citations, valid)
    ]
    if settings.CRITIC_ENABLED and valid:
        claims = await critique_answer(
            "".join(answer_parts), select_cited(assembled.citations, valid)
        )
        if claims is not None:
            trace.attrs["critic_unsupported"] = sum(1 for c in claims if not c["supported"])
            yield ("critique", {"claims": claims})
    payload_out: dict = {"citations": citations}
    if not valid:
        payload_out["warning"] = "no_valid_citations"
    if invalid:
        payload_out["invalid_markers"] = invalid
    if prompt_mod.leaks_system_prompt("".join(answer_parts)):
        logger.warning("possible system prompt leak in answer")
        payload_out["warning"] = "possible_prompt_leak"
    if cache_vec is not None and valid and not tool_notes:
        semantic_cache.put(user_id, scope, cache_vec, "".join(answer_parts), citations)
    yield ("citations", payload_out)


_TERMINAL_OUTCOMES = {
    "citations": "ok",
    "no_context": "no_context",
    "error": "error",
    "quota_exceeded": "quota_exceeded",
}


async def _persist(user_id: str, chat_id: Any, role: str, content: str, citations=None):
    """Best-effort save: a DB hiccup must never break a live answer."""
    try:
        return await queries.add_message(
            get_pool(),
            user_id=user_id,
            chat_id=chat_id,
            role=role,
            content=content,
            citations=citations,
        )
    except Exception:
        logger.exception("Failed to persist chat message")
        return None


async def _run_chat_turn(user_id: str, payload: ChatRequest) -> AsyncIterator[tuple[str, dict]]:
    """Instrumented wrapper: correlation id, server-side history + persistence
    when a chat_id is given, stage timings, one `chat_turn` log line + metrics
    per turn, whatever way the turn ends."""
    request_id_var.set(new_request_id())
    trace = Trace(user=str(user_id)[:8], history_turns=len(payload.history))
    outcome = "cancelled"
    answer: list[str] = []
    try:
        if payload.chat_id is not None:
            # Server is the source of truth: client history is ignored, so it
            # can't be forged, and ownership is checked before anything is read.
            pool = get_pool()
            if await queries.get_chat(pool, user_id=user_id, chat_id=payload.chat_id) is None:
                outcome = "error"
                yield ("error", {"message": "That conversation no longer exists."})
                return
            rows = await queries.recent_messages(
                pool, user_id=user_id, chat_id=payload.chat_id, limit=settings.HISTORY_TURNS * 2
            )
            history_msgs = [ChatMessage(role=r["role"], content=r["content"]) for r in rows]
            if settings.CHAT_SUMMARY:
                try:
                    summary, _ = await queries.get_chat_summary(
                        pool, user_id=user_id, chat_id=payload.chat_id
                    )
                except Exception:  # noqa: BLE001 -- migration 008 not applied yet
                    summary = None
                if summary:
                    history_msgs.insert(
                        0,
                        ChatMessage(
                            role="assistant",
                            content=f"[Summary of the earlier conversation] {summary}",
                        ),
                    )
            payload = payload.model_copy(update={"history": history_msgs})
            trace.attrs["history_turns"] = len(payload.history)
            await _persist(user_id, payload.chat_id, "user", payload.message)

        async for event, data in _run_chat_turn_inner(user_id, payload, trace):
            outcome = _TERMINAL_OUTCOMES.get(event, outcome)
            if event == "token":
                answer.append(data["content"])
            elif payload.chat_id is not None and event == "citations":
                mid = await _persist(
                    user_id, payload.chat_id, "assistant", "".join(answer), data["citations"]
                )
                if mid is not None:
                    data = {**data, "message_id": str(mid)}
                if settings.CHAT_SUMMARY:
                    memory_mod.schedule_summary(get_pool(), user_id, payload.chat_id)
            elif payload.chat_id is not None and event == "no_context":
                await _persist(user_id, payload.chat_id, "assistant", data["message"], [])
            yield event, data
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        trace.finish(outcome)
        _after_turn(user_id, trace, outcome, payload.message, "".join(answer))


def _after_turn(user_id: str, trace, outcome: str, message: str, answer: str) -> None:
    """Optional tracing export + usage accounting. Never raises into the turn."""
    try:
        export_trace(trace, outcome, prompt_mod.PROMPT_VERSION, message, answer)
        p = int(trace.attrs.get("prompt_tokens_approx", 0))
        c = int(trace.attrs.get("completion_tokens_approx", 0))
        if p or c:
            cost = (
                p * settings.COST_PER_1M_INPUT_USD + c * settings.COST_PER_1M_OUTPUT_USD
            ) / 1_000_000
            spawn(
                queries.add_usage(
                    get_pool(),
                    user_id=user_id,
                    kind="chat",
                    model=trace.attrs.get("model"),
                    prompt_tokens=p,
                    completion_tokens=c,
                    cost_usd=cost,
                ),
                "usage accounting",
            )
    except Exception:  # noqa: BLE001
        logger.warning("after-turn bookkeeping failed", exc_info=True)


def _parse_chat_request(msg: dict) -> ChatRequest:
    history_raw = msg.get("history") or []
    return ChatRequest(
        message=msg.get("message", ""),
        document_id=msg.get("document_id"),
        chat_id=msg.get("chat_id"),
        history=[ChatMessage(**h) for h in history_raw],
    )


@router.websocket("/chat/ws")
async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    # Origin isn't enforced by CORSMiddleware for WebSocket handshakes (that
    # middleware only applies to regular HTTP requests), so it's checked
    # manually here. This is defense-in-depth, not the primary access-control
    # boundary -- that's the auth handshake below -- so a browser dev tool
    # with no Origin header at all is allowed through rather than rejected.
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.allowed_origins_list:
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    try:
        auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=_AUTH_TIMEOUT_SECONDS)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        await websocket.close(code=1008, reason="Expected an auth message")
        return

    if (
        not isinstance(auth_msg, dict)
        or auth_msg.get("type") != "auth"
        or not auth_msg.get("token")
    ):
        await websocket.close(code=1008, reason="Expected {type: 'auth', token: ...} first")
        return

    try:
        claims = verify_token_claims(auth_msg["token"])
        user_id = claims["sub"]
        token_exp = claims.get("exp")
    except TokenVerificationError as exc:
        await websocket.send_json({"type": "auth_error", "message": str(exc)})
        await websocket.close(code=1008)
        return

    await websocket.send_json({"type": "auth_ok"})

    current_task: asyncio.Task | None = None
    expiry_watch: asyncio.Task | None = None
    # Every websocket.send_json() call -- both the main loop's and
    # run_turn's -- goes through this lock. Turns run as a background task
    # (see the "don't inline-await" note below) so the main loop keeps
    # reading frames (to notice a "stop") while a turn is still sending its
    # own frames; without serializing writes, those two concurrent senders
    # could interleave bytes on the same socket.
    send_lock = asyncio.Lock()

    async def send(frame: dict) -> None:
        async with send_lock:
            await websocket.send_json(frame)

    async def run_turn(turn_id: Any, payload: ChatRequest) -> None:
        try:
            async for event_type, data in _run_chat_turn(user_id, payload):
                await send({"type": event_type, "turn_id": turn_id, **data})
        except asyncio.CancelledError:
            await send({"type": "stopped", "turn_id": turn_id})
            raise
        finally:
            await send({"type": "turn_end", "turn_id": turn_id})

    def _on_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            # _run_chat_turn already turns every failure it knows about into
            # an "error"/"no_context" frame; reaching here means something
            # unexpected slipped through (a bug, not a modeled failure mode).
            # Since this task is never awaited by the main loop anymore, an
            # exception here would otherwise vanish as a silent
            # "Task exception was never retrieved" log line.
            logger.error("Unhandled exception in chat turn", exc_info=exc)

    async def _close_at_expiry() -> None:
        # The JWT is only checked at connect, so a socket could outlive it. Close
        # (code 1008) once it expires -- after any in-flight turn finishes -- and
        # the client reconnects with a freshly refreshed token.
        await asyncio.sleep(max(0.0, float(token_exp) - time.time()))
        while current_task is not None and not current_task.done():
            await asyncio.sleep(1)
        with contextlib.suppress(Exception):
            await websocket.close(code=1008, reason="Token expired")

    if token_exp is not None:
        expiry_watch = asyncio.create_task(_close_at_expiry())

    try:
        while True:
            try:
                msg = await websocket.receive_json()
            except ValueError:
                await send({"type": "error", "message": "Malformed JSON message."})
                continue

            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await send({"type": "pong"})
                continue

            if msg_type == "stop":
                if current_task is not None and not current_task.done():
                    current_task.cancel()
                continue

            if msg_type != "message":
                continue

            turn_id = msg.get("turn_id")

            if current_task is not None and not current_task.done():
                # One turn at a time per connection -- the frontend already
                # disables sending while a response is streaming, so this is
                # a defensive guard against a misbehaving/multi-tab client,
                # not part of the normal happy path. Reachable because the
                # loop below no longer blocks on the turn task, so it can
                # actually observe an overlapping "message" frame.
                await send(
                    {
                        "type": "error",
                        "turn_id": turn_id,
                        "message": "A response is already in progress on this connection.",
                    }
                )
                continue

            try:
                payload = _parse_chat_request(msg)
            except ValidationError as exc:
                await send(
                    {"type": "error", "turn_id": turn_id, "message": f"Invalid message: {exc}"}
                )
                continue

            # Quota can no longer be enforced as a one-shot dependency before
            # the response is constructed (there's no per-turn "response" to
            # gate the way an HTTP request has) -- it's re-checked here, per
            # inbound message, and unlike the old SSE 429 (which ended the
            # whole HTTP request), the connection stays open afterwards.
            if not check_user_rate_limit(user_id):
                RATE_LIMITED.labels(kind="user").inc()
                await send(
                    {
                        "type": "quota_exceeded",
                        "turn_id": turn_id,
                        "message": "You're sending messages too quickly. Please wait a moment.",
                    }
                )
                await send({"type": "turn_end", "turn_id": turn_id})
                continue
            try:
                await enforce_gemini_quota()
            except HTTPException as exc:
                await send({"type": "quota_exceeded", "turn_id": turn_id, "message": exc.detail})
                await send({"type": "turn_end", "turn_id": turn_id})
                continue

            # Deliberately NOT awaited inline: this task must keep running
            # concurrently with the loop below going back to
            # websocket.receive_json(), or a "stop" frame sent while this
            # turn is in flight would simply never be read until the turn
            # finishes on its own -- too late to cancel anything.
            current_task = asyncio.create_task(run_turn(turn_id, payload))
            current_task.add_done_callback(_on_task_done)
    except WebSocketDisconnect:
        pass
    finally:
        if expiry_watch is not None:
            expiry_watch.cancel()
        if current_task is not None and not current_task.done():
            current_task.cancel()
