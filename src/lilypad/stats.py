"""Session play statistics for the parent's "today's play" card.

Pure and time-injected: nothing here reads a clock, draws, or touches the
disk. The main loop feeds it ``on_action`` / ``on_animal`` / ``on_party`` with
its own monotonic ``now``. "Today" means "since power-on": the SD card has a
corruption history, so these numbers live in memory only and die with the
process.

Activity model. Every child input (``on_action`` / ``on_animal``) is an
*activity tick*. Consecutive ticks no more than ``GAP_SECONDS`` apart belong
to the same run; a longer silence ends the run and the silence itself is not
counted as play. ``time_played`` is the total length of all runs and
``longest_streak`` is the length of the longest single run. A party is earned
play but is a minutes-long stretch of watching, so ``on_party`` only counts the
party; it does not bridge a gap.
"""

from __future__ import annotations

import math

GAP_SECONDS = 60.0

# Actions that end something rather than start it. A hold or a mash that is
# *released* (or times out) proves nothing about the child being there.
_PASSIVE_KINDS = frozenset({"mash_end", "hold_end"})


class PlayStats:
    """Accumulates one session's worth of play."""

    def __init__(self, gap: float = GAP_SECONDS) -> None:
        self.gap = gap
        self._letters: set[str] = set()
        self._counts: dict[str, int] = {}     # insertion order = first seen
        self._parties = 0
        self._last: float | None = None       # time of the latest tick
        self._run_start: float | None = None  # first tick of the current run
        self._played = 0.0                    # closed runs plus the open one
        self._closed = 0.0                    # total of runs already closed
        self._longest = 0.0

    # ----------------------------------------------------------------- feed

    def _tick(self, t: float) -> None:
        if not isinstance(t, (int, float)) or not math.isfinite(t):
            return
        if self._last is None:
            self._last = self._run_start = t
            return
        if t < self._last:
            t = self._last                     # a clock never runs backwards
        if t - self._last > self.gap:          # silence: close the run
            self._closed += self._last - self._run_start
            self._run_start = t
        self._last = t
        run = t - self._run_start
        self._played = self._closed + run
        if run > self._longest:
            self._longest = run

    def on_action(self, action, t: float) -> None:
        """Feed a mapper ``Action`` (or anything with ``kind`` / ``letter``)."""
        kind = getattr(action, "kind", "")
        if kind in _PASSIVE_KINDS:
            return
        if kind == "letter":
            # `special` actions carry a letter too, but only a real letter key
            # counts towards the A-Z grid.
            letter = str(getattr(action, "letter", "") or "").upper()
            if len(letter) == 1 and "A" <= letter <= "Z":
                self._letters.add(letter)
        self._tick(t)

    def on_animal(self, name: str, t: float) -> None:
        """An animal was summoned (any gait, any key, including F-key dinosaurs)."""
        self._counts[name] = self._counts.get(name, 0) + 1
        self._tick(t)

    def on_party(self, t: float) -> None:
        """A reward party started."""
        self._parties += 1

    # --------------------------------------------------------------- results

    @property
    def time_played(self) -> float:
        """Seconds of play, ignoring every silence longer than the gap."""
        return self._played

    @property
    def longest_streak(self) -> float:
        """Seconds in the longest run with no silence over the gap."""
        return self._longest

    @property
    def letters_found(self) -> frozenset[str]:
        return frozenset(self._letters)

    @property
    def animals_seen(self) -> frozenset[str]:
        return frozenset(self._counts)

    @property
    def animal_counts(self) -> dict[str, int]:
        return dict(self._counts)

    @property
    def favourite(self) -> str | None:
        """Most-summoned animal; a tie goes to whoever was seen first."""
        best: str | None = None
        best_n = 0
        for name, n in self._counts.items():     # first-seen order
            if n > best_n:
                best, best_n = name, n
        return best

    @property
    def parties(self) -> int:
        return self._parties
