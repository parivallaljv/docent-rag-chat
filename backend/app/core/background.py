"""Fire-and-forget tasks that must not be garbage-collected mid-flight."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine, what: str = "background task") -> None:
    async def _run() -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001
            logger.warning("%s failed", what, exc_info=True)

    task = asyncio.create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
