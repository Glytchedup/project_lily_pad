"""Mock lighting backend for dev machines and tests.

Records frames and periodically logs a one-line summary so dev mode shows
the lighting pipeline is alive without any hardware.
"""

from __future__ import annotations

import logging
import time

from .base import Grid, LightingBackend

log = logging.getLogger(__name__)


class MockLightingBackend(LightingBackend):
    name = "mock"

    def __init__(self, log_every: float = 5.0) -> None:
        self.frames_applied = 0
        self.last_grid: Grid | None = None
        self.brightness = 1.0
        self.closed = False
        self._log_every = log_every
        self._last_log = 0.0

    def apply(self, grid: Grid) -> None:
        self.frames_applied += 1
        self.last_grid = grid
        now = time.monotonic()
        if now - self._last_log >= self._log_every:
            self._last_log = now
            lit = sum(1 for row in grid for px in row if any(px))
            log.info(
                "mock lighting: %d frames applied, %d/%d LEDs lit in latest",
                self.frames_applied, lit, len(grid) * len(grid[0]),
            )

    def set_brightness(self, value: float) -> None:
        self.brightness = value

    def close(self) -> None:
        self.closed = True
