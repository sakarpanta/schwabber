from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _Entry[V]:
    value: V
    stored_at: float
    expires_at: float


class TtlLruCache[K, V]:
    def __init__(
        self, max_entries: int = 1024, clock: Callable[[], float] = monotonic
    ) -> None:
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()

    def get(self, key: K) -> tuple[V, int] | None:
        entry = self._entries.get(key)
        now = self._clock()
        if entry is None:
            return None
        if now >= entry.expires_at:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry.value, int(now - entry.stored_at)

    def set(self, key: K, value: V, ttl_seconds: int) -> None:
        now = self._clock()
        self._entries[key] = _Entry(value, now, now + ttl_seconds)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
