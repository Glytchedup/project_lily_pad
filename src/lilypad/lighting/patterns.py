"""Paint the moving animal patches on the BlackWidow's LED matrix."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

from .keymap import COLS, ROWS

RGB = tuple[int, int, int]

# Moonlit Gouache pigments from docs/ART_BIBLE.md. Mix shades once, so a
# lighting tick only selects colours and moves them by whole cells.
MOON = (232, 232, 214)
RIM = (191, 216, 255)
BOUNCE = (242, 196, 107)
KEYLINE = (42, 30, 44)
DEEP_WATER = (14, 26, 44)
LILY = (44, 120, 64)
LOTUS = (219, 112, 147)


def _mix(a: RGB, b: RGB, amount: float) -> RGB:
    r, g, blue = (round(x + (y - x) * amount) for x, y in zip(a, b))
    return r, g, blue


OCHRE = _mix(BOUNCE, KEYLINE, 0.55)
WAVE_BLUE = _mix(DEEP_WATER, RIM, 0.5)
LEAF = _mix(LILY, BOUNCE, 0.28)
PINK_PULSE = tuple(_mix(LOTUS, MOON, t) for t in (0.0, 0.2, 0.4, 0.6, 0.4, 0.2))

# The remaining cast carries one coat colour and a travelling rim-light glint.
COATS = {
    "alligator": LILY, "bear": OCHRE, "cow": MOON, "duck": BOUNCE,
    "elephant": _mix(RIM, KEYLINE, 0.4), "fox": _mix(LOTUS, BOUNCE, 0.5),
    "horse": OCHRE, "iguana": LEAF, "koala": _mix(MOON, KEYLINE, 0.4),
    "monkey": OCHRE, "pig": LOTUS, "quail": _mix(BOUNCE, MOON, 0.25),
    "rabbit": MOON, "sheep": MOON, "unicorn": _mix(MOON, LOTUS, 0.15),
    "xrayfish": _mix(RIM, LILY, 0.3), "yak": _mix(OCHRE, KEYLINE, 0.4),
}


def _spots(x, dy, width, frame, coat):
    return OCHRE if (x + dy * 2) % 4 == 0 else BOUNCE


def _stripes(x, dy, width, frame, coat):
    return MOON if x % 2 == 0 else KEYLINE


def _mane(x, dy, width, frame, coat):
    # Golden centre, warm glow, darker tips around the mane.
    distance = abs(2 * x + 1 - width)
    if dy == 0 and distance <= width // 3:
        return MOON
    return BOUNCE if distance <= width * 2 // 3 else OCHRE


def _wave(x, dy, width, frame, coat):
    crest = ((x + frame // 4) % 4) // 2
    return RIM if dy == -crest else WAVE_BLUE


def _eyes(x, dy, width, frame, coat):
    inset = (width - 1) // 4
    if dy == 0 and x in (inset, width - 1 - inset):
        return KEYLINE if frame % 75 >= 70 else MOON
    return None


def _pulse(x, dy, width, frame, coat):
    return PINK_PULSE[(frame // 4) % len(PINK_PULSE)]


def _stomp(x, dy, width, frame, coat):
    # The whole green patch drops a row and brightens on the downbeat.
    if frame % 18 < 5:
        return LEAF if dy >= 0 else None
    return LILY if dy <= 0 else None


def _sparkle(x, dy, width, frame, coat):
    if dy == 0 and x == (frame // 4) % width:
        return RIM
    return coat


PATTERNS = {
    "giraffe": _spots, "zebra": _stripes, "lion": _mane,
    "whale": _wave, "narwhal": _wave, "owl": _eyes, "jellyfish": _pulse,
    "trex": _stomp, "velociraptor": _stomp, "stegosaurus": _stomp,
    "triceratops": _stomp, "brachiosaurus": _stomp, "pterodactyl": _stomp,
    "default": _sparkle,
}


def screen_cell(fraction: float, cells: int) -> int:
    """Map screen endpoints to the first and last LED, before clipping."""
    return math.floor(fraction * (cells - 1) + 0.5)


@dataclass(frozen=True, slots=True)
class Track:
    name: str
    x_frac: float
    y_frac: float
    width_frac: float
    start: float

    def pixels(self, now: float) -> Iterator[tuple[int, int, RGB]]:
        """Yield visible (row, column, colour) cells in sprite-local phase."""
        width = max(1, min(COLS, round(self.width_frac * COLS)))
        left = screen_cell(self.x_frac, COLS) - width // 2
        center = screen_cell(self.y_frac, ROWS)
        offsets = (-1, 0, 1)
        pattern = PATTERNS.get(self.name, _sparkle)
        if pattern is _wave:
            center = ROWS - 1
            offsets = (-1, 0)
        frame = max(0, int((now - self.start) * 30))
        coat = COATS.get(self.name, BOUNCE)
        # Clip the projection, keeping the markings anchored to the animal
        # even when part of its body is entering or leaving the screen.
        columns = range(max(0, -left), min(width, COLS - left))
        for dy in offsets:
            row = center + dy
            if 0 <= row < ROWS:
                for x in columns:
                    colour = pattern(x, dy, width, frame, coat)
                    if colour is not None:
                        yield row, left + x, colour
