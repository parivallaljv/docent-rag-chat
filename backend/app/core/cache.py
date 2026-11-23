"""Tiny in-process TTL + LRU cache (single worker; not shared across instances)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(
        self, max_size: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._max, self._ttl, self._clock = max_size, ttl_seconds, clock
        self._data: OrderedDict[Hashable, tuple[float, V]] = OrderedDict()

    def get(self, key: Hashable) -> V | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if self._clock() >= expires:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: Hashable, value: V) -> None:
        if self._max <= 0:
            return
        self._data[key] = (self._clock() + self._ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
