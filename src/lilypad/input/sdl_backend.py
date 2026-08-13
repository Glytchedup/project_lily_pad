"""Dev-mode input backend: normal pygame/SDL keyboard events.

Used on desktops where the window system delivers keyboard input. Also
surfaces window-close (QUIT) so dev mode can be exited like a normal app.
"""

from __future__ import annotations

import time

import pygame

from .base import KeyEvent

# pygame key-name → canonical evdev-style name (see input/base.py).
#
# The names have to match what `evdev_backend` produces — `ecodes.KEY_*` with
# the `KEY_` prefix stripped — or dev mode and the Pi disagree about what a key
# is, and the whole "runs and tests on a desktop" promise quietly stops holding
# for the keys that differ.
_NAME_OVERRIDES = {
    "return": "ENTER",
    "escape": "ESC",
    "left shift": "LEFTSHIFT",
    "right shift": "RIGHTSHIFT",
    "left ctrl": "LEFTCTRL",
    "right ctrl": "RIGHTCTRL",
    "left alt": "LEFTALT",
    "right alt": "RIGHTALT",
    "left meta": "LEFTMETA",
    "right meta": "RIGHTMETA",
    "caps lock": "CAPSLOCK",
    "backspace": "BACKSPACE",
    "delete": "DELETE",
    "space": "SPACE",
    "tab": "TAB",
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
    "menu": "MENU",
    # Punctuation. pygame reports these as the printed glyph (","), evdev as a
    # word ("COMMA"), so without these the colour and shape keys — and only
    # those — are dead in dev mode while working perfectly on the Pi.
    ",": "COMMA",
    ".": "DOT",
    "/": "SLASH",
    ";": "SEMICOLON",
    "'": "APOSTROPHE",
    "`": "GRAVE",
    "-": "MINUS",
    "=": "EQUAL",
    "[": "LEFTBRACE",
    "]": "RIGHTBRACE",
    "\\": "BACKSLASH",
}

# Numpad keys arrive bracketed, e.g. "[5]" or "[/]". The digits become KP0-KP9
# below; the operators need naming, and must not be allowed to collapse onto
# the main-row punctuation above — "[/]" and "/" are different keys.
_NUMPAD_OVERRIDES = {
    "/": "KPSLASH",
    "*": "KPASTERISK",
    "+": "KPPLUS",
    "-": "KPMINUS",
    ".": "KPDOT",
    "enter": "KPENTER",
}


def _canonical(key: int) -> str:
    raw = pygame.key.name(key)
    # Numpad first: "[.]" must become KPDOT, not fall through to the main-row
    # "." override and turn into DOT.
    if raw.startswith("[") and raw.endswith("]") and len(raw) > 2:
        inner = raw[1:-1]
        if inner.isdigit():
            return f"KP{inner}"
        return _NUMPAD_OVERRIDES.get(inner, f"KP{inner.upper()}")
    if raw in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[raw]
    if len(raw) == 1 and raw.isalpha():
        return raw.upper()
    # "f1".."f12", named keys, media names — uppercase, no spaces.
    return raw.upper().replace(" ", "")


class SdlInputBackend:
    def __init__(self) -> None:
        self.quit_requested = False
        self._held: set[str] = set()

    def start(self) -> None:  # pygame.init() is done by the app shell
        pass

    def poll(self) -> list[KeyEvent]:
        now = time.monotonic()
        events: list[KeyEvent] = []
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.quit_requested = True
            elif ev.type == pygame.KEYDOWN:
                name = _canonical(ev.key)
                self._held.add(name)
                events.append(KeyEvent(name=name, pressed=True, ts=now))
            elif ev.type == pygame.KEYUP:
                name = _canonical(ev.key)
                self._held.discard(name)
                events.append(KeyEvent(name=name, pressed=False, ts=now))
        return events

    def held_keys(self) -> frozenset[str]:
        return frozenset(self._held)

    def stop(self) -> None:
        self._held.clear()
