"""Turn raw KeyEvents into semantic Actions.

Every key maps to *something* — unknown codes fall through to a "sparkle".
Also detects 2-key chords (two keys pressed within a short window and held
together) and mash-storms (5+ keys held, or a burst of rapid presses), which
toggle rainbow-chaos mode.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterator

from .base import KeyEvent

ARROWS = {"LEFT": (-1, 0), "RIGHT": (1, 0), "UP": (0, -1), "DOWN": (0, 1)}

# Number of objects shown for each digit key ("0" counts as ten).
_DIGIT_COUNT = {str(d): d for d in range(1, 10)} | {"0": 10}

MASH_HELD_THRESHOLD = 5     # keys held at once to enter chaos mode
MASH_RELEASE_BELOW = 3      # held-count to drop below to leave chaos mode
MASH_RATE_COUNT = 8         # presses ...
MASH_RATE_WINDOW = 1.0      # ... within this many seconds also triggers chaos

HOLD_SECONDS = 0.4          # held this long → a rainbow comet (see poll_holds)
MAX_COMETS = 4              # cap concurrent hold-comets (mash covers the rest)


@dataclass(frozen=True)
class Action:
    kind: str                     # letter|number|space|arrow|enter|special|sparkle|chord|mash_start|mash_end|hold_start|hold_end
    key: str = ""                 # originating key name ("" for synthetic actions)
    letter: str = ""              # for kind == "letter"
    count: int = 0                # for kind == "number"
    direction: tuple[int, int] = (0, 0)   # for kind == "arrow"
    keys: tuple[str, ...] = ()    # for kind == "chord"


# Keys that get a named "special" action (big bespoke effects); anything not
# matched anywhere becomes a "sparkle" so *every* key does something.
_SPECIALS = {
    "ESC": "swirl",
    "TAB": "zigzag",
    "CAPSLOCK": "colorwave",
    "LEFTSHIFT": "shimmer",
    "RIGHTSHIFT": "shimmer",
    "LEFTCTRL": "bounce",
    "RIGHTCTRL": "bounce",
    "LEFTALT": "spiral",
    "RIGHTALT": "spiral",
    "LEFTMETA": "pinwheel",
    "RIGHTMETA": "pinwheel",
    "MENU": "pinwheel",
    "COMPOSE": "pinwheel",
    "BACKSPACE": "vacuum",
    "DELETE": "vacuum",
    "F1": "balloon", "F2": "balloon", "F3": "balloon", "F4": "balloon",
    "F5": "balloon", "F6": "balloon", "F7": "balloon", "F8": "balloon",
    "F9": "balloon", "F10": "balloon", "F11": "balloon", "F12": "balloon",
    "MUTE": "drum", "VOLUMEUP": "drum", "VOLUMEDOWN": "drum",
    "PLAYPAUSE": "drum", "NEXTSONG": "drum", "PREVIOUSSONG": "drum",
    "STOPCD": "drum",
}


def classify(name: str) -> Action:
    """Total mapping: every key name yields exactly one base Action."""
    if len(name) == 1 and name.isalpha():
        return Action(kind="letter", key=name, letter=name)
    if name in _DIGIT_COUNT:
        return Action(kind="number", key=name, count=_DIGIT_COUNT[name])
    if name.startswith("KP") and name[2:] in _DIGIT_COUNT:  # numpad digits
        return Action(kind="number", key=name, count=_DIGIT_COUNT[name[2:]])
    if name == "SPACE":
        return Action(kind="space", key=name)
    if name in ARROWS:
        return Action(kind="arrow", key=name, direction=ARROWS[name])
    if name in ("ENTER", "KPENTER"):
        return Action(kind="enter", key=name)
    if name in _SPECIALS:
        return Action(kind="special", key=name, letter=_SPECIALS[name])
    return Action(kind="sparkle", key=name)


@dataclass
class KeyMapper:
    chord_window: float = 0.15
    _held: dict[str, float] = field(default_factory=dict)
    _recent_presses: deque = field(default_factory=lambda: deque(maxlen=32))
    _last_press: tuple[str, float] | None = None
    _in_mash: bool = False
    _mash_by_held: bool = False   # mash is (also) justified by the held-count path
    _holding: set[str] = field(default_factory=set)   # keys with an active hold-comet

    @property
    def in_mash(self) -> bool:
        return self._in_mash

    def held_count(self) -> int:
        return len(self._held)

    def feed(self, event: KeyEvent) -> Iterator[Action]:
        """Yield zero or more Actions for one KeyEvent (presses only produce
        base actions; releases only matter for mash bookkeeping)."""
        if event.pressed:
            # Key repeat (already held) produces nothing new.
            if event.name in self._held:
                return
            self._held[event.name] = event.ts
            self._recent_presses.append(event.ts)

            yield classify(event.name)

            # Chord: this press follows another distinct press within the
            # window, and that key is still held.
            if (
                self._last_press is not None
                and self._last_press[0] != event.name
                and self._last_press[0] in self._held
                and event.ts - self._last_press[1] <= self.chord_window
            ):
                yield Action(
                    kind="chord",
                    key=event.name,
                    keys=(self._last_press[0], event.name),
                )
            self._last_press = (event.name, event.ts)

            if len(self._held) >= MASH_HELD_THRESHOLD:
                self._mash_by_held = True
            if not self._in_mash and self._mash_triggered(event.ts):
                self._in_mash = True
                self._mash_by_held = len(self._held) >= MASH_HELD_THRESHOLD
                yield Action(kind="mash_start")
        else:
            self._held.pop(event.name, None)
            if event.name in self._holding:
                self._holding.discard(event.name)
                yield Action(kind="hold_end", key=event.name)
            if self._mash_should_end(event.ts):
                self._in_mash = False
                self._mash_by_held = False
                yield Action(kind="mash_end")

    def poll_holds(self, now: float) -> Iterator[Action]:
        """Time-based check the main loop calls every frame: any key held past
        HOLD_SECONDS starts a rainbow comet (hold_start), ended by its release
        (hold_end, emitted from feed). Arrows are excluded — holding an arrow
        already repeats frog shoves and a comet would muddy that mapping.

        Also exits rate-triggered mash mode once tapping slows: that exit is
        time-based (no release event arrives after the last tap), so it has
        to live in the per-frame poll rather than in feed()."""
        for name, since in list(self._held.items()):
            if (name not in self._holding
                    and name not in ARROWS
                    and len(self._holding) < MAX_COMETS
                    and now - since >= HOLD_SECONDS):
                self._holding.add(name)
                yield Action(kind="hold_start", key=name)
        if self._mash_should_end(now):
            self._in_mash = False
            self._mash_by_held = False
            yield Action(kind="mash_end")

    def _mash_should_end(self, now: float) -> bool:
        """Mash ends when nothing justifies it anymore. The held-count
        hysteresis (stay until < MASH_RELEASE_BELOW) only applies when the
        held path actually triggered it — otherwise 3-4 keys merely RESTING
        under a toy latched rate-triggered chaos on forever, because the
        exit floor was designed for the 5-keys-held entry it never took.
        The rate check itself stops chaos strobing ~19x/s under fast taps."""
        if not self._in_mash or self._rate_active(now):
            return False
        return not self._mash_by_held or len(self._held) < MASH_RELEASE_BELOW

    def _rate_active(self, now: float) -> bool:
        rapid = [t for t in self._recent_presses if now - t <= MASH_RATE_WINDOW]
        return len(rapid) >= MASH_RATE_COUNT

    def _mash_triggered(self, now: float) -> bool:
        if len(self._held) >= MASH_HELD_THRESHOLD:
            return True
        return self._rate_active(now)
