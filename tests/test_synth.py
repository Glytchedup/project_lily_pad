import wave

import pytest

from lilypad.audio.engine import ANIMAL_LETTERS, AudioEngine
from lilypad.audio.music import CHORD_NAMES, NOTE_MIDIS
from lilypad.audio.synth import (
    BELL, SAMPLE_RATE, baa, boom, build_cues, celebration, chord_cue,
    count_note, cues_stale, drum, mash_chord_cue, moo, note_cue, oink, quack,
    render_note, whoosh,
)
from lilypad.audio.tunes import TUNE_NAMES
from lilypad.input.mapper import classify
from lilypad.lighting.razer_hid import build_report


def test_build_cues_writes_valid_wavs(tmp_path):
    # Tunes are ~20 s each and by far the slowest part of a build; they get
    # their own test below.
    paths = build_cues(tmp_path, tunes=False)
    names = {p.stem for p in paths}
    assert {"pop", "whoosh", "boom", "sparkle", "chord", "drum", "boing"} <= names
    assert {"moo", "quack", "oink", "baa", "celebration"} <= names
    assert {f"count_{i}" for i in range(10)} <= names
    assert sum(1 for n in names if n.startswith("chime")) == 6
    for p in paths:
        with wave.open(str(p), "rb") as wf:
            assert wf.getframerate() == SAMPLE_RATE
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getnframes() > 500  # not empty


def test_build_cues_writes_a_note_for_every_pitch_and_every_chord(tmp_path):
    names = {p.stem for p in build_cues(tmp_path, tunes=False)}
    assert {f"note_{m}" for m in NOTE_MIDIS} <= names
    assert {f"chord_{c}" for c in CHORD_NAMES} <= names
    assert "chord_mash" in names


def test_build_cues_stamps_version_and_staleness_detects_it(tmp_path):
    from lilypad.audio.synth import CUE_VERSION, cues_stale
    assert cues_stale(tmp_path)                       # empty dir → stale
    build_cues(tmp_path)
    assert (tmp_path / "cues.version").read_text() == str(CUE_VERSION)
    assert not cues_stale(tmp_path)                   # freshly built → current
    (tmp_path / "cues.version").write_text("0")
    assert cues_stale(tmp_path)                       # old version → stale
    (tmp_path / "cues.version").unlink()
    assert cues_stale(tmp_path)                       # pre-versioning dir → stale


def test_a_cue_set_without_tunes_counts_as_stale(tmp_path):
    # Otherwise a fast test-shaped build would mark a dir "current" while the
    # background music is missing from it.
    build_cues(tmp_path, tunes=False)
    assert cues_stale(tmp_path)


def test_softening_only_touches_the_character_cues(tmp_path):
    """The musical cues must keep their brightness — Voice already shapes it."""
    from lilypad.audio.synth import _SOFTENED
    assert "whoosh" in _SOFTENED and "moo" in _SOFTENED
    for name in _SOFTENED:
        assert not name.startswith(("note_", "chord", "count_", "tune_"))
    assert not any(f"note_{m}" in _SOFTENED for m in NOTE_MIDIS)
    assert "celebration" not in _SOFTENED


def test_softened_character_cues_stay_audible_and_quieter_than_full_scale():
    from lilypad.audio.synth import _soften
    for raw in (whoosh(), boom(), drum(), moo(), quack(), baa()):
        soft = _soften(raw)
        peak = max(abs(s) for s in soft)
        assert 0.15 < peak <= 0.8, "audible, but with headroom under the notes"


def test_build_cues_deterministic(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    build_cues(a, tunes=False)
    build_cues(b, tunes=False)
    assert (a / "chime0.wav").read_bytes() == (b / "chime0.wav").read_bytes()


def test_build_cues_writes_the_tunes(tmp_path):
    names = {p.stem for p in build_cues(tmp_path)}
    assert {f"tune_{n}" for n in TUNE_NAMES} <= names
    # Four distinct tunes, not the same render four times.
    blobs = {(tmp_path / f"tune_{n}.wav").read_bytes() for n in TUNE_NAMES}
    assert len(blobs) == len(TUNE_NAMES)


# --------------------------------------------------------------- note voices

def _rms(samples):
    return (sum(s * s for s in samples) / max(1, len(samples))) ** 0.5


def test_note_cues_exist_for_every_mapped_pitch_and_stay_in_range():
    for midi in NOTE_MIDIS:
        samples = note_cue(midi)
        assert samples
        assert all(-1.0 <= s <= 1.0 for s in samples)
        assert max(abs(s) for s in samples) > 0.5      # audible


def test_a_note_decays_like_a_struck_instrument():
    # The single biggest thing separating "note" from "beep": it has to die
    # away, not hold flat until it is cut off.
    samples = render_note(64, 1.1, BELL)
    quarter = len(samples) // 4
    assert _rms(samples[-quarter:]) < 0.2 * _rms(samples[:quarter])


def test_note_pitch_rises_with_midi_number():
    def crossings(s):
        return sum(1 for a, b in zip(s, s[1:]) if (a < 0) != (b < 0))

    counts = [crossings(render_note(m, 0.4, BELL)) for m in (48, 60, 72, 84)]
    assert counts == sorted(counts)
    assert all(b > a for a, b in zip(counts, counts[1:]))


def test_chord_cues_are_audible_and_do_not_clip():
    for name in CHORD_NAMES:
        samples = chord_cue(name)
        assert all(-1.0 <= s <= 1.0 for s in samples)
        assert max(abs(s) for s in samples) > 0.5
    mash = mash_chord_cue()
    assert all(-1.0 <= s <= 1.0 for s in mash)
    assert len(mash) / SAMPLE_RATE > 2.0           # a swell, not a stab


# --------------------------------------------------- animal + counting cues

def _zero_crossings(samples):
    return sum(1 for a, b in zip(samples, samples[1:]) if (a < 0) != (b < 0))


def test_animal_cues_are_in_range_and_roughly_the_right_length():
    # (cue, expected seconds) — durations are the caricature, so they matter.
    for samples, seconds in ((moo(), 0.9), (quack(), 0.5),
                             (oink(), 0.5), (baa(), 0.8)):
        assert samples
        assert all(-1.0 <= s <= 1.0 for s in samples)
        assert max(abs(s) for s in samples) > 0.2      # audible, not a whisper
        assert abs(len(samples) / SAMPLE_RATE - seconds) < 0.15


def test_celebration_is_a_long_loud_fanfare():
    samples = celebration()
    assert all(-1.0 <= s <= 1.0 for s in samples)
    assert 1.5 < len(samples) / SAMPLE_RATE < 2.5
    assert max(abs(s) for s in samples) > 0.5


def test_count_notes_are_in_range():
    for i in range(10):
        samples = count_note(i)
        assert samples
        assert all(-1.0 <= s <= 1.0 for s in samples)
        # 0.75 s of marimba plus the reverb tail; all ten are the same length,
        # which is what makes the zero-crossing pitch test below valid.
        assert abs(len(samples) / SAMPLE_RATE - 0.95) < 0.1
    assert len({len(count_note(i)) for i in range(10)}) == 1


def test_count_note_pitch_rises_with_index():
    # All ten notes are the same length, so zero-crossing count tracks pitch.
    crossings = [_zero_crossings(count_note(i)) for i in range(10)]
    assert crossings == sorted(crossings)
    assert all(b > a for a, b in zip(crossings, crossings[1:]))
    assert crossings[-1] > 2 * crossings[0]           # spans an octave+


def test_count_note_clamps_out_of_range_index():
    assert count_note(99) == count_note(9)
    assert count_note(-1) == count_note(0)


# --------------------------------------------------- audio engine (silent paths)

def test_engine_survives_missing_sounds_dir(tmp_path):
    """No cues on disk at all — every action must degrade to silence."""
    engine = AudioEngine(tmp_path / "nope", mute=False, autogen=False)
    try:
        for name in ("C", "D", "P", "S", "Q", "5", "0", "SPACE", "ENTER"):
            engine.on_action(classify(name))
        engine.on_celebration()
    finally:
        engine.close()


def test_engine_plays_animal_and_count_cues(tmp_path):
    """With real cues present, animal letters and digits still can't crash —
    the mixer itself may be unavailable headless, which is a silent path too."""
    build_cues(tmp_path, tunes=False)
    engine = AudioEngine(tmp_path, mute=False, autogen=False)
    try:
        for letter in ANIMAL_LETTERS:
            engine.on_action(classify(letter))
        for digit in "1234567890":
            engine.on_action(classify(digit))
        engine.on_celebration()
    finally:
        engine.close()


# ------------------------------------------------ audio engine (cue choice)

def _recorder(tmp_path, **kwargs):
    """An engine whose ``_play`` records requests instead of making sound, so
    the *choice* of cue can be asserted without a working mixer."""
    engine = AudioEngine(tmp_path, mute=False, autogen=False, **kwargs)
    played: list[tuple[str, ...]] = []
    engine._play = lambda *names: played.append(names)
    return engine, played


def _first_choices(played):
    return [names[0] for names in played]


def test_a_letter_plays_its_note_and_still_says_its_name(tmp_path):
    engine, played = _recorder(tmp_path)
    engine.on_action(classify("A"))
    # A sits on E4 (see test_music); the note leads, the letter name follows,
    # and A's animal (the alligator) growls on top of both.
    assert _first_choices(played) == ["note_64", "voice/A", "growl"]


def test_a_quiet_animal_adds_no_cue(tmp_path):
    """Every letter has a creature, but a creature need not have a voice."""
    from lilypad.effects.animals import ANIMAL_LETTERS, ANIMAL_VOICES
    silent = [k for k, v in ANIMAL_LETTERS.items() if v not in ANIMAL_VOICES]
    if not silent:
        pytest.skip("every animal currently has a call")
    engine, played = _recorder(tmp_path)
    engine.on_action(classify(silent[0]))
    assert len(_first_choices(played)) == 2      # note + spoken name only


def test_the_dinosaur_key_roars(tmp_path):
    engine, played = _recorder(tmp_path)
    engine.on_action(classify("F9"))
    # One roar for every dinosaur: the effects layer picks which one appears,
    # so a second random pick here could play the wrong animal's call.
    assert "roar" in _first_choices(played)


def test_letter_note_follows_the_keyboard_layout(tmp_path):
    engine, played = _recorder(tmp_path)
    for key in "ZAQ":
        engine.on_action(classify(key))
    notes = [int(n.removeprefix("note_")) for n in _first_choices(played)
             if n.startswith("note_")]
    assert notes == sorted(notes) and len(set(notes)) == 3


def test_two_keys_at_once_play_a_diatonic_triad(tmp_path):
    from lilypad.input.mapper import Action
    engine, played = _recorder(tmp_path)
    engine.on_action(Action(kind="chord", key="S", keys=("A", "S")))
    assert _first_choices(played) == ["chord_Em"]
    # The plain legacy stab remains as the fallback for an old cue set.
    assert played[0][-1] == "chord"


def test_mash_storm_gets_the_open_swell(tmp_path):
    from lilypad.input.mapper import Action
    engine, played = _recorder(tmp_path)
    engine.on_action(Action(kind="mash_start"))
    assert _first_choices(played) == ["chord_mash"]


def test_numbers_use_the_count_ladder_not_the_key_note(tmp_path):
    engine, played = _recorder(tmp_path)
    engine.on_action(classify("3"))
    chosen = _first_choices(played)
    assert chosen == ["voice/3", "count_2"]
    assert not any(n.startswith("note_") for n in chosen)


def test_key_notes_can_be_switched_off(tmp_path):
    engine, played = _recorder(tmp_path, key_notes=False)
    for name in ("A", "SPACE", "ESC", "F1"):
        engine.on_action(classify(name))
    assert not any(n.startswith("note_") for names in played for n in names)
    # ...and nothing that used to make a sound falls silent.
    assert all(names for names in played)


def test_every_key_makes_some_sound(tmp_path):
    engine, played = _recorder(tmp_path)
    for name in ("A", "5", "SPACE", "ENTER", "LEFT", "ESC", "F7", "PRINTSCREEN"):
        before = len(played)
        engine.on_action(classify(name))
        assert len(played) > before, name


# ------------------------------------------------- audio engine (background)

def test_set_idle_starts_and_stops_the_tune_once_per_transition(tmp_path):
    # Explicit: "off" is the default now, so idle mode has to be asked for.
    engine = AudioEngine(tmp_path, mute=False, autogen=False, tunes="idle")
    calls: list[str] = []
    engine._start_tune = lambda: calls.append("start")
    engine._stop_tune = lambda: calls.append("stop")
    engine.set_idle(True)
    engine.set_idle(True)       # still idle — must not restart the tune
    engine.set_idle(False)
    engine.set_idle(False)
    assert calls == ["start", "stop"]
    engine.close()


@pytest.mark.parametrize("mode", ["off", "always"])
def test_non_idle_tune_modes_ignore_idle_transitions(tmp_path, mode):
    engine = AudioEngine(tmp_path, mute=False, autogen=False, tunes=mode)
    calls: list[str] = []
    engine._start_tune = lambda: calls.append("start")
    engine._stop_tune = lambda: calls.append("stop")
    engine.set_idle(True)
    engine.set_idle(False)
    assert calls == []
    engine.close()


def test_missing_tunes_on_disk_are_silent_not_fatal(tmp_path):
    engine = AudioEngine(tmp_path, mute=False, autogen=False)
    try:
        engine.set_idle(True)
        assert engine._tune_playing is False
        engine.set_idle(False)
    finally:
        engine.close()


def test_muted_engine_never_starts_a_tune(tmp_path):
    engine = AudioEngine(tmp_path, mute=True, tunes="always")
    engine.set_idle(True)
    assert engine._tune_playing is False
    engine.close()


def test_engine_muted_is_silent_and_harmless(tmp_path):
    engine = AudioEngine(tmp_path, mute=True)
    engine.on_action(classify("C"))
    engine.on_celebration()
    assert engine._sounds == {}
    engine.close()


def test_animal_letters_cover_the_expected_cast():
    """Every letter summons a creature — that is the product promise."""
    import inspect
    import string

    from lilypad.audio.synth import build_cues
    from lilypad.effects.animals import ANIMAL_VOICES

    assert set(ANIMAL_LETTERS) == set(string.ascii_uppercase)
    # The four originals must survive any recasting.
    for letter, name in (("C", "cow"), ("D", "duck"), ("P", "pig"), ("S", "sheep")):
        assert ANIMAL_LETTERS[letter] == name
    # Every call a creature claims has to be one this module actually builds,
    # or that animal is silent on the device and nowhere else.
    src = inspect.getsource(build_cues)
    for cue in set(ANIMAL_VOICES.values()):
        assert '"%s": %s()' % (cue, cue) in src, f"no generator wired for {cue}"


# --------------------------------------------------- razer report (no USB)

def test_razer_report_layout_and_crc():
    args = bytes((0xFF, 0x02, 0x00, 0x15)) + bytes(66)
    report = build_report(0x03, 0x0B, args)
    assert len(report) == 90
    assert report[0] == 0x00            # status
    assert report[1] == 0xFF            # transaction id
    assert report[5] == len(args)       # data_size
    assert report[6] == 0x03            # command class
    assert report[7] == 0x0B            # command id
    crc = 0
    for b in report[2:88]:
        crc ^= b
    assert report[88] == crc
    assert report[89] == 0x00


def test_razer_report_rejects_oversized_args():
    import pytest
    with pytest.raises(ValueError):
        build_report(0x03, 0x0B, bytes(81))
