"""Threaded wrapper for hardware lighting backends.

razer_hid's apply() is ~7 USB control transfers with inter-report delays —
milliseconds of blocking that must not live in the 60 fps render loop. This
wrapper ships frames from a worker thread instead; apply() just swaps the
pending frame (latest-wins, stale frames are dropped, never queued).

The mock backend stays unwrapped: tests and dev logs want synchronous calls.
"""

from __future__ import annotations

import logging
import threading

from .base import Grid, LightingBackend

log = logging.getLogger(__name__)


class ThreadedLightingBackend(LightingBackend):
    def __init__(self, inner: LightingBackend) -> None:
        self.inner = inner
        self.name = f"{inner.name} (threaded)"
        self._cond = threading.Condition()
        self._pending: Grid | None = None
        self._stop = False
        self._io_lock = threading.Lock()   # serializes USB access with set_brightness
        self._worker = threading.Thread(target=self._run, name="lilypad-lighting",
                                        daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                grid, self._pending = self._pending, None
            try:
                with self._io_lock:
                    self.inner.apply(grid)
            except Exception:                 # noqa: BLE001 — keep the show alive
                log.warning("lighting apply failed", exc_info=True)

    def apply(self, grid: Grid) -> None:
        with self._cond:
            self._pending = grid              # latest-wins
            self._cond.notify()

    def set_brightness(self, value: float) -> None:
        with self._io_lock:
            self.inner.set_brightness(value)

    def close(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()
        self._worker.join(timeout=2.0)
        with self._io_lock:
            self.inner.close()
