import wave

from lilypad.audio.synth import SAMPLE_RATE, build_cues
from lilypad.lighting.razer_hid import build_report


def test_build_cues_writes_valid_wavs(tmp_path):
    paths = build_cues(tmp_path)
    names = {p.stem for p in paths}
    assert {"pop", "whoosh", "boom", "sparkle", "chord", "drum", "boing"} <= names
    assert sum(1 for n in names if n.startswith("chime")) == 6
    for p in paths:
        with wave.open(str(p), "rb") as wf:
            assert wf.getframerate() == SAMPLE_RATE
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getnframes() > 500  # not empty


def test_build_cues_deterministic(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    build_cues(a)
    build_cues(b)
    assert (a / "chime0.wav").read_bytes() == (b / "chime0.wav").read_bytes()


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
