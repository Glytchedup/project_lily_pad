"""Lighting interface + host-side animation math.

All animation (breathing, screen mirror, ripples, strobe) is computed into a
6×22 RGB grid; backends only ship the finished grid to hardware. That keeps
every visual behavior identical — and unit-testable — across the razer_hid,
openrazer, and mock backends (PLAN.md D10).
"""

from __future__ import annotations

import colorsys
import math
from abc import ABC, abstractmethod
from collections.abc import Hashable, Iterable
from dataclasses import dataclass

from .keymap import COLS, ROWS, position
from .patterns import RGB, Track, screen_cell

Grid = list[list[RGB]]

RIPPLE_SPEED = 14.0     # matrix cells per second
RIPPLE_WIDTH = 1.6      # ring thickness in cells
RIPPLE_LIFE = 1.2       # seconds
KEY_FLASH_LIFE = 0.5    # pressed key stays lit this long
BREATHE_PERIOD = 6.0    # idle breathing cycle, seconds
STROBE_HZ = 6.0         # mash-mode rainbow strobe
MAX_TRACKS = 5


def blank_grid() -> Grid:
    return [[(0, 0, 0) for _ in range(COLS)] for _ in range(ROWS)]


def hsv(h: float, s: float = 1.0, v: float = 1.0) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def _add(a: RGB, b: RGB) -> RGB:
    return (min(255, a[0] + b[0]), min(255, a[1] + b[1]), min(255, a[2] + b[2]))


@dataclass(frozen=True)
class Ripple:
    row: int
    col: int
    start: float
    hue: float


@dataclass(frozen=True, slots=True)
class Bloom:
    row: int
    col: int
    colour: RGB
    start: float


class LightingBackend(ABC):
    """Ships finished frames to hardware (or nowhere, for the mock)."""

    name: str = "base"

    @abstractmethod
    def apply(self, grid: Grid) -> None: ...

    @abstractmethod
    def set_brightness(self, value: float) -> None:
        """0.0 .. 1.0"""

    @abstractmethod
    def close(self) -> None: ...


def render_frame(
    now: float,
    ripples: list[Ripple],
    lit_keys: dict[str, tuple[float, float]],  # name -> (press_time, hue)
    mash: bool,
    tracks: Iterable[Track] = (),
    blooms: Iterable[Bloom] = (),
) -> Grid:
    """Pure frame function: current lighting state → 6×22 RGB grid."""
    grid = blank_grid()

    if mash:
        # Strobe rainbow: hue sweeps across columns and flashes.
        flash = 0.35 + 0.65 * (math.sin(now * STROBE_HZ * math.tau) > 0)
        for r in range(ROWS):
            for c in range(COLS):
                grid[r][c] = hsv(now * 0.8 + c / COLS, 1.0, flash)
        return grid

    # Idle breathing base: slow hue drift, gentle brightness swell.
    breathe = 0.25 + 0.20 * (1 + math.sin(now * math.tau / BREATHE_PERIOD)) / 2
    base = hsv(now * 0.03, 0.9, breathe)
    for r in range(ROWS):
        for c in range(COLS):
            grid[r][c] = base

    # Paint coats in arrival order. Transparent cells leave older coats
    # visible, and fireworks briefly illuminate the animals underneath.
    for track in tracks:
        for r, c, colour in track.pixels(now):
            grid[r][c] = colour
    for bloom in blooms:
        if bloom.start > now:
            continue
        r, c = bloom.row, bloom.col
        grid[r][c] = bloom.colour
        red, green, blue = bloom.colour
        halo = (red // 2, green // 2, blue // 2)
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < ROWS and 0 <= nc < COLS:
                grid[nr][nc] = _add(grid[nr][nc], halo)

    # Expanding rings from recent keypresses.
    for rp in ripples:
        age = now - rp.start
        if not 0.0 <= age <= RIPPLE_LIFE:
            continue
        radius = age * RIPPLE_SPEED
        fade = 1.0 - age / RIPPLE_LIFE
        color = hsv(rp.hue, 1.0, fade)
        for r in range(ROWS):
            for c in range(COLS):
                d = math.hypot(r - rp.row, (c - rp.col) * 0.55)  # cells are wider than tall
                if abs(d - radius) <= RIPPLE_WIDTH / 2:
                    grid[r][c] = _add(grid[r][c], color)

    # Pressed keys flash bright in their ripple's hue.
    for name, (t, hue) in lit_keys.items():
        age = now - t
        if 0.0 <= age <= KEY_FLASH_LIFE:
            r, c = position(name)
            grid[r][c] = hsv(hue, 0.25, 1.0 - 0.5 * (age / KEY_FLASH_LIFE))

    return grid


class LightingEngine:
    """Holds lighting state, renders frames at its own fps, feeds a backend."""

    def __init__(self, backend: LightingBackend, fps: int = 30, brightness: float = 0.9,
                 *, mirror_animals: bool = True):
        self.backend = backend
        self.frame_interval = 1.0 / max(1, fps)
        self._ripples: list[Ripple] = []
        self._lit: dict[str, tuple[float, float]] = {}
        self._mirror_animals = mirror_animals
        self._tracks: dict[Hashable, Track] = {}
        self._blooms: dict[tuple[int, int], Bloom] = {}
        self._mash = False
        self._sleep = False
        self._last_frame = float("-inf")  # first tick always renders
        self._hue_cursor = 0.13
        backend.set_brightness(brightness)

    def key_pressed(self, name: str, now: float) -> None:
        # Golden-angle hue stepping: consecutive presses get distinct colors.
        self._hue_cursor = (self._hue_cursor + 0.381966) % 1.0
        r, c = position(name)
        self._ripples.append(Ripple(row=r, col=c, start=now, hue=self._hue_cursor))
        self._lit[name] = (now, self._hue_cursor)

    def set_mash(self, on: bool) -> None:
        self._mash = on

    def track(self, token: Hashable, pattern_name: str, x_frac: float, y_frac: float,
              width_frac: float, now: float) -> None:
        """Place or move a sprite by its screen centre and full screen-relative width.

        A stable token keeps its animation phase until untracked. If the
        cast exceeds five, the newest arrival replaces the oldest one.
        """
        if not self._mirror_animals or self._sleep:
            return
        previous = self._tracks.get(token)
        if previous is None and len(self._tracks) == MAX_TRACKS:
            del self._tracks[next(iter(self._tracks))]
        start = previous.start if previous and previous.name == pattern_name else now
        self._tracks[token] = Track(pattern_name, x_frac, y_frac, width_frac, start)

    def untrack(self, token: Hashable) -> None:
        self._tracks.pop(token, None)

    def bloom(self, x_frac: float, y_frac: float, colour: RGB, now: float) -> None:
        """Flash a burst on the next lighting frame, coalescing hits on the same LED."""
        if not self._mirror_animals or self._sleep:
            return
        row, col = screen_cell(y_frac, ROWS), screen_cell(x_frac, COLS)
        if 0 <= row < ROWS and 0 <= col < COLS:
            self._blooms[row, col] = Bloom(row, col, colour, now)

    def set_sleep(self, on: bool) -> None:
        """Go dark with the screen, and come back the instant it does.

        A keyboard breathing rainbows all night in a toddler's room defeats
        the point of blanking the display, so sleep blanks the LEDs once and
        then stops sending frames entirely.
        """
        if on == self._sleep:
            return
        self._sleep = on
        if on:
            self._ripples.clear()
            self._lit.clear()
            self._tracks.clear()
            self._blooms.clear()
            self.backend.apply(blank_grid())
        # Render immediately on the next tick either way rather than waiting
        # out the frame interval.
        self._last_frame = float("-inf")

    def tick(self, now: float) -> None:
        if self._sleep:
            return
        if now - self._last_frame < self.frame_interval:
            return
        self._last_frame = now
        self._ripples = [rp for rp in self._ripples if now - rp.start <= RIPPLE_LIFE]
        self._lit = {k: v for k, v in self._lit.items() if now - v[0] <= KEY_FLASH_LIFE}
        self.backend.apply(render_frame(now, self._ripples, self._lit, self._mash,
                                        self._tracks.values(), self._blooms.values()))
        if self._blooms:
            self._blooms = {k: b for k, b in self._blooms.items() if b.start > now}

    def close(self) -> None:
        self.backend.close()
