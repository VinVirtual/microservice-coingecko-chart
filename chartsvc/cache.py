"""Thread-safe TTL cache that can still hand out stale entries, and an image LRU."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, Optional, Tuple, TypeVar

V = TypeVar("V")


@dataclass(frozen=True)
class Entry(Generic[V]):
    value: V
    stored_at: float


class TTLCache(Generic[V]):
    """Entries are *fresh* for ``ttl`` seconds and *stale* until ``stale_ttl``.

    Stale entries are only returned when explicitly asked for, e.g. to keep
    serving charts while the upstream API is down.
    """

    def __init__(self, ttl: float, stale_ttl: float, max_entries: int,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl, self.stale_ttl, self.max_entries = ttl, max(stale_ttl, ttl), max_entries
        self._clock = clock
        self._data: OrderedDict[Hashable, Entry[V]] = OrderedDict()
        self._lock = threading.Lock()
        self._key_locks: dict = {}
        self.hits = self.misses = 0

    def _get(self, key: Hashable, max_age: float) -> Optional[Entry[V]]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None or self._clock() - entry.stored_at > max_age:
                return None
            self._data.move_to_end(key)
            return entry

    def get_fresh(self, key: Hashable) -> Optional[V]:
        entry = self._get(key, self.ttl)
        with self._lock:
            if entry is None:
                self.misses += 1
            else:
                self.hits += 1
        return None if entry is None else entry.value

    def get_stale(self, key: Hashable) -> Optional[Tuple[V, float]]:
        """``(value, age_seconds)`` for an entry younger than ``stale_ttl``."""
        entry = self._get(key, self.stale_ttl)
        return None if entry is None else (entry.value, self._clock() - entry.stored_at)

    def set(self, key: Hashable, value: V) -> None:
        with self._lock:
            self._data[key] = Entry(value, self._clock())
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def key_lock(self, key: Hashable) -> threading.Lock:
        """One lock per key so concurrent misses make a single upstream call."""
        with self._lock:
            lock = self._key_locks.get(key)
            if lock is None:
                if len(self._key_locks) > 4 * self.max_entries:
                    self._key_locks.clear()
                lock = self._key_locks[key] = threading.Lock()
            return lock

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class BytesLRU:
    """LRU of rendered images bounded by total size in bytes."""

    def __init__(self, max_bytes: int, ttl: float, clock: Callable[[], float] = time.monotonic):
        self.max_bytes, self.ttl, self._clock = max_bytes, ttl, clock
        self._data: OrderedDict[Hashable, Tuple[bytes, float]] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Optional[bytes]:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            if self._clock() - item[1] > self.ttl:
                self._size -= len(item[0])
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return item[0]

    def set(self, key: Hashable, value: bytes) -> None:
        if len(value) > self.max_bytes:
            return
        with self._lock:
            old = self._data.pop(key, None)
            if old is not None:
                self._size -= len(old[0])
            self._data[key] = (value, self._clock())
            self._size += len(value)
            while self._size > self.max_bytes:
                _, (dropped, _) = self._data.popitem(last=False)
                self._size -= len(dropped)

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return self._size
