"""Model routing: a cheap rule-based classifier sends simple questions to a fast
model and analytical/multi-part ones to a stronger model (ROUTING_ENABLED)."""

from __future__ import annotations

import re

from ..core.config import settings

_HARD = re.compile(
    r"\b(compare|contrast|difference|differ|why|explain|summari[sz]e|analy[sz]e|trade-?offs?|"
    r"step by step|how does|how do|pros and cons|relationship)\b",
    re.I,
)


def is_complex(question: str) -> bool:
    q = question.strip()
    return len(q.split()) > 25 or q.count("?") > 1 or bool(_HARD.search(q))


def route_model(question: str) -> str:
    if not settings.ROUTING_ENABLED:
        return settings.CHAT_MODEL
    strong = settings.CHAT_MODEL_STRONG or settings.CHAT_MODEL
    fast = settings.CHAT_MODEL_FAST or settings.CHAT_MODEL
    return strong if is_complex(question) else fast
