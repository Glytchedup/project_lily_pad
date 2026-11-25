"""Packaged music, beat timing, and the legacy audio-engine call trace."""

import json
from unittest.mock import Mock, call

import pygame
import pytest

from lilypad.audio import engine as audio
from lilypad.audio.music import note_for_key
from lilypad.audio.tracks import (
    BeatClock,
    load_beat_map,
    load_bundled_tracks,
    reward_source_order,
)
from lilypad.audio.tunes import TUNE_NAMES
from lilypad.input.mapper import classify


@pytest.mark.parametrize("parent_track", [False, True])
def test_empty_manifests_preserve_cue_and_reward_calls(tmp_path, monkeypatch, parent_track):
    for directory in ("voice", "music"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "manifest.toml").write_bytes(b"# empty\n")
    monkeypatch.setattr(audio, "asset_root", lambda **kwargs: tmp_path)
    folder = tmp_path / "parent"
    folder.mkdir()
    generated = tmp_path / f"tune_{TUNE_NAMES[0]}.wav"
    generated.touch()
    track = generated
    if parent_track:
        track = folder / "parent.ogg"
        track.touch()

    mixer = Mock()
    monkeypatch.setattr(pygame, "mixer", mixer)
    engine = audio.AudioEngine(tmp_path, tunes="reward", autogen=False,
                               background_folder=folder, reward_presses=1)
    engine._play = Mock()
    engine.on_action(classify("G"))
    engine.on_action(classify("3"))
    engine.notify_activity(1.0)
    engine.tick(1.0 + audio.PARTY_FANFARE_SECONDS)

    assert engine._play.call_args_list == [
        call(f"note_{note_for_key('G')}", "chime1"), call("voice/G"),
        call("squeak", "boing"), call("voice/3", "pop"), call("count_2"),
    ]
    assert mixer.mock_calls == [
        call.init(frequency=22050, channels=2, buffer=512), call.set_num_channels(16),
        call.music.load(str(track)), call.music.set_volume(0.45),
        call.music.play(loops=0, fade_ms=1200), call.music.set_volume(0.95),
        call.music.get_busy(),
    ]


def test_engine_constructs_both_loaders_without_decoding_or_playing(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    (music / "party.ogg").touch()
    (music / "manifest.toml").write_text('[tracks.party]\nfile="party.ogg"', encoding="utf-8")
    voice = tmp_path / "voice"
    voice.mkdir()
    (voice / "gee.wav").touch()
    (voice / "manifest.toml").write_text('[letters.G]\nfile="gee.wav"', encoding="utf-8")
    mixer = Mock()
    monkeypatch.setattr(pygame, "mixer", mixer)
    monkeypatch.setattr(audio, "asset_root", lambda **kwargs: tmp_path)
    engine = audio.AudioEngine(tmp_path / "sounds", mute=True)
    assert engine.bundled_tracks == (music / "party.ogg",)
    assert not mixer.mock_calls
    assert engine.voice_loader.get("letters", "G") is mixer.Sound.return_value
    mixer.Sound.assert_called_once_with(str(voice / "gee.wav"))


def test_track_list_preserves_manifest_order_and_skips_unusable_rows(tmp_path):
    outside = tmp_path / "private.wav"
    outside.touch()
    music = tmp_path / "bundle"
    music.mkdir()
    for name in ("a.ogg", "z.wav", "unlisted.ogg"):
        (music / name).touch()
    (music / "manifest.toml").write_text(
        '[tracks.lilies]\nfile="z.wav"\n[tracks.bad]\nfile=3\n'
        '[tracks.missing]\nfile="no.ogg"\n[tracks.frogs]\nfile="a.ogg"\n'
        '[tracks.outside]\nfile="../private.wav"\n[other.entry]\nfile="unlisted.ogg"\n',
        encoding="utf-8",
    )
    assert load_bundled_tracks(music) == (music / "z.wav", music / "a.ogg")


@pytest.mark.parametrize(("mode", "expected"), [
    ("folder_first", ("folder", "bundled", "generated")),
    ("bundled", ("bundled", "folder", "generated")),
    ("generated", ("generated",)),
])
def test_reward_source_order(mode, expected):
    assert reward_source_order(mode) == expected


@pytest.fixture
def track_map(tmp_path):
    track = tmp_path / "party.ogg"
    track.touch()
    # Same units, precision and fields as tools/art/beatmap.py, with a lead-in.
    beats = [round(0.17 + i * 0.5, 6) for i in range(11)]
    data = {"bpm": 120, "offset": beats[0], "beats": beats, "downbeats": beats[::4],
            "drops": [beats[4]]}
    sidecar = tmp_path / "party.ogg.beats.json"
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    return track, sidecar, data


def test_sidecar_uses_full_track_name_and_missing_map_leaves_track_playable(track_map):
    track, _, data = track_map
    mapped = load_beat_map(track)
    assert (mapped.bpm, mapped.offset, mapped.beats, mapped.downbeats, mapped.drops) == (
        120, 0.17, tuple(data["beats"]), tuple(data["downbeats"]), (2.17,),
    )
    other = track.with_suffix(".mp3")
    other.touch()
    assert load_beat_map(other) is None
    assert other.is_file()


@pytest.mark.parametrize(("field", "value"), [
    ("bpm", 59.99), ("bpm", 180.01), ("bpm", True), ("bpm", "120"),
    ("bpm", float("inf")), ("offset", -1), ("offset", 0.67),
    ("beats", []), ("beats", [0.17, 0.67, 0.66]), ("beats", [0.17, 0.17]),
    ("beats", [0.17, float("nan")]), ("beats", "0.17"),
    ("downbeats", [0.18]), ("drops", [4.17, 2.17]),
])
def test_invalid_map_disables_sync(track_map, field, value):
    track, sidecar, data = track_map
    data[field] = value
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    assert load_beat_map(track) is None


@pytest.mark.parametrize("raw", [b"{broken", b"{}", b"null", b"\xff"])
def test_unreadable_or_incomplete_sidecar_disables_sync(track_map, raw):
    track, sidecar, _ = track_map
    sidecar.write_bytes(raw)
    assert load_beat_map(track) is None


@pytest.mark.parametrize("bpm", [60, 180])
def test_bpm_limits_are_inclusive(track_map, bpm):
    track, sidecar, data = track_map
    data["bpm"] = bpm
    del data["drops"]
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    assert load_beat_map(track).bpm == bpm


@pytest.mark.parametrize(("ms", "beat", "bar", "phase", "to_next", "drop"), [
    (0, -1, -1, 0, 0.17, False),
    (170, 0, 0, 0, 0.5, False),
    (420, 0, 0, 0.5, 0.25, False),
    (2169, 3, 0, 0.998, 0.001, False),
    (2170, 4, 1, 0, 0.5, True),
    (2669, 4, 1, 0.998, 0.001, True),
    (2670, 5, 1, 0, 0.5, False),
    (6170, 12, 3, 0, 0.5, False),  # extrapolated at the declared tempo
])
def test_beat_clock_on_a_120_bpm_map(track_map, ms, beat, bar, phase, to_next, drop):
    clock = BeatClock(load_beat_map(track_map[0]), ms)
    assert (clock.beat_index, clock.bar, clock.is_drop) == (beat, bar, drop)
    assert clock.beat_phase == pytest.approx(phase)
    assert clock.time_to_next_beat == pytest.approx(to_next)


def test_clock_uses_measured_intervals_and_downbeats(track_map):
    track, sidecar, data = track_map
    data.update(beats=[0.17, 0.65, 1.18, 1.7, 2.16], downbeats=[0.65], drops=[1.8])
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    clock = BeatClock(load_beat_map(track), 410)
    assert (clock.beat_index, clock.bar) == (0, -1)   # pickup
    assert clock.beat_phase == pytest.approx(0.5)
    assert clock.time_to_next_beat == pytest.approx(0.24)
    clock.resync(1790)
    assert (clock.bar, clock.is_drop) == (0, False)
    clock.resync(1810)
    assert clock.is_drop
    clock.resync(2160)
    assert not clock.is_drop


def test_clock_resync_corrects_drift_and_handles_unavailable_or_restarted_mixer(track_map):
    clock = BeatClock(load_beat_map(track_map[0]), 170)
    for _ in range(120):
        clock.advance(1.01 / 60)   # simulated 1% drift over a bar
    assert clock.beat_phase * 0.5 > 1 / 60
    clock.resync(2171)             # a millisecond past the actual downbeat
    assert (clock.bar, clock.beat_index, clock.is_drop) == (1, 4, True)
    assert clock.beat_phase * 0.5 == pytest.approx(0.001)
    clock.resync(-1)
    clock.advance(0.1)
    assert clock.time_to_next_beat == pytest.approx(0.399)
    clock.resync(0)
    assert (clock.beat_index, clock.bar, clock.is_drop) == (-1, -1, False)


def test_accumulated_frame_deltas_land_on_the_mapped_drop(track_map):
    clock = BeatClock(load_beat_map(track_map[0]), 170)
    for _ in range(120):
        clock.advance(1 / 60)
    assert (clock.beat_index, clock.bar, clock.is_drop) == (4, 1, True)
    assert clock.beat_phase == pytest.approx(0, abs=1e-12)
    assert clock.time_to_next_beat == pytest.approx(0.5)


def test_free_running_clock_needs_no_mixer():
    clock = BeatClock()
    assert (clock.beat_index, clock.bar, clock.beat_phase) == (0, 0, 0)
    clock.advance(2.125)
    assert (clock.beat_index, clock.bar, clock.beat_phase) == (4, 1, 0.25)
    assert clock.time_to_next_beat == 0.375
    assert not clock.is_drop
