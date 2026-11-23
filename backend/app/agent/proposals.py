"""Human-in-the-loop proposals. The agent may PROPOSE a side effect, but nothing
happens until the user approves it in the UI. The only action today is saving a
short note to the user's memory. Proposals are in-memory, per user, short-lived."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from ..db import queries

ACTION_SAVE_MEMORY = "save_memory_note"
TTL_SECONDS = 600.0
MAX_PER_USER = 20
MAX_NOTE_CHARS = 300
MEMORY_LIMIT = 2000


@dataclass
class Proposal:
    id: str
    user_id: str
    action: str
    text: str
    expires: float


class ProposalStore:
    def __init__(self, ttl: float = TTL_SECONDS) -> None:
        self.ttl = ttl
        self._items: dict[str, Proposal] = {}

    def _gc(self) -> None:
        now = time.monotonic()
        for pid in [p for p, v in self._items.items() if v.expires <= now]:
            del self._items[pid]

    def create(self, user_id: str, action: str, text: str) -> Proposal | None:
        if action != ACTION_SAVE_MEMORY:
            return None
        text = " ".join(text.split())[:MAX_NOTE_CHARS]
        if not text:
            return None
        self._gc()
        mine = [p for p in self._items.values() if p.user_id == user_id]
        if len(mine) >= MAX_PER_USER:
            del self._items[min(mine, key=lambda p: p.expires).id]
        p = Proposal(secrets.token_urlsafe(12), user_id, action, text, time.monotonic() + self.ttl)
        self._items[p.id] = p
        return p

    def take(self, user_id: str, proposal_id: str) -> Proposal | None:
        """Remove and return the proposal if it exists, is unexpired and is the user's."""
        self._gc()
        p = self._items.get(proposal_id)
        if p is None or p.user_id != user_id:
            return None
        del self._items[proposal_id]
        return p


proposal_store = ProposalStore()


def append_note(existing: str | None, note: str) -> str:
    """Append a note, dropping the oldest lines if the 2000-char memory limit is hit."""
    lines = [ln for ln in (existing or "").splitlines() if ln.strip()] + [f"- {note}"]
    while len("\n".join(lines)) > MEMORY_LIMIT and len(lines) > 1:
        lines.pop(0)
    return "\n".join(lines)[-MEMORY_LIMIT:]


async def apply_proposal(pool, proposal: Proposal) -> None:
    assert proposal.action == ACTION_SAVE_MEMORY
    current = await queries.get_memory(pool, user_id=proposal.user_id)
    await queries.upsert_memory(
        pool, user_id=proposal.user_id, content=append_note(current, proposal.text)
    )
