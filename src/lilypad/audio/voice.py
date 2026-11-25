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

    @staticmethod
    def _normal(group: str, key: str | int) -> str:
        key = str(key)
        return key.upper() if group in ("letters", "phrases") else key

    def get_packaged(self, group: str, key: str | int) -> pygame.mixer.Sound | None:
        """The packaged take only, with no espeak stand-in.

        A "G is for Giraffe!" line has no honest espeak equivalent (the
        letter-name wav would just repeat the name), so the phrase caller asks
        for the packaged take and stays silent without it.
        """
        path = self._files.get((group, self._normal(group, key)))
        return self._decode(path) if path is not None else None

    def get(self, group: str, key: str | int) -> pygame.mixer.Sound | None:
        """Try the packaged take, then the corresponding installed espeak name."""
        key = self._normal(group, key)
        sound = self.get_packaged(group, key)
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
        elif group == "endings":
            pass  # the count's climax replaces a still-sounding "nine"
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


# ---------------------------------------------------------------------------
# The line catalogue
# ---------------------------------------------------------------------------
# One row per clip the narrator can say. An id is "<manifest group>.<key>",
# so ``phrases.G`` is the manifest table ``[phrases.G]`` and the TTS batch can
# name each rendered file from it. The engine requests exactly these
# (group, key) pairs; tests keep the two in step.

#: Letter names spelled the way a TTS voice should say them.
LETTER_NAMES: dict[str, str] = dict(zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    ("Ay", "Bee", "See", "Dee", "Ee", "Eff", "Gee", "Aitch", "Eye", "Jay",
     "Kay", "El", "Em", "En", "Oh", "Pee", "Cue", "Are", "Ess", "Tee", "You",
     "Vee", "Double-you", "Ex", "Why", "Zee"), strict=True))

#: How a creature's name is written for speech, where the id would be read badly.
_SPOKEN_ANIMAL = {"trex": "T-Rex", "xrayfish": "X-ray fish"}

_NUMBER_WORDS = ("One", "Two", "Three", "Four", "Five",
                 "Six", "Seven", "Eight", "Nine", "Ten")

#: Praise and party lines, keyed by the event name ``AudioEngine.narrate`` takes.
PRAISE_LINES: dict[str, str] = {
    "party_start": "You did it! Party time!",
    "alphabet_complete": "You found ALL the animals!",
    "party_end": "What a great party!",
    "milestone": "Hooray! Look at that!",
    "great_job": "Great job!",
    "well_done": "Well done!",
    "wow": "Wow!",
    "yay": "Yay!",
    "amazing": "Amazing!",
    "super": "Super duper!",
    "good_job": "Good job, you!",
    "nice": "Nice one!",
    "fantastic": "Fantastic!",
    "hooray": "Hooray!",
    "bravo": "Bravo!",
    "you_found_it": "You found it!",
    "so_clever": "You are so clever!",
    "keep_going": "Keep going!",
    "high_five": "High five!",
    "look_at_that": "Look at that!",
    "lily_hi": "Hi, Lily!",
    "lily_great": "Great job, Lily!",
    "lily_party": "Lily, it's party time!",
    "lily_wow": "Wow, Lily!",
    "lily_all": "Lily found all the animals!",
}


def _spoken(animal: str) -> str:
    return _SPOKEN_ANIMAL.get(animal, animal)


def narrator_lines() -> list[dict[str, str]]:
    """Every clip to record: ``{id, text, kind}``, in a stable order."""
    from ..effects.animals import ANIMAL_LETTERS, DINOSAURS

    lines = [{"id": f"letters.{k}", "text": f"{v}!", "kind": "letter"}
             for k, v in LETTER_NAMES.items()]
    # Phrases spell the letter as its name too: a bare "A is for ..." reads as
    # the article "a".
    lines += [{"id": f"phrases.{k}",
               "text": f"{LETTER_NAMES[k]} is for {_spoken(animal)}!",
               "kind": "phrase"} for k, animal in ANIMAL_LETTERS.items()]
    animals = list(ANIMAL_LETTERS.values())
    animals += [d for d in DINOSAURS if d not in animals]
    lines += [{"id": f"animals.{a}", "text": f"{_spoken(a)}!", "kind": "animal"}
              for a in animals]
    lines += [{"id": f"numbers.{i}", "text": f"{w}...", "kind": "number"}
              for i, w in enumerate(_NUMBER_WORDS, 1)]
    lines += [{"id": f"endings.{i}", "text": f"{w}!", "kind": "ending"}
              for i, w in enumerate(_NUMBER_WORDS, 1)]
    lines += [{"id": f"praise.{k}", "text": t, "kind": "praise"}
              for k, t in PRAISE_LINES.items()]
    return lines
