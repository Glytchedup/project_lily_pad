import wave

from lilypad.audio.engine import ANIMAL_LETTERS, AudioEngine
from lilypad.audio.synth import (
    SAMPLE_RATE, baa, build_cues, celebration, count_note, moo, oink, quack,
)
from lilypad.input.mapper import classify
from lilypad.lighting.razer_hid import build_report


def test_build_cues_writes_valid_wavs(tmp_path):
    paths = build_cues(tmp_path)
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


def test_build_cues_deterministic(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    build_cues(a)
    build_cues(b)
    assert (a / "chime0.wav").read_bytes() == (b / "chime0.wav").read_bytes()


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
        assert abs(len(samples) / SAMPLE_RATE - 0.25) < 0.05


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
    build_cues(tmp_path)
    engine = AudioEngine(tmp_path, mute=False, autogen=False)
    try:
        for letter in ANIMAL_LETTERS:
            engine.on_action(classify(letter))
        for digit in "1234567890":
            engine.on_action(classify(digit))
        engine.on_celebration()
    finally:
        engine.close()


def test_engine_muted_is_silent_and_harmless(tmp_path):
    engine = AudioEngine(tmp_path, mute=True)
    engine.on_action(classify("C"))
    engine.on_celebration()
    assert engine._sounds == {}
    engine.close()


def test_animal_letters_cover_the_expected_cast():
    assert ANIMAL_LETTERS == {"C": "cow", "D": "duck", "P": "pig", "S": "sheep"}


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
