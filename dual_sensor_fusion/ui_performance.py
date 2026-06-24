from __future__ import annotations

from collections import deque
import queue
import threading
import time
from typing import Any, Iterable

import numpy as np


class RateLimiter:
    """Simple monotonic fixed-rate gate."""

    def __init__(self, rate_hz: float):
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        self.interval_sec = 1.0 / float(rate_hz)
        self.last_run = float("-inf")

    def due(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else float(now)
        if current - self.last_run < self.interval_sec:
            return False
        self.last_run = current
        return True


class RollingRate:
    def __init__(self, window_sec: float = 2.0):
        self.window_sec = max(0.25, float(window_sec))
        self._times: deque[float] = deque()

    def mark(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else float(now)
        self._times.append(current)
        cutoff = current - self.window_sec
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

    def value(self, now: float | None = None) -> float:
        current = time.monotonic() if now is None else float(now)
        cutoff = current - self.window_sec
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
        if len(self._times) < 2:
            return 0.0
        elapsed = self._times[-1] - self._times[0]
        return (len(self._times) - 1) / elapsed if elapsed > 0 else 0.0


def downsample_series(
    x: Iterable[float] | np.ndarray,
    *series: Iterable[float] | np.ndarray,
    max_points: int,
) -> tuple[np.ndarray, ...]:
    """Return aligned arrays with at most max_points, preserving endpoints."""

    arrays = (np.asarray(x), *(np.asarray(values) for values in series))
    count = len(arrays[0])
    if max_points < 2:
        raise ValueError("max_points must be at least 2")
    if any(len(values) != count for values in arrays):
        raise ValueError("all series must have the same length")
    if count <= max_points:
        return arrays
    indices = np.linspace(0, count - 1, max_points, dtype=np.int64)
    return tuple(values[indices] for values in arrays)


def drain_latest_by_kind(
    source: queue.Queue,
) -> tuple[dict[str, Any], int, int]:
    """Drain a queue and retain only the newest item for each item[0] kind."""

    latest: dict[str, Any] = {}
    consumed = 0
    while True:
        try:
            item = source.get_nowait()
        except queue.Empty:
            break
        consumed += 1
        latest[str(item[0])] = item
    return latest, consumed, max(0, consumed - len(latest))


class AsyncMethodWorker:
    """Run method calls on one background thread with bounded backlog."""

    def __init__(
        self,
        target: Any,
        *,
        max_pending: int = 512,
        flush_interval_sec: float = 1.0,
        flush_rows: int = 50,
    ):
        self.target = target
        self.flush_interval_sec = max(0.05, float(flush_interval_sec))
        self.flush_rows = max(1, int(flush_rows))
        self.queue: queue.Queue = queue.Queue(maxsize=max(1, int(max_pending)))
        self.dropped = 0
        self.errors = 0
        self.last_flush_monotonic = time.monotonic()
        self._rows_since_flush = 0
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run, name="fusion-csv-writer", daemon=True
        )
        self._thread.start()

    @property
    def backlog(self) -> int:
        return self.queue.qsize()

    @property
    def last_flush_age_sec(self) -> float:
        return max(0.0, time.monotonic() - self.last_flush_monotonic)

    def submit(self, method_name: str, *args: Any, row_weight: int = 1) -> bool:
        if self._stopping:
            return False
        try:
            self.queue.put_nowait((method_name, args, max(1, int(row_weight))))
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def _flush(self) -> None:
        flush = getattr(self.target, "flush", None)
        if callable(flush):
            flush()
        self._rows_since_flush = 0
        self.last_flush_monotonic = time.monotonic()

    def _run(self) -> None:
        while not self._stopping or not self.queue.empty():
            try:
                method_name, args, row_weight = self.queue.get(
                    timeout=self.flush_interval_sec
                )
            except queue.Empty:
                self._flush()
                continue
            try:
                getattr(self.target, method_name)(*args)
                self._rows_since_flush += row_weight
            except Exception:
                self.errors += 1
            finally:
                self.queue.task_done()
            if (
                self._rows_since_flush >= self.flush_rows
                or self.last_flush_age_sec >= self.flush_interval_sec
            ):
                self._flush()

    def close(self, timeout_sec: float = 5.0) -> None:
        self._stopping = True
        self._thread.join(timeout=max(0.0, float(timeout_sec)))
        self._flush()
        close = getattr(self.target, "close", None)
        if callable(close):
            close()
