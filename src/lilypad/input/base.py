"""Normalized key events and the input-backend interface.

Key names are canonical Linux evdev names without the ``KEY_`` prefix
("A", "1", "SPACE", "LEFTSHIFT", "PLAYPAUSE", ...). Both backends normalize
to this space so the mapper, escape hatch, and lighting keymap are
backend-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KeyEvent:
    name: str        # canonical key name, e.g. "A", "SPACE", "LEFTSHIFT"
    pressed: bool    # True = key down, False = key up
    ts: float        # monotonic timestamp (seconds)


class InputBackend(Protocol):
    def start(self) -> None:
        """Acquire devices (and on the Pi, the exclusive grab)."""

    def poll(self) -> list[KeyEvent]:
        """Return all events since the last poll. Non-blocking."""

    def held_keys(self) -> frozenset[str]:
        """Names of keys currently held down (for escape hatch / mash logic)."""

    def stop(self) -> None:
        """Release devices/grabs. Idempotent."""
