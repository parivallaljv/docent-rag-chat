"""Prometheus metrics + a lightweight per-turn trace (stage timings and
approximate token counts) that is also emitted as one structured log line."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from prometheus_client import Counter, Histogram

logger = logging.getLogger("docent.trace")

CHAT_TURNS = Counter("docent_chat_turns_total", "Chat turns by outcome", ["outcome"])
STAGE_SECONDS = Histogram(
    "docent_stage_seconds",
    "Latency per pipeline stage",
    ["stage"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32),
)
TOKENS = Counter("docent_tokens_approx_total", "Approximate tokens (word-based)", ["direction"])
CACHE = Counter("docent_cache_total", "Cache lookups", ["cache", "result"])
RATE_LIMITED = Counter("docent_rate_limited_total", "Requests rejected by limiter", ["kind"])


class Trace:
    """Collects stage durations for one chat turn."""

    def __init__(self, **attrs) -> None:
        self.stages: dict[str, float] = {}
        self.attrs: dict = dict(attrs)
        self._t0 = time.perf_counter()

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.mark(name, time.perf_counter() - start)

    def mark(self, name: str, seconds: float) -> None:
        self.stages[name] = round(seconds, 4)
        STAGE_SECONDS.labels(stage=name).observe(seconds)

    def finish(self, outcome: str) -> None:
        total = time.perf_counter() - self._t0
        self.mark("total", total)
        CHAT_TURNS.labels(outcome=outcome).inc()
        for key, direction in (
            ("prompt_tokens_approx", "prompt"),
            ("completion_tokens_approx", "completion"),
        ):
            if key in self.attrs:
                TOKENS.labels(direction=direction).inc(self.attrs[key])
        logger.info(
            "chat_turn",
            extra={"outcome": outcome, "stages_s": self.stages, **self.attrs},
        )
