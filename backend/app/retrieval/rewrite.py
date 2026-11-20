"""Optional LLM query rewriting: turns a context-dependent follow-up
("what year was that?") into a standalone search query."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from ..core.config import settings
from ..llm import gemini_client

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 8.0
_MAX_TURNS = 4

_SYSTEM = (
    "Rewrite the user's last message as a single standalone search query, "
    "resolving pronouns and references using the conversation. Output ONLY the "
    "query text. If it is already standalone, repeat it unchanged."
)


def _format(history: Sequence[Any], message: str) -> str:
    lines = [f"{t.role}: {t.content}" for t in list(history)[-_MAX_TURNS:] if t.content]
    return "Conversation:\n" + "\n".join(lines) + f"\n\nLast message: {message}\n\nQuery:"


async def rewrite_query(message: str, history: Sequence[Any]) -> str | None:
    """Return the rewritten query, or None to tell the caller to fall back.
    Skips the LLM call entirely when there is no history or rewriting is off."""
    if not settings.QUERY_REWRITE or not history:
        return None

    async def _run() -> str:
        parts = [
            t
            async for t in gemini_client.stream_chat(
                _format(history, message), system_instruction=_SYSTEM, temperature=0.0
            )
        ]
        return "".join(parts)

    try:
        text = (await asyncio.wait_for(_run(), timeout=_TIMEOUT_SECONDS)).strip().strip('"')
    except Exception:  # noqa: BLE001 -- rewriting is best-effort, never fatal
        logger.warning("query rewrite failed; falling back to history expansion", exc_info=True)
        return None
    return text[:500] or None
