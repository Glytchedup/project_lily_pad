import json
import wave

import pytest

np = pytest.importorskip("numpy")
from tools.art import beatmap, tts


def click_track(path, bpm=120, offset=.17):
    rate = 16000
    audio = np.zeros(rate*9, dtype=np.float32)
    click = np.hanning(200) * np.sin(2*np.pi*900*np.arange(200)/rate)
    for at in np.arange(offset, 8.9, 60/bpm):
        start = round(at*rate)
        audio[start:start+len(click)] += click
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", ""))
        out.writeframes((audio*32767).astype("<i2").tobytes())


@pytest.mark.parametrize("backend", ["auto", "numpy"])
def test_folder_recovers_tempo_phase_and_bar_grid(tmp_path, backend):
    track = tmp_path / "click.wav"
    click_track(track)
    (tmp_path/"ignore.txt").touch()
    beatmap.process(tmp_path, backend=backend)
    data = json.loads((tmp_path/"click.wav.beats.json").read_text())
    assert set(data) == {"bpm","beats","downbeats","offset","drops"}
    assert abs(data["bpm"]-120) <= 1
    assert data["offset"] == pytest.approx(.17, abs=.025)
    assert data["downbeats"] == data["beats"][::4] and data["drops"] == []
    assert np.allclose(data["beats"], np.arange(.17, 9, .5), atol=.03)


def test_fallback_measures_a_different_tempo_and_rejects_silence(tmp_path):
    track = tmp_path/"slow.wav"
    click_track(track, bpm=96)
    audio, rate = beatmap.decode(track)
    result = beatmap.analyze(audio, rate, backend="numpy")
    assert result["bpm"] == pytest.approx(96, abs=1)
    with pytest.raises(ValueError, match="No onsets"):
        beatmap.analyze(np.zeros(rate*3), rate, backend="numpy")


def test_folder_decodes_ogg_and_mp3_and_keeps_same_stem_sidecars(tmp_path):
    sf = pytest.importorskip("soundfile")
    wav = tmp_path/"party.wav"
    click_track(wav)
    audio, rate = beatmap.decode(wav)
    for ext in ("ogg", "mp3"):
        if ext.upper() not in sf.available_formats():
            pytest.skip(f"No {ext} encoder in fixture libsndfile")
        sf.write(wav.with_suffix("."+ext), audio, rate)
    beatmap.process(tmp_path, backend="numpy")
    for ext in ("wav", "ogg", "mp3"):
        data = json.loads((tmp_path/f"party.{ext}.beats.json").read_text())
        assert data["bpm"] == pytest.approx(120, abs=1)
        assert data["offset"] == pytest.approx(.17, abs=.03)


def test_tts_paid_stub_renders_takes_and_verifies_receipts(tmp_path, monkeypatch):
    jobs = tmp_path/"jobs.json"
    jobs.write_text(json.dumps([{"out":"lines/B.wav", "voice":"mock", "text":"Bee!", "takes":2},
                                {"out":"yay.mp3", "voice":"mock", "text":"Yay!"}]))
    calls = []
    def fake(model, text, voice, out, fmt, instructions):
        calls.append((model, text, voice, fmt))
        if fmt == "wav":
            click_track(out)
        else:
            out.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + bytes([255, 251, 144, 0]) + bytes(413))
    monkeypatch.setattr(tts.orc, "tts", fake)
    paths = tts.render(jobs)
    assert [p.name for p in paths] == ["B-01.wav", "B-02.wav", "yay.mp3"]
    assert [c[3] for c in calls] == ["wav","wav","mp3"]
    assert all(c[0] == "elevenlabs/eleven-v4" for c in calls)
    for p in paths:
        receipt = json.loads(p.with_suffix(p.suffix+".json").read_text())
        assert receipt["bytes"] == p.stat().st_size and receipt["request"]["voice"] == "mock"
    tts.render(jobs)
    assert len(calls) == 3
    paths[0].write_bytes(b"incomplete")
    with pytest.raises(ValueError, match="incomplete"):
        tts.render(jobs)
