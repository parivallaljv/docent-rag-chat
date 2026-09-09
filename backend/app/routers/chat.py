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
import logging
from typing import Any, AsyncIterator, Optional, Tuple

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..core.auth import TokenVerificationError, verify_token
from ..core.config import settings
from ..core.rate_limit import enforce_gemini_quota, is_quota_exhausted_error
from ..db.client import get_pool
from ..db.models import ChatMessage, ChatRequest
from ..llm.gemini_client import stream_chat
from ..retrieval import prompt as prompt_mod
from ..retrieval import search as search_mod
from ..retrieval.rerank import mmr_rerank

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_AUTH_TIMEOUT_SECONDS = 10.0


async def _run_chat_turn(user_id: str, payload: ChatRequest) -> AsyncIterator[Tuple[str, dict]]:
    """Transport-agnostic retrieval + generation pipeline for one chat turn.
    Yields (event_type, data) pairs; the WebSocket route below is the only
    caller and handles all framing/turn_id/transport concerns itself."""
    pool = get_pool()

    try:
        candidates = await search_mod.search(
            pool,
            user_id=user_id,
            query_text=payload.message,
            document_id=payload.document_id,
            top_n=settings.RETRIEVAL_TOP_N,
            history=payload.history,
        )

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
        )
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

    try:
        async for token in stream_chat(
            prompt=assembled.prompt,
            system_instruction=assembled.system_instruction,
            model=settings.CHAT_MODEL,
        ):
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
        yield ("error", {"message": "The AI is temporarily overloaded. Please try again in a moment."})
        return

    citations = [
        {
            # Field names match the frontend's ChatCitation type exactly
            # (lib/types.ts) -- id/page/snippet, not chunk_id/page_number/content.
            "id": str(c.chunk_id),
            "document_id": str(c.document_id),
            "filename": c.filename,
            "page": c.page_number,
            "snippet": c.content[:280].strip() + ("…" if len(c.content) > 280 else ""),
            "similarity": round(c.similarity, 4),
        }
        for c in assembled.citations
    ]
    yield ("citations", {"citations": citations})


def _parse_chat_request(msg: dict) -> ChatRequest:
    history_raw = msg.get("history") or []
    return ChatRequest(
        message=msg.get("message", ""),
        document_id=msg.get("document_id"),
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
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        await websocket.close(code=1008, reason="Expected an auth message")
        return

    if not isinstance(auth_msg, dict) or auth_msg.get("type") != "auth" or not auth_msg.get("token"):
        await websocket.close(code=1008, reason="Expected {type: 'auth', token: ...} first")
        return

    try:
        user_id = verify_token(auth_msg["token"])
    except TokenVerificationError as exc:
        await websocket.send_json({"type": "auth_error", "message": str(exc)})
        await websocket.close(code=1008)
        return

    await websocket.send_json({"type": "auth_ok"})

    current_task: Optional[asyncio.Task] = None
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
                await send({"type": "error", "turn_id": turn_id, "message": f"Invalid message: {exc}"})
                continue

            # Quota can no longer be enforced as a one-shot dependency before
            # the response is constructed (there's no per-turn "response" to
            # gate the way an HTTP request has) -- it's re-checked here, per
            # inbound message, and unlike the old SSE 429 (which ended the
            # whole HTTP request), the connection stays open afterwards.
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
        if current_task is not None and not current_task.done():
            current_task.cancel()
