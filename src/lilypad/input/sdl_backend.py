"""Dev-mode input backend: normal pygame/SDL keyboard events.

Used on desktops where the window system delivers keyboard input. Also
surfaces window-close (QUIT) so dev mode can be exited like a normal app.
"""

from __future__ import annotations

import time

import pygame

from .base import KeyEvent

# pygame key-name → canonical evdev-style name (see input/base.py).
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
}


def _canonical(key: int) -> str:
    raw = pygame.key.name(key)
    if raw in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[raw]
    if len(raw) == 1 and raw.isalpha():
        return raw.upper()
    if raw.startswith("[") and raw.endswith("]"):  # numpad, e.g. "[5]"
        inner = raw[1:-1]
        return f"KP{inner}" if inner.isdigit() else inner.upper()
    # "f1".."f12", punctuation names, media names — uppercase, no spaces.
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
