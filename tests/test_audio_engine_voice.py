"""The narrator on the audio engine: one channel, letters first, phrases when idle.

Time is injected (``engine._clock`` and the ``now`` handed to ``tick``), the
narrator channel is a recorder, and the clips are tiny synthetic WAVs, so
nothing here waits on a wall clock or needs real speech assets.
"""

import json
import wave
from pathlib import Path

import pygame
import pytest

from lilypad.audio.engine import AudioEngine
from lilypad.audio.music import note_for_key
from lilypad.audio.voice import (LETTER_NAMES, PRAISE_LINES, VoiceLoader,
                                 narrator_lines)
from lilypad.effects.animals import ANIMAL_LETTERS
from lilypad.effects.numbers import CountAlong
from lilypad.input.mapper import Action

RATE = 22050
LENGTHS = {"letters": 0.2, "phrases": 1.0, "numbers": 0.1, "endings": 0.4,
           "praise": 1.5}
LINES_FILE = Path("C:/Github_Repos/project_lily_pad/work/narrator_lines.json")


def write_clip(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * int(RATE * seconds))


class FakeChannel:
    """Records what the engine plays, and the volume it was played at."""

    def __init__(self):
        self.played = []
        self.stops = 0

    def play(self, sound):
        self.played.append((sound, sound.get_volume()))

    def stop(self):
        self.stops += 1


def letter(char):
    return Action(kind="letter", key=char, letter=char)


def number(count):
    return Action(kind="number", key=str(count), count=count)


class Rig:
    def __init__(self, tmp_path, *, manifest=None, espeak=(), **kwargs):
        packaged = tmp_path / "packaged"
        rows = manifest or {
            "letters": "ABG", "phrases": "AG", "numbers": "123",
            "endings": "3", "praise": ("party_start", "alphabet_complete"),
        }
        text = []
        for group, keys in rows.items():
            for key in keys:
                write_clip(packaged / f"{group}-{key}.wav", LENGTHS[group])
                text.append(f'[{group}.{key}]\nfile="{group}-{key}.wav"\n')
        packaged.mkdir(exist_ok=True)
        (packaged / "manifest.toml").write_text("".join(text), encoding="utf-8")
        for name in espeak:
            write_clip(tmp_path / "espeak" / f"{name}.wav", 0.05)

        kwargs.setdefault("voice", "narrator")
        self.engine = AudioEngine(tmp_path, autogen=False, **kwargs)
        if not self.engine._enabled:
            pytest.skip("no (dummy) audio device")
        self.engine.voice_loader = VoiceLoader(packaged, tmp_path / "espeak")
        self.now = 100.0
        self.engine._clock = lambda: self.now
        if self.engine.voice == "narrator":
            self.engine._narrator = self.channel = FakeChannel()
        self.plays = []
        self.engine._play = lambda *names: self.plays.append(names)
        self.names = {}
        for group, keys in rows.items():
            for key in keys:
                sound = self.engine.voice_loader.get(group, key)
                self.names[id(sound)] = f"{group}.{key}"
        for key in espeak:
            group = "letters" if key.isalpha() else "numbers"
            self.names[id(self.engine.voice_loader.get(group, key))] = f"espeak.{key}"

    def spoken(self):
        return [self.names.get(id(sound), "?") for sound, _ in self.channel.played]

    def at(self, now):
        """Move the clock and run the per-frame tick."""
        self.now = now
        self.engine.tick(now)

    def close(self):
        self.engine.close()


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(**kwargs):
        made.append(Rig(tmp_path, **kwargs))
        return made[-1]

    yield make
    for item in made:
        item.close()


# ------------------------------------------------------------------ letters

def test_letter_name_plays_on_the_narrator_channel_not_as_a_cue(rig):
    r = rig()
    r.engine.on_action(letter("G"))
    assert r.spoken() == ["letters.G"]
    assert not [p for p in r.plays if p[0].startswith("voice/")]
    assert ("squeak", "boing") in r.plays        # the animal call still layers on


def test_letter_always_preempts_whatever_the_narrator_is_saying(rig):
    r = rig()
    r.engine.narrate("alphabet_complete")        # a 1.5 s praise line
    assert r.spoken() == ["praise.alphabet_complete"]
    r.now += 0.1
    r.engine.on_action(letter("B"))
    r.now += 0.05
    r.engine.on_action(letter("A"))
    assert r.spoken() == ["praise.alphabet_complete", "letters.B", "letters.A"]


def test_phrase_waits_for_the_name_to_end_plus_eight_tenths(rig):
    r = rig()
    r.engine.on_action(letter("G"))               # name sounds 100.0 - 100.2
    for t in (100.0, 100.5, 100.99):
        r.at(t)
    assert r.spoken() == ["letters.G"]
    r.at(101.01)
    assert r.spoken() == ["letters.G", "phrases.G"]
    r.at(105.0)
    assert r.spoken() == ["letters.G", "phrases.G"]      # said once only


def test_phrase_expires_if_it_never_got_its_quiet_moment(rig):
    r = rig()
    r.engine.on_action(letter("G"))
    r.at(110.0)                                   # far past the window
    assert r.spoken() == ["letters.G"]


def test_mashing_at_ten_keys_a_second_speaks_only_names(rig):
    r = rig()
    for press in range(30):
        r.now = 100.0 + press / 10
        r.engine.on_action(letter("AG"[press % 2]))
        r.at(r.now + 0.05)
    assert len(r.spoken()) == 30
    assert all(name.startswith("letters.") for name in r.spoken())
    r.at(r.now + 1.2)                             # hands off the keyboard
    assert r.spoken()[-1] == "phrases.G"
    assert r.spoken().count("phrases.G") == 1


def test_phrases_toggle_off_leaves_only_names(rig):
    r = rig(phrases=False)
    r.engine.on_action(letter("G"))
    r.at(102.0)
    assert r.spoken() == ["letters.G"]
    assert r.engine.narrate("alphabet_complete") is False


def test_new_letter_replaces_the_phrase_still_waiting(rig):
    r = rig()
    r.engine.on_action(letter("G"))
    r.now += 0.3
    r.engine.on_action(letter("A"))
    r.at(r.now + 1.3)
    assert r.spoken() == ["letters.G", "letters.A", "phrases.A"]


# ---------------------------------------------------------------- fallbacks

def test_missing_narrator_letter_falls_back_to_the_espeak_file(rig):
    r = rig(espeak=["Z"])
    r.engine.on_action(letter("Z"))
    assert r.spoken() == ["espeak.Z"]


def test_letter_with_no_clip_anywhere_keeps_the_old_cue_path(rig):
    r = rig()
    r.engine.on_action(letter("Q"))
    assert r.spoken() == []
    assert ("voice/Q",) in r.plays


def test_missing_phrase_is_silent_not_a_second_letter_name(rig):
    r = rig()
    r.engine.on_action(letter("B"))               # no phrases.B packaged
    r.at(103.0)
    assert r.spoken() == ["letters.B"]


def test_missing_praise_is_silence(rig):
    r = rig()
    assert r.engine.narrate("great_job") is False
    assert r.spoken() == []


# ------------------------------------------------------------------- counts

def test_count_speaks_on_the_visual_pop_schedule_and_ends_with_the_ending(
        rig, monkeypatch):
    monkeypatch.setattr(CountAlong, "POP_INTERVAL", 0.375)   # no copied literal
    r = rig()
    r.engine.on_action(number(3))
    r.at(100.0)
    assert r.spoken() == ["numbers.1"]
    r.at(100.374)
    assert r.spoken() == ["numbers.1"]
    r.at(100.376)
    r.at(100.76)
    assert r.spoken() == ["numbers.1", "numbers.2", "endings.3"]
    assert not [p for p in r.plays if p[0] == "voice/3"]


def test_ending_cuts_off_a_number_that_is_still_sounding(rig, monkeypatch):
    monkeypatch.setattr(CountAlong, "POP_INTERVAL", 0.06)   # "one" lasts 0.1 s
    r = rig(manifest={"numbers": "12", "endings": "2"})
    r.engine.narrate_count(2, "frog")
    r.at(100.0)
    r.at(100.06)
    assert r.spoken() == ["numbers.1", "endings.2"]


def test_a_new_count_replaces_the_old_one(rig):
    r = rig(manifest={"numbers": "123", "endings": "13"})
    r.engine.narrate_count(3, "duck")
    r.at(100.0)
    r.engine.narrate_count(1, "star")
    r.at(100.0)
    r.at(101.0)
    assert r.spoken() == ["numbers.1", "endings.1"]


def test_a_letter_cancels_the_count(rig):
    r = rig()
    r.engine.narrate_count(3, "duck")
    r.at(100.0)
    r.engine.on_action(letter("A"))
    r.at(100.6)
    assert r.spoken() == ["numbers.1", "letters.A"]


def test_count_aloud_off_keeps_the_old_number_cue(rig):
    r = rig(count_aloud=False)
    r.engine.on_action(number(3))
    r.at(100.0)
    r.at(101.0)
    assert r.spoken() == []
    assert ("voice/3", "pop") in r.plays


# -------------------------------------------------------------------- party

def test_narrator_ducks_under_the_party_track(rig):
    r = rig(volume=0.8, party_duck=0.25)
    r.engine.on_action(letter("A"))
    r.engine._party = "playing"
    r.now += 1.0
    r.engine.on_action(letter("B"))
    r.engine._party = "idle"
    r.now += 1.0
    r.engine.on_action(letter("G"))
    volumes = [v for _, v in r.channel.played]
    assert volumes == pytest.approx([0.8, 0.2, 0.8], abs=0.01)


def test_party_start_line_waits_for_the_letter_that_started_it(rig):
    r = rig()
    r.engine.on_action(letter("A"))               # the press that earns the party
    r.engine._start_party(r.now)
    assert r.spoken() == ["letters.A"]            # the name is not cut short
    r.at(100.5)
    assert r.spoken() == ["letters.A", "praise.party_start"]
    assert r.engine.consume_party_started() is True


def test_party_start_line_speaks_at_once_on_an_idle_channel(rig):
    r = rig()
    r.engine._start_party(r.now)
    assert r.spoken() == ["praise.party_start"]


def test_praise_gives_up_after_its_patience(rig):
    r = rig()
    r.engine.on_action(letter("A"))
    r.engine.narrate("alphabet_complete")
    r.at(106.0)
    assert r.spoken() == ["letters.A"]


def test_muted_engine_has_no_narrator(tmp_path):
    engine = AudioEngine(tmp_path, mute=True, voice="narrator", autogen=False)
    assert engine._narrator is None
    assert engine.narrate("party_start") is False
    engine.narrate_count(3)
    engine.tick(1.0)
    engine.close()


# ------------------------------------------------------- espeak keeps today

def _drive(engine):
    calls = []
    engine._play = lambda *names: calls.append(names)
    engine.on_action(letter("G"))
    engine.on_action(number(3))
    engine.narrate_count(5, "frog")
    assert engine.narrate("party_start") is False
    for now in (1.0, 2.0, 3.0):
        engine.tick(now)
    engine._start_party(4.0)
    engine.tick(5.0)
    return calls


def test_espeak_mode_makes_exactly_todays_call_sequence(tmp_path):
    default = AudioEngine(tmp_path, autogen=False)
    explicit = AudioEngine(tmp_path, autogen=False, voice="espeak",
                           phrases=True, count_aloud=True)
    try:
        if not default._enabled:
            pytest.skip("no (dummy) audio device")
        note = (f"note_{note_for_key('G')}", "chime1")
        expected = [
            note, ("voice/G",), ("squeak", "boing"),
            ("voice/3", "pop"), ("count_2",),
        ]
        assert _drive(default) == expected
        assert _drive(explicit) == expected
        assert default._narrator is None and explicit._narrator is None
    finally:
        default.close()
        explicit.close()


def test_unknown_voice_value_means_espeak(tmp_path):
    engine = AudioEngine(tmp_path, autogen=False, voice="robot")
    assert engine.voice == "espeak" and engine._narrator is None
    engine.close()


# --------------------------------------------------------- the line catalogue

def test_every_letters_animal_has_a_phrase_line():
    ids = {line["id"] for line in narrator_lines()}
    for char, animal in ANIMAL_LETTERS.items():
        assert f"phrases.{char}" in ids, animal
        assert f"letters.{char}" in ids
        assert f"animals.{animal}" in ids


def test_catalogue_covers_everything_the_engine_requests():
    ids = {line["id"] for line in narrator_lines()}
    wanted = {f"letters.{c}" for c in LETTER_NAMES}
    wanted |= {f"{group}.{n}" for group in ("numbers", "endings") for n in range(1, 11)}
    wanted |= {"praise.party_start", "praise.alphabet_complete"}
    assert wanted <= ids


def test_catalogue_shape_and_size():
    lines = narrator_lines()
    assert len({line["id"] for line in lines}) == len(lines)
    kinds = {}
    for line in lines:
        assert set(line) == {"id", "text", "kind"} and line["text"].strip()
        kinds[line["kind"]] = kinds.get(line["kind"], 0) + 1
    assert kinds == {"letter": 26, "phrase": 26, "animal": 30, "number": 10,
                     "ending": 10, "praise": len(PRAISE_LINES)}
    assert 15 <= len(PRAISE_LINES) <= 25
    assert PRAISE_LINES["party_start"] == "You did it! Party time!"
    assert PRAISE_LINES["alphabet_complete"] == "You found ALL the animals!"
    assert any(line["text"] == "Double-you!" for line in lines)


@pytest.mark.skipif(not LINES_FILE.is_file(), reason="lead's work folder not present")
def test_work_folder_lines_file_matches_the_catalogue():
    assert json.loads(LINES_FILE.read_text(encoding="utf-8")) == narrator_lines()
