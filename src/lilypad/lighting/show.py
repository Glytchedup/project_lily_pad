"""Beat-driven keyboard choreography. All positions passed to frame() are seconds."""

from __future__ import annotations

from ..audio.tracks import BeatClock
from .base import Grid, blank_grid, hsv
from .keymap import COLS, ROWS
from .patterns import RGB, screen_cell


def _columns(colours: list[RGB]) -> Grid:
    # Lighting compositors can change individual cells after we return.
    return [colours.copy() for _ in range(ROWS)]


def beat_chase(t: float, beat_phase: float, bar: int, is_drop: bool) -> Grid:
    """Three coloured runners travel one spacing per beat, with trailing light."""
    colours = []
    for col in range(COLS):
        trail = (beat_phase - 3 * col / COLS) % 1
        colours.append(hsv(bar / 8 + col / COLS, 0.88, 0.10 + 0.90 * (1 - trail)**3))
    return _columns(colours)


def rainbow_wipe(t: float, beat_phase: float, bar: int, is_drop: bool) -> Grid:
    """Spread a rainbow from one edge of the keyboard over the opening beat."""
    front = beat_phase * COLS
    colours = []
    for col in range(COLS):
        distance = COLS - 1 - col if bar % 4 == 3 else col
        brightness = 0.16 + 0.84 * max(0.0, min(1.0, front - distance + 1))
        colours.append(hsv(col / COLS + bar / 8, 0.88, brightness))
    return _columns(colours)


def drop_flash(t: float, beat_phase: float, bar: int, is_drop: bool) -> Grid:
    """Light every key together on a drop, then fade through warm gold."""
    if not is_drop:
        return beat_chase(t, beat_phase, bar, False)
    glow = 1 - beat_phase
    colour = hsv(0.105, 0.15 + 0.50 * beat_phase, 0.45 + 0.55 * glow)
    return _columns([colour] * COLS)


def parade_chase(t: float, beat_phase: float, bar: int, is_drop: bool, *,
                 x_frac: float = 0.5) -> Grid:
    """Centre a rainbow ribbon on the screen position of the leading animal."""
    centre = screen_cell(max(0.0, min(1.0, x_frac)), COLS)
    grid = blank_grid()
    for row in range(ROWS):
        for col in range(max(0, centre - 2), min(COLS, centre + 3)):
            brightness = (1 - abs(col - centre) / 3) * (1 - 0.25 * beat_phase)
            grid[row][col] = hsv(row / ROWS + (col - centre) / 12 + t / 8, 0.86, brightness)
    return grid


class PartyShow:
    """Read the shared audio clock without advancing it. Pass elapsed party time to frame."""

    def __init__(self, beat_clock: BeatClock | None = None) -> None:
        self.beat_clock = beat_clock
        self._free_clock = BeatClock()

    def frame(self, t: float, *, lead_x_frac: float | None = None) -> Grid:
        clock = self.beat_clock
        if clock is None:
            clock = self._free_clock
            clock.resync(max(0.0, t) * 1000)
        timing = (t, clock.beat_phase, clock.bar, clock.is_drop)
        if lead_x_frac is not None:
            return parade_chase(*timing, x_frac=lead_x_frac)
        if clock.bar < 0:
            return blank_grid()
        if clock.is_drop:
            return drop_flash(*timing)
        if clock.bar % 2:
            # The map can begin with a pickup or contain a short bar. Use its
            # indexed downbeats; J05 extrapolates in 4/4 beyond the last one.
            starts = clock._bar_starts
            if clock.bar < len(starts):
                downbeat = clock.beat_index == starts[clock.bar]
            else:
                downbeat = (clock.beat_index - starts[-1]) % 4 == 0
            if downbeat:
                return rainbow_wipe(*timing)
        return beat_chase(*timing)
