import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class SingleFlightTTLCache:
    """Process-shared TTL cache that coalesces concurrent equivalent loads."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._values: dict[str, tuple[float, object]] = {}
        self._inflight: dict[str, threading.Event] = {}

    def get_or_load(self, key: str, ttl_seconds: float, loader: Callable[[], T]) -> T:
        while True:
            with self._lock:
                cached = self._values.get(key)
                if cached and cached[0] > self._clock():
                    return cached[1]  # type: ignore[return-value]
                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._inflight[key] = event
                    break
            event.wait()

        try:
            value = loader()
        except Exception:
            with self._lock:
                self._inflight.pop(key, None)
                event.set()
            raise

        with self._lock:
            self._values[key] = (self._clock() + ttl_seconds, value)
            self._inflight.pop(key, None)
            event.set()
        return value

    def clear(self):
        with self._lock:
            self._values.clear()
