"""Fallback lighting backend via the OpenRazer daemon (RESEARCH.md §1).

Requires openrazer-daemon + the DKMS driver to be installed and running
(README troubleshooting covers this). Same LightingBackend interface, so it
is a drop-in swap via config: lighting.backend = "openrazer".
"""

from __future__ import annotations

import logging

from .base import Grid, LightingBackend
from .keymap import COLS, ROWS

log = logging.getLogger(__name__)


class OpenRazerBackend(LightingBackend):
    name = "openrazer"

    def __init__(self) -> None:
        from openrazer.client import DeviceManager

        self._kbd = None
        for dev in DeviceManager().devices:
            if dev.type == "keyboard":
                self._kbd = dev
                break
        if self._kbd is None:
            raise RuntimeError("openrazer daemon reports no keyboard devices")
        if not self._kbd.fx.advanced:
            raise RuntimeError(
                f"openrazer device {self._kbd.name!r} lacks per-key matrix support"
            )
        log.info("openrazer: using %s", self._kbd.name)

    def apply(self, grid: Grid) -> None:
        matrix = self._kbd.fx.advanced.matrix
        for r in range(ROWS):
            for c in range(COLS):
                matrix[r, c] = grid[r][c]
        matrix.draw()

    def set_brightness(self, value: float) -> None:
        try:
            self._kbd.brightness = max(0.0, min(100.0, value * 100.0))
        except Exception:                     # noqa: BLE001 — brightness is non-critical
            log.warning("openrazer: brightness set failed", exc_info=True)

    def close(self) -> None:
        try:
            self._kbd.fx.spectrum()
        except Exception:                     # noqa: BLE001 — best-effort restore
            pass
