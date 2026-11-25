"""Load short speech clips on demand and arbitrate one narrator channel."""

from __future__ import annotations

import logging
from collections import OrderedDict, deque
from pathlib import Path

import pygame

from ..effects.numbers import CountAlong
from .tracks import read_audio_manifest

log = logging.getLogger(__name__)
_NUMBER_KEYS = frozenset(str(n) for n in range(1, 11))


class VoiceLoader:
    """Resolve a (group, key) to a decoded Sound. Never starts playback."""

    CACHE_SIZE = 48

    def __init__(self, directory: Path, espeak_dir: Path) -> None:
        self._files = read_audio_manifest(directory)
        self._espeak_dir = espeak_dir
        self._cache: OrderedDict[Path, pygame.mixer.Sound] = OrderedDict()
        self._unavailable: set[Path] = set()

    def _decode(self, path: Path) -> pygame.mixer.Sound | None:
        if path in self._cache:
            self._cache.move_to_end(path)
            return self._cache[path]
        if path in self._unavailable:
            return None
        try:
            sound = pygame.mixer.Sound(str(path))
        except (OSError, pygame.error) as exc:
            self._unavailable.add(path)
            log.debug("Voice clip unavailable: %s (%s)", path, exc)
            return None
        self._cache[path] = sound
        if len(self._cache) > self.CACHE_SIZE:
            self._cache.popitem(last=False)
        return sound

    def get(self, group: str, key: str | int) -> pygame.mixer.Sound | None:
        """Try the packaged take, then the corresponding installed espeak name."""
        key = str(key)
        if group in ("letters", "phrases"):
            key = key.upper()
        path = self._files.get((group, key))
        if path is not None:
            sound = self._decode(path)
            if sound is not None:
                return sound
        letter = group in ("letters", "phrases") and len(key) == 1 and "A" <= key <= "Z"
        number = group in ("numbers", "endings") and key in _NUMBER_KEYS
        if letter or number:
            return self._decode(self._espeak_dir / f"{key}.wav")
        return None


class NarratorPolicy:
    """Decide what to play on one channel, using only caller-supplied seconds.

    Pass the duration of the resolved clip to request(). On success the
    caller plays it immediately on the narrator channel (replacing the old
    clip). Pass zero for a missing clip so a silent key still gates phrases.
    """

    def __init__(self, *, party_duck: float, now: float = 0.0) -> None:
        self.party_duck = party_duck
        self._idle_since = now       # scheduled end of the most recent clip
        self._last_letter = -float("inf")
        self._count: deque[tuple[float, int]] = deque()

    def request(self, group: str, *, now: float, duration: float) -> bool:
        if group == "letters":
            self._last_letter = now
            self._count.clear()
        elif group == "phrases":
            if now < self._idle_since + 0.8 or now < self._last_letter + 0.6:
                return False
        elif now < self._idle_since:
            return False

        if duration <= 0:
            return False
        self._idle_since = now + duration
        return True

    def schedule_count(self, count: int, *, now: float) -> None:
        """Replace the old count. The first visual object appears at age zero."""
        count = max(1, min(count, 10))
        self._count = deque((now + i * CountAlong.POP_INTERVAL, i + 1) for i in range(count))

    def due_count(self, now: float) -> int | None:
        """Return the newest due number once; never replay a backlog after a late frame."""
        number = None
        while self._count and self._count[0][0] <= now:
            _, number = self._count.popleft()
        return number

    def gain(self, *, party_playing: bool) -> float:
        """Multiplier on narrator volume while the reward track is audible."""
        return self.party_duck if party_playing else 1.0
