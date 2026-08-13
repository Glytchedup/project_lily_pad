"""Synthetic input backend for smoke tests (--smoke N).

Generates a toddler-realistic stream of key events — letters, numbers,
space, arrows, enter, specials, occasional chords and a mash burst — so the
whole pipeline (mapper → effects → lighting → audio) can be exercised with
no keyboard at all. Used for dev smoke checks and as an on-device self-test.
"""

from __future__ import annotations

import random
import time

from .base import KeyEvent

_KEYS = (
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(d) for d in range(10)]
    + ["SPACE", "ENTER", "LEFT", "RIGHT", "UP", "DOWN",
       "ESC", "F5", "F9", "BACKSPACE", "PLAYPAUSE", "LEFTMETA"]
    # Colour and shape keys. The smoke run is the on-device self-test, so it
    # has to reach every effect family — a whole subsystem that the automated
    # check never touches is a subsystem nobody finds out about until a
    # toddler does.
    + ["GRAVE", "MINUS", "EQUAL", "LEFTBRACE", "RIGHTBRACE", "BACKSLASH",
       "INSERT"]
    + ["SEMICOLON", "APOSTROPHE", "COMMA", "DOT", "SLASH"]
)


class SyntheticInputBackend:
    def __init__(self, duration: float = 6.0, seed: int = 42,
                 events_per_second: float = 5.0) -> None:
        self.duration = duration
        self.rng = random.Random(seed)
        self.interval = 1.0 / events_per_second
        self.quit_requested = False
        self._held: set[str] = set()
        self._start = 0.0
        self._next_event = 0.0
        self._mash_done = False

    def start(self) -> None:
        self._start = time.monotonic()
        self._next_event = self._start

    def poll(self) -> list[KeyEvent]:
        now = time.monotonic()
        elapsed = now - self._start
        if elapsed >= self.duration:
            self.quit_requested = True
            return []
        events: list[KeyEvent] = []

        # One scripted mash burst halfway through: 6 keys down at once.
        if not self._mash_done and elapsed >= self.duration / 2:
            self._mash_done = True
            burst_keys = self.rng.sample(_KEYS[:26], 6)
            for k in burst_keys:
                if k not in self._held:
                    self._held.add(k)
                    events.append(KeyEvent(name=k, pressed=True, ts=now))
            return events

        while now >= self._next_event:
            self._next_event += self.interval
            # Release something if lots are held, else press something new.
            if self._held and (len(self._held) > 3 or self.rng.random() < 0.45):
                k = self.rng.choice(sorted(self._held))
                self._held.discard(k)
                events.append(KeyEvent(name=k, pressed=False, ts=now))
            else:
                k = self.rng.choice(_KEYS)
                if k not in self._held:
                    self._held.add(k)
                    events.append(KeyEvent(name=k, pressed=True, ts=now))
        return events

    def held_keys(self) -> frozenset[str]:
        return frozenset(self._held)

    def stop(self) -> None:
        self._held.clear()
