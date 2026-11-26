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
import time
from pathlib import Path

from ..effects.assets import asset_root
from ..input.mapper import Action
from .music import chord_for_keys, note_for_key
from .tracks import BeatClock, load_beat_map, load_bundled_tracks, reward_source_order
from .tunes import TUNE_NAMES
from .voice import NarratorPolicy, VoiceLoader

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

#: How long a "G is for Giraffe!" stays wanted after its letter press. The
#: policy releases it only once the channel has been idle 0.8 s with no letter
#: in the last 0.6 s, so this must outlast name + 0.8 s but not linger into
#: the next game.
PHRASE_WINDOW = 4.0
#: How long a praise or party line waits for a clip that is still sounding.
PRAISE_PATIENCE = 3.0

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
#: Key notes and voices duck under the reward track while it plays. The party
#: is the music's moment — the keys still have to answer, but quietly enough
#: that a child hears the song and not their own typing over it.
PARTY_DUCK = 0.25
#: The reward track plays louder than an ordinary background bed: `tune_volume`
#: is a level chosen to sit UNDER play, and the party is the opposite of that.
PARTY_VOLUME = 0.95

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
                 reward_presses: int = 50,
                 reward_window: float = 10.0,
                 reward_rule: str = "play",
                 reward_animals: int = 8,
                 reward_min_gap: float = 180.0,
                 reward_source: str = "folder_first",
                 bundled_tracks: bool = False,
                 party_show: bool = False,
                 party_volume: float = PARTY_VOLUME,
                 party_duck: float = PARTY_DUCK,
                 voice: str = "espeak",
                 phrases: bool = True,
                 count_aloud: bool = True) -> None:
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
        # "animals": a party is earned by meeting `reward_animals` different
        # animals, and at most one every `reward_min_gap` seconds. "play": the
        # seconds-or-presses meter. (The config default is "animals"; the bare
        # constructor keeps "play" so direct callers are unchanged.)
        self.reward_rule = reward_rule if reward_rule in ("animals", "play") else "play"
        self.reward_animals = max(1, int(reward_animals))
        self.reward_min_gap = max(0.0, float(reward_min_gap))
        self.reward_source = reward_source
        self.beat_clock: BeatClock | None = None
        self._beat_maps = {}
        self._clock_at = 0.0
        self._sync_bar = -2
        self.party_volume = max(0.0, min(1.0, party_volume))
        self.party_duck = max(0.0, min(1.0, party_duck))
        self.sounds_dir = Path(sounds_dir)
        # Narrator mode (see the narrator block below). "espeak" is today's
        # behaviour exactly: none of the narrator state is ever consulted.
        self.voice = voice if voice in ("narrator", "espeak") else "espeak"
        self.phrases = phrases
        self.count_aloud = count_aloud
        self._clock = time.monotonic    # tests inject a fake; ticks pass `now`
        self.narrator = NarratorPolicy(party_duck=self.party_duck)
        self._narrator = None           # the reserved mixer channel
        self._phrase_wanted: tuple[str, float] | None = None
        self._praise_wanted: tuple[str, float] | None = None
        self._count_total = 0
        assets = asset_root(kiosk=True)  # use the packaged audio manifests in both modes
        self.voice_loader = VoiceLoader(assets / "voice", self.sounds_dir / "voice")
        self.bundled_tracks = load_bundled_tracks(assets / "music")
        self._use_bundled = bundled_tracks
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
        self._animals_met: set[str] = set()
        # When the spacing clock started: the first event the engine sees
        # (~start-up; tick() runs every frame) and then each party's end.
        self._gap_origin: float | None = None
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
            if self.voice == "narrator":
                # Channel 0 is reserved so no cue's Sound.play() can land on
                # (and cut) the narrator, and the narrator never steals a
                # channel from the key notes.
                pygame.mixer.set_reserved(1)
                self._narrator = pygame.mixer.Channel(0)
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
            if self.tunes == "reward" and party_show:
                for path in self._playlist:
                    beatmap = load_beat_map(path)
                    if beatmap is not None:
                        self._beat_maps[path] = beatmap

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
        sources = reward_source_order(self.reward_source) if self.tunes == "reward" else ("folder",)
        for source in sources:
            if source == "folder" and self.background_folder.is_dir():
                try:
                    files = sorted(p for p in self.background_folder.iterdir()
                                   if p.is_file() and p.suffix.lower() in _MUSIC_EXTS)
                except OSError as exc:
                    log.warning("Cannot read music folder %s: %s", self.background_folder, exc)
                    continue
                if files:
                    random.shuffle(files)
                    return files, True
            if source == "bundled" and self._use_bundled and self.bundled_tracks:
                tracks = list(self.bundled_tracks)
                random.shuffle(tracks)
                return tracks, True  # finite file playlist, same transport as a parent track
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
        if self._gap_origin is None:
            self._gap_origin = now
        if self._party != "idle":
            return  # the party IS the reward; the meter restarts once it ends
        if self.reward_rule == "animals":
            # Presses and seconds earn nothing here; only note_animal() fills
            # the meter. A press after the gap is what releases a full one.
            self._maybe_start_animal_party(now)
            return
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

    def note_animal(self, name: str, now: float) -> None:
        """An animal was shown for a keypress (the effect engine's
        ``on_animal`` hook, which names the creature actually spawned — the
        F7-F12 dinosaur pick included). Only the "animals" rule uses it."""
        if (self.reward_rule != "animals" or self.tunes != "reward"
                or not self._enabled or self.mute):
            return
        if self._gap_origin is None:
            self._gap_origin = now
        if self._party != "idle":
            return  # animals met during a party don't bank the next one
        if name:
            self._animals_met.add(name)
        self._maybe_start_animal_party(now)

    def _maybe_start_animal_party(self, now: float) -> None:
        if (len(self._animals_met) >= self.reward_animals
                and now - self._gap_origin >= self.reward_min_gap):
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

    @property
    def reward_progress(self) -> float:
        """How full the meter is, 0..1 — what the on-screen party bar shows.

        "play" rule: either threshold can fire the party, so progress is
        whichever is further along. "animals" rule: distinct animals met over
        ``reward_animals`` (full while the spacing gap still holds the party
        back). Returns 0.0 when there is nothing to show: reward mode
        off, no audio, or a party already running (the party is its own
        feedback — a full bar sitting there during the fireworks would be
        telling the child something they can already see).
        """
        if self.tunes != "reward" or not self._enabled or self.mute:
            return 0.0
        if self._party != "idle":
            return 0.0
        if self.reward_rule == "animals":
            return min(1.0, len(self._animals_met) / self.reward_animals)
        return min(1.0, max(self._active_seconds / self.reward_seconds,
                            self._press_count / self.reward_presses))

    def _start_party(self, now: float) -> None:
        self._active_seconds = 0.0
        self._press_count = 0
        self._animals_met.clear()
        self._party = "starting"
        self._party_at = now
        self._party_pending = True
        self.narrate("party_start", now=now)
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
        self._gap_origin = now        # the spacing gap runs from the party's END
        self.beat_clock = None
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
            path = self._playlist[self._playlist_index]
        else:
            # Generated tunes are seamless infinite loops. The party has to
            # end when the track does, so this one plays exactly once.
            self._start_tune(loops=0)
            path = self._tune_path(self._tune_index)
        if beatmap := self._beat_maps.get(path):
            self.beat_clock = BeatClock(beatmap)
            self._clock_at = now
            self._sync_bar = -2
        # Both paths above load at `tune_volume` (the background-bed level).
        # Lift to the party level AFTER starting, so the reward track is the
        # loudest thing in the room rather than something under the keys.
        try:
            import pygame
            pygame.mixer.music.set_volume(self.party_volume)
        except Exception:                 # noqa: BLE001 — music is optional
            pass

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
            # Duck only now: the fanfare cue plays into three seconds of
            # silence, so ducking it under music that hasn't started yet
            # would quieten the one moment the whole reward is about.
            self._duck = self.party_duck
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
        self._tick_narrator(now)
        if self.tunes == "reward":
            if self._gap_origin is None:
                self._gap_origin = now
            self._tick_reward(now)
            clock = self.beat_clock
            if clock is not None:
                clock.advance(now - self._clock_at)
                self._clock_at = now
                if clock.bar > self._sync_bar:
                    bar = clock.bar
                    try:
                        import pygame
                        clock.resync(pygame.mixer.music.get_pos())
                    except pygame.error:
                        pass  # let the clock coast until the next bar
                    self._sync_bar = max(bar, clock.bar)
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
            if self._narrator is not None and self._narrate_letter(action.letter):
                pass
            elif self.key_notes:
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
            if self._narrator is not None and self.count_aloud:
                # The voice counts each object as it pops (see narrate_count).
                self.narrate_count(action.count)
            else:
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

    # ------------------------------------------------------------- narrator
    #
    # One mixer channel, one voice. Who may speak is decided by the pure
    # NarratorPolicy (audio/voice.py); this block only resolves clips, plays
    # them on the reserved channel, and keeps the two things that have to wait
    # for the policy: the "X is for Animal!" line and a praise line that
    # arrived while another clip was sounding. Nothing here ever blocks input.

    def _speak(self, group: str, sound, now: float) -> bool:
        """Ask the policy, then play on the narrator channel. True if playing."""
        duration = sound.get_length() if sound is not None else 0.0
        if not self.narrator.request(group, now=now, duration=duration):
            return False
        try:
            sound.set_volume(self.volume * self.narrator.gain(
                party_playing=self._party == "playing"))
            self._narrator.play(sound)   # replaces whatever was sounding
        except Exception as exc:         # noqa: BLE001 — speech is optional
            log.warning("narrator clip failed to play (%s)", exc)
            return False
        return True

    def _narrate_letter(self, letter: str) -> bool:
        """The letter name always pre-empts; its phrase is queued behind it."""
        now = self._clock()
        sound = self.voice_loader.get("letters", letter)
        spoken = self._speak("letters", sound, now)
        self._phrase_wanted = ((letter.upper(), now + PHRASE_WINDOW)
                               if self.phrases else None)
        return spoken

    def narrate_count(self, n: int, kind: str | None = None) -> None:
        """Count 1..n aloud on the visual pop schedule; the last is "N!".

        ``kind`` is the mini sprite kind. The ending lines are generic
        ("Five!") so it is unused today; it is accepted so the effect engine
        can pass it without a later signature change. Calling again replaces
        the schedule (same instant, so harmless after on_action's own call).
        """
        if self._narrator is None or self.mute or not self.count_aloud:
            return
        self._count_total = max(1, min(int(n), 10))
        self.narrator.schedule_count(self._count_total, now=self._clock())

    def narrate(self, event: str, now: float | None = None) -> bool:
        """Speak a praise line (``party_start``, ``alphabet_complete``, ...).

        There is no espeak stand-in for praise: a missing take is silence. A
        clip still sounding delays the line (up to PRAISE_PATIENCE) rather than
        dropping it, because the party starts on the very press that just
        started a letter name.
        """
        if self._narrator is None or self.mute or not self.phrases:
            return False
        sound = self.voice_loader.get_packaged("praise", event)
        if sound is None:
            return False
        now = self._clock() if now is None else now
        if self._speak("praise", sound, now):
            self._praise_wanted = None
            return True
        self._praise_wanted = (event, now + PRAISE_PATIENCE)
        return False

    def _tick_narrator(self, now: float) -> None:
        if self._narrator is None:
            return
        number = self.narrator.due_count(now)
        if number is not None and self.count_aloud:
            group = "endings" if number == self._count_total else "numbers"
            self._speak(group, self.voice_loader.get(group, number), now)
        if self._praise_wanted is not None:
            event, expires = self._praise_wanted
            sound = self.voice_loader.get_packaged("praise", event)
            if sound is None or now > expires:
                self._praise_wanted = None
            elif self._speak("praise", sound, now):
                self._praise_wanted = None
        if self._phrase_wanted is not None:
            letter, expires = self._phrase_wanted
            sound = self.voice_loader.get_packaged("phrases", letter)
            if sound is None or now > expires:
                self._phrase_wanted = None
            elif self._speak("phrases", sound, now):
                self._phrase_wanted = None

    def on_celebration(self) -> None:
        """Milestone mega-party fanfare; called by the effects engine's main
        loop. Falls back to the plain chord if the cue is missing."""
        self._play("celebration", "chord")

    def close(self) -> None:
        if self._enabled:
            try:
                import pygame
                try:
                    if self._narrator is not None:
                        self._narrator.stop()
                except Exception:             # noqa: BLE001
                    pass
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
        self._narrator = None
        self._phrase_wanted = self._praise_wanted = None
        self._party = "idle"
        self._duck = 1.0
