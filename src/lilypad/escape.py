"""Parent escape hatch.

Watches the raw held-key set (independently of the mapper, so no toddler
input path can mask it). When every key of the configured combo is held
continuously for ``hold_seconds``, the hatch fires once.

Default combo: both Shifts + Backspace, held 5 seconds — deliberate for an
adult, effectively impossible for a 2-year-old to produce by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EscapeHatch:
    combo: tuple[str, ...] = ("LEFTSHIFT", "RIGHTSHIFT", "BACKSPACE")
    hold_seconds: float = 5.0
    _combo_down_since: float | None = field(default=None, repr=False)
    _fired: bool = field(default=False, repr=False)

    def update(self, held: frozenset[str], now: float) -> bool:
        """Feed the current held-key set; returns True exactly once when the
        combo has been held for the full duration."""
        if self._fired:
            return False
        if all(k in held for k in self.combo):
            if self._combo_down_since is None:
                self._combo_down_since = now
            elif now - self._combo_down_since >= self.hold_seconds:
                self._fired = True
                return True
        else:
            self._combo_down_since = None
        return False

    def hold_progress(self, now: float) -> float:
        """0..1 fraction of the hold completed (for a subtle on-screen cue)."""
        if self._combo_down_since is None:
            return 0.0
        return min(1.0, (now - self._combo_down_since) / self.hold_seconds)
