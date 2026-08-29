"""Audio engine: plays a cue for every action via pygame.mixer.

Every keypress is a musical note (see :mod:`lilypad.audio.music` for why they
can never clash), character cues layer on top, and instrumental tunes play in
the background through ``pygame.mixer.music``.

Degrades to silence — never crashes — if the mixer can't initialize (no
HDMI audio, dev box without an output). ``mute = true`` in config
short-circuits everything.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

from ..input.mapper import Action
from .music import chord_for_keys, note_for_key
from .tunes import TUNE_NAMES

log = logging.getLogger(__name__)

# The cast and its calls are imported from the visual layer so the two can
# never drift apart: adding an animal there adds its sound here, and a
# creature with no entry in ANIMAL_VOICES is simply a quiet one.
from ..effects.animals import ANIMAL_LETTERS, ANIMAL_VOICES  # noqa: E402

#: Action kinds that represent a fresh key going down, and so should sound a
#: note. Numbers are excluded because the counting ladder already gives them a
#: pitch; the synthetic kinds (chord, mash_*, hold_*) are excluded because the
#: press that produced them has already played its note.
_NOTE_KINDS = frozenset({"letter", "space", "arrow", "enter", "special", "sparkle"})

_TUNE_MODES = ("idle", "always", "off", "active", "reward")

#: Extensions scanned in the "active" mode's background_folder. WAV is
#: included so it also matches a folder of the generated tunes.
_MUSIC_EXTS = (".mp3", ".ogg", ".oga", ".flac", ".wav")

_PLAYLIST_FADE_IN_MS = 1200
_PLAYLIST_FADE_OUT_MS = 1500

#: "reward" mode. Fireworks play over silence for this long before the track
#: starts, so the celebration reads as *earning* the music rather than as a
#: jingle that happened to coincide with it.
PARTY_FANFARE_SECONDS = 3.0
#: Failsafe. Every mixer call in here swallows its exceptions (music is
#: optional, never fatal), so a mixer that dies mid-track would otherwise
#: leave the party — and the sleep/attract suppression that rides on it —
#: latched on forever.
PARTY_MAX_SECONDS = 600.0
#: Key notes and voices duck under the reward track while it plays.
PARTY_DUCK = 0.45

#: Relative level per cue family. Key notes sit *under* the spoken letter name
#: rather than masking it — the voice is the part with teaching value.
_GAINS = (
    ("note_", 0.55),
    ("chord", 0.70),
    ("count_", 0.80),
    ("chime", 0.60),
)


class AudioEngine:
    def __init__(self, sounds_dir: str | Path, *, mute: bool = False,
                 volume: float = 0.8, autogen: bool = True,
                 key_notes: bool = True, tunes: str = "idle",
                 tune_volume: float = 0.45,
                 background_folder: str | Path = "music",
                 fade_after: float = 30.0,
                 reward_seconds: float = 60.0,
                 reward_presses: int = 100,
                 reward_window: float = 10.0) -> None:
        self.mute = mute
        self.volume = volume
        self.key_notes = key_notes
        self.tunes = tunes if tunes in _TUNE_MODES else "idle"
        self.tune_volume = tune_volume
        self.background_folder = Path(background_folder)
        self.fade_after = max(0.0, fade_after)
        self.reward_seconds = max(1.0, reward_seconds)
        self.reward_presses = max(1, reward_presses)
        self.reward_window = max(0.5, reward_window)
        self.sounds_dir = Path(sounds_dir)
        self._sounds: dict[str, object] = {}
        self._chime_cycle = 0
        self._tune_index = -1
        self._tune_playing = False
        self._idle = False
        self._enabled = False
        # "active" mode — a shuffled playlist, distinct from the idle-tune
        # rotation above (see _playlist_* methods).
        self._playlist: list[Path] = []
        self._playlist_from_folder = False
        self._playlist_index = -1
        self._track_offset = 0.0
        self._track_loaded = False
        self._track_started_at: float | None = None
        self._music_on = False
        self._last_activity: float | None = None
        # "reward" mode — a play meter that buys a fireworks-then-dance-party
        # track (see the _tick_reward block).
        self._party = "idle"          # idle | starting | playing
        self._party_at = 0.0
        self._party_pending = False
        self._active_seconds = 0.0
        self._press_count = 0
        self._duck = 1.0
        if mute:
            log.info("audio: muted by config")
            if self.tunes == "reward":
                log.info("audio: muted, so no reward parties either")
            return
        try:
            import pygame
            pygame.mixer.init(frequency=22050, channels=2, buffer=512)
            pygame.mixer.set_num_channels(16)
            self._enabled = True
        except Exception as exc:              # noqa: BLE001 — silence, never crash
            log.warning("audio unavailable (%s) — running silent", exc)
            if self.tunes == "reward":
                log.warning("no audio device — reward parties are disabled")
            return
        if autogen:
            from .synth import build_cues, cues_stale
            if cues_stale(self.sounds_dir):
                log.info("audio: (re)generating cues into %s", self.sounds_dir)
                try:
                    build_cues(self.sounds_dir)
                except OSError as exc:
                    # Read-only sounds dir — /opt under the Pi's overlayfs, for
                    # instance. Keep whatever cues are there over crashing.
                    log.warning("audio: cue regeneration failed (%s)", exc)
        if self.tunes == "always":
            self._start_tune()
        elif self.tunes in ("active", "reward"):
            self._playlist, self._playlist_from_folder = self._build_playlist()

    # ------------------------------------------------------------- cue play

    def _gain(self, name: str) -> float:
        for prefix, gain in _GAINS:
            if name.startswith(prefix):
                return gain
        return 1.0

    def _get(self, name: str):
        if not self._enabled:
            return None
        if name not in self._sounds:
            import pygame
            path = self.sounds_dir / f"{name}.wav"
            if not path.is_file():
                self._sounds[name] = None
            else:
                sound = pygame.mixer.Sound(str(path))
                sound.set_volume(self.volume * self._gain(name))
                self._sounds[name] = sound
        return self._sounds[name]

    def _play(self, *names: str) -> None:
        """Play the first available sound from ``names``."""
        if not self._enabled or self.mute:
            return
        for name in names:
            sound = self._get(name)
            if sound is not None:
                # Volume is set per play, not once at load: the reward party
                # ducks every cue under the music, and _get caches the Sound
                # object, so a level baked in at load time could never move.
                sound.set_volume(self.volume * self._gain(name) * self._duck)
                sound.play()
                return

    def _next_chime(self) -> str:
        self._chime_cycle = (self._chime_cycle + 1) % 6
        return f"chime{self._chime_cycle}"

    def _play_note(self, key: str) -> None:
        """The note this key sits on. Falls back to a chime for a cue set
        generated before the musical layer existed."""
        self._play(f"note_{note_for_key(key)}", self._next_chime())

    # ---------------------------------------------------------- background

    def _tune_path(self, index: int) -> Path:
        return self.sounds_dir / f"tune_{TUNE_NAMES[index]}.wav"

    def _start_tune(self, loops: int = -1) -> None:
        """Load and play the next tune. Silent no-op if none are on disk.

        Loops forever by default (idle/always/active are background beds).
        The reward party passes ``loops=0``: the party ends when the track
        does, so it must actually end.
        """
        if not self._enabled or self.mute or self.tunes == "off":
            return
        for _ in range(len(TUNE_NAMES)):
            self._tune_index = (self._tune_index + 1) % len(TUNE_NAMES)
            path = self._tune_path(self._tune_index)
            if not path.is_file():
                continue
            try:
                import pygame
                pygame.mixer.music.load(str(path))
                pygame.mixer.music.set_volume(self.tune_volume)
                pygame.mixer.music.play(loops=loops, fade_ms=1200)
                self._tune_playing = True
            except Exception as exc:          # noqa: BLE001 — music is optional
                log.warning("tune %s failed to play (%s)", path.name, exc)
            return

    def _stop_tune(self) -> None:
        if not self._tune_playing:
            return
        self._tune_playing = False
        try:
            import pygame
            pygame.mixer.music.fadeout(700)
        except Exception:                     # noqa: BLE001
            pass

    def set_idle(self, idle: bool) -> None:
        """Called every frame with whether attract mode is running.

        In the default ``idle`` mode the tunes are the soundtrack to an empty
        room: they fade in when the child wanders off and fade out the instant
        a key is touched, so playing is never competing with backing music.
        """
        if idle == self._idle:
            return
        self._idle = idle
        if self.tunes != "idle":
            return
        if idle:
            self._start_tune()
        else:
            self._stop_tune()

    # ------------------------------------------------ background (active mode)
    #
    # "active" is the mirror image of "idle": background music plays while
    # the child is at the keyboard and fades out once they wander off,
    # rather than the other way round. It draws from background_folder (a
    # personal, git-ignored library of real songs) and, only when that
    # folder is empty or missing, falls back to looping the generated tunes
    # via the exact _start_tune/_stop_tune machinery above — so a stock
    # checkout with no personal music still plays something.

    def _build_playlist(self) -> tuple[list[Path], bool]:
        files: list[Path] = []
        if self.background_folder.is_dir():
            files = sorted(
                p for p in self.background_folder.iterdir()
                if p.is_file() and p.suffix.lower() in _MUSIC_EXTS
            )
        if files:
            random.shuffle(files)
            return files, True
        fallback = [self._tune_path(i) for i in range(len(TUNE_NAMES))]
        fallback = [p for p in fallback if p.is_file()]
        random.shuffle(fallback)
        return fallback, False

    def _playlist_advance(self, now: float) -> None:
        """Load and play the next shuffled track from the top."""
        if not self._playlist:
            return
        self._playlist_index = (self._playlist_index + 1) % len(self._playlist)
        path = self._playlist[self._playlist_index]
        self._track_offset = 0.0
        self._track_loaded = True
        self._track_started_at = now
        try:
            import pygame
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(self.tune_volume)
            pygame.mixer.music.play(loops=0, fade_ms=_PLAYLIST_FADE_IN_MS)
        except Exception as exc:              # noqa: BLE001 — music is optional
            log.warning("background track %s failed to play (%s)", path.name, exc)

    def _playlist_play(self, now: float) -> None:
        if self._music_on or not self._playlist:
            return
        self._music_on = True
        if not self._playlist_from_folder:
            # Generated tunes are seamless infinite loops — reuse the idle
            # rotation as-is, there's no "partway through" to resume.
            self._start_tune()
            return
        if not self._track_loaded:
            self._playlist_advance(now)
            return
        # Resume the same track where the fade caught it.
        path = self._playlist[self._playlist_index]
        self._track_started_at = now
        try:
            import pygame
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(self.tune_volume)
            pygame.mixer.music.play(loops=0, start=self._track_offset,
                                    fade_ms=_PLAYLIST_FADE_IN_MS)
        except Exception as exc:              # noqa: BLE001
            # SDL_mixer doesn't support seeking every format (WAV, notably)
            # — rather than silently stay "on" but mute, fall back to
            # restarting this track from the top.
            log.info("background track seek unsupported (%s) — restarting it", exc)
            self._track_offset = 0.0
            try:
                import pygame
                pygame.mixer.music.play(loops=0, fade_ms=_PLAYLIST_FADE_IN_MS)
            except Exception as exc2:          # noqa: BLE001
                log.warning("background track resume failed (%s)", exc2)

    def _playlist_pause(self, now: float) -> None:
        if not self._music_on:
            return
        self._music_on = False
        if not self._playlist_from_folder:
            self._stop_tune()
            return
        if self._track_started_at is not None:
            self._track_offset += now - self._track_started_at
            self._track_started_at = None
        try:
            import pygame
            pygame.mixer.music.fadeout(_PLAYLIST_FADE_OUT_MS)
        except Exception:                     # noqa: BLE001
            pass

    def _playlist_advance_if_finished(self, now: float) -> None:
        """A finite track (real song) that finished on its own moves on to
        the next shuffled pick. Generated tunes loop forever, so this is a
        no-op for the fallback playlist."""
        if not self._music_on or not self._playlist_from_folder:
            return
        try:
            import pygame
            if not pygame.mixer.music.get_busy():
                self._playlist_advance(now)
        except Exception:                     # noqa: BLE001
            pass

    def notify_activity(self, now: float) -> None:
        """Called on every raw keypress — the same signal that wakes the
        screen. Only meaningful in the "active" and "reward" tune modes."""
        last, self._last_activity = self._last_activity, now
        if self.tunes != "reward" or not self._enabled or self.mute:
            return
        if self._party != "idle":
            return  # the party IS the reward; the meter restarts once it ends
        # Engaged play, not wall clock: a gap longer than reward_window means
        # the child wandered off, and that time must not count toward the next
        # track. Progress itself survives the gap — a toddler who comes back
        # picks up where they left off rather than starting from zero.
        if last is not None and now - last <= self.reward_window:
            self._active_seconds += now - last
        self._press_count += 1
        if (self._active_seconds >= self.reward_seconds
                or self._press_count >= self.reward_presses):
            self._start_party(now)

    # ----------------------------------------------- background (reward mode)
    #
    # "reward" turns the music into something the child earns. Play quietly
    # (key notes only) until the meter fills — a minute of engaged play, or a
    # hundred presses, whichever lands first — then: fireworks over silence,
    # then a whole track while the frog throws a dance party. When the track
    # ends the party ends, the meter is empty, and the next one has to be
    # earned again.

    @property
    def party_active(self) -> bool:
        """True from the fireworks until the reward track finishes."""
        return self._party != "idle"

    def _start_party(self, now: float) -> None:
        self._active_seconds = 0.0
        self._press_count = 0
        self._party = "starting"
        self._party_at = now
        self._party_pending = True
        self._duck = PARTY_DUCK
        log.info("reward earned — fireworks, then the dance party track")

    def consume_party_started(self) -> bool:
        """Main loop polls this to kick off the visual party (mirrors the
        effect engine's ``consume_celebration``)."""
        pending, self._party_pending = self._party_pending, False
        return pending

    def _end_party(self, now: float) -> None:
        if self._party == "idle":
            return
        self._party = "idle"
        self._duck = 1.0
        # The party is not an idle gap: without this the first press after it
        # would be measured against a press from minutes ago.
        self._last_activity = now
        if self._playlist_from_folder:
            try:
                import pygame
                pygame.mixer.music.fadeout(_PLAYLIST_FADE_OUT_MS)
            except Exception:             # noqa: BLE001
                pass
        else:
            self._stop_tune()

    def _party_track(self, now: float) -> None:
        if not self._playlist:
            return
        if self._playlist_from_folder:
            self._playlist_advance(now)   # already finite (loops=0)
        else:
            # Generated tunes are seamless infinite loops. The party has to
            # end when the track does, so this one plays exactly once.
            self._start_tune(loops=0)

    def _music_playing(self) -> bool:
        try:
            import pygame
            return bool(pygame.mixer.music.get_busy())
        except Exception:                 # noqa: BLE001
            return False

    def _tick_reward(self, now: float) -> None:
        if self._party == "starting":
            if now - self._party_at < PARTY_FANFARE_SECONDS:
                return
            self._party = "playing"
            self._party_at = now
            self._party_track(now)
            if not self._music_playing():
                # Nothing playable on disk. End it rather than leaving the
                # frog dancing in silence to a track that never started.
                log.info("no reward track available — ending the party early")
                self._end_party(now)
            return
        if self._party == "playing":
            # get_busy() is only meaningful HERE: during "starting" the mixer
            # is legitimately idle for the fanfare gap, and reading that as
            # "track finished" would end every party the instant it began.
            if not self._music_playing():
                log.info("reward track finished — dance party over")
                self._end_party(now)
            elif now - self._party_at >= PARTY_MAX_SECONDS:
                log.warning("reward party hit the %.0fs cap — ending it",
                            PARTY_MAX_SECONDS)
                self._end_party(now)

    def tick(self, now: float) -> None:
        """Call once per frame. Drives the "active" mode's fade in/out and
        playlist advance, and the "reward" mode's party state machine; a
        no-op in every other tune mode."""
        if not self._enabled or self.mute:
            return
        if self.tunes == "reward":
            self._tick_reward(now)
            return
        if self.tunes != "active":
            return
        if self._last_activity is None:
            return  # never touched the keyboard yet — stay silent
        if now - self._last_activity < self.fade_after:
            self._playlist_play(now)
        else:
            self._playlist_pause(now)
        self._playlist_advance_if_finished(now)

    # -------------------------------------------------------------- actions

    def on_action(self, action: Action) -> None:
        kind = action.kind
        if self.key_notes and kind in _NOTE_KINDS and action.key:
            self._play_note(action.key)

        if kind == "letter":
            # The note above carries the sound; the voice carries the lesson.
            if self.key_notes:
                self._play(f"voice/{action.letter}")
            else:
                self._play(f"voice/{action.letter}", self._next_chime())
            animal = ANIMAL_LETTERS.get(action.letter.upper())
            cue = ANIMAL_VOICES.get(animal) if animal else None
            if cue is not None:
                # Animal call layers *on top of* the letter name, never replaces it.
                # Fallback for a pre-upgrade sounds dir that lacks the cue.
                self._play(cue, "boing")
        elif kind == "number":
            self._play(f"voice/{action.count}", "pop")
            # One cue per press: the marimba note for the count, so the pitch
            # rises with the number. (The effect layer paces the visual pops at
            # 0.28 s.) No fallback here: the voice line above already falls back
            # to "pop" on a pre-upgrade sounds dir, and a second fallback made
            # the same cue fire twice at double amplitude.
            count = max(1, min(action.count, 10))
            self._play(f"count_{count - 1}")
        elif kind == "space":
            self._play("whoosh")
        elif kind == "enter":
            self._play("boom")
        elif kind == "arrow":
            self._play("boing")
        elif kind == "chord":
            # Two keys within the chord window: the diatonic triad their lower
            # note roots, swelling under the two notes already sounding.
            self._play(f"chord_{chord_for_keys(action.keys)}", "chord")
        elif kind == "mash_start":
            self._play("chord_mash", "chord")
        elif kind == "special":
            if action.letter == "dino":
                # One roar for every dinosaur: the effect layer picks which one
                # shows up, and a second random pick here could easily play a
                # pterodactyl's screech over a stomping triceratops.
                self._play("roar", "boom")
            elif action.letter == "drum":
                self._play("drum")
            elif action.letter == "vacuum":
                self._play("whoosh")
            elif not self.key_notes:
                # With notes off there'd be nothing at all for the rest.
                self._play(self._next_chime())
        elif kind == "sparkle":
            self._play("sparkle")

    def on_celebration(self) -> None:
        """Milestone mega-party fanfare; called by the effects engine's main
        loop. Falls back to the plain chord if the cue is missing."""
        self._play("celebration", "chord")

    def close(self) -> None:
        if self._enabled:
            try:
                import pygame
                try:
                    pygame.mixer.music.stop()
                except Exception:             # noqa: BLE001 — music is optional
                    pass
                pygame.mixer.quit()
            except Exception:                 # noqa: BLE001
                pass
            self._enabled = False
        self._tune_playing = False
        self._music_on = False
        self._party = "idle"
        self._duck = 1.0
