"""The reward loop: play earns a track, the track is a party.

The economy has to be legible to a 2-year-old — press keys, something big
happens — and legible to a parent reading the log. These tests pin the parts
that are easy to get subtly wrong: what counts as "engaged" play, the gap
between the fireworks and the music (where the mixer is idle but the party is
not over), and everything that must NOT happen while the frog is dancing.
"""

import random
import wave

import pytest

from lilypad.audio.engine import (PARTY_DUCK, PARTY_FANFARE_SECONDS,
                                  PARTY_MAX_SECONDS, AudioEngine)
from lilypad.audio.tunes import TUNE_NAMES
from lilypad.config import load as load_config
from lilypad.effects.engine import MAX_GLYPHS, EffectEngine
from lilypad.input.mapper import classify

SAMPLE_RATE = 22050
SCREEN = (320, 240)


def _silent_wav(path, seconds=1.0):
    frames = int(SAMPLE_RATE * seconds)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(b"\x00\x00" * frames)


def reward_engine(tmp_path, **kwargs):
    folder = tmp_path / "music"
    folder.mkdir(exist_ok=True)
    _silent_wav(folder / "song.wav")
    kwargs.setdefault("reward_seconds", 10.0)
    kwargs.setdefault("reward_presses", 20)
    kwargs.setdefault("reward_window", 10.0)
    return AudioEngine(tmp_path, mute=False, autogen=False, tunes="reward",
                       background_folder=folder, **kwargs)


def press(engine, times, start=0.0, gap=0.5):
    """`times` presses `gap` seconds apart, returning the final timestamp."""
    now = start
    for _ in range(times):
        engine.notify_activity(now)
        now += gap
    return now


# ----------------------------------------------------------------- the meter

def test_a_track_is_earned_by_engaged_seconds(tmp_path):
    engine = reward_engine(tmp_path, reward_presses=10_000)
    try:
        press(engine, 15, gap=0.5)      # 7 s of play — not yet
        assert engine.party_active is False
        press(engine, 10, start=7.5, gap=0.5)
        assert engine.party_active is True
    finally:
        engine.close()


def test_a_track_is_earned_by_press_count(tmp_path):
    """Fast mashing earns it on presses long before the clock runs out."""
    engine = reward_engine(tmp_path, reward_seconds=10_000.0, reward_presses=20)
    try:
        press(engine, 19, gap=0.05)
        assert engine.party_active is False
        engine.notify_activity(1.0)
        assert engine.party_active is True
    finally:
        engine.close()


def test_gaps_longer_than_the_window_do_not_count_as_play(tmp_path):
    """Wall clock is not play. A key every minute must not earn a party."""
    engine = reward_engine(tmp_path, reward_presses=10_000, reward_window=10.0)
    try:
        press(engine, 20, gap=60.0)     # 20 minutes of wall clock, no engagement
        assert engine.party_active is False
        assert engine._active_seconds == 0.0
    finally:
        engine.close()


def test_progress_survives_a_break_and_resets_only_after_a_party(tmp_path):
    engine = reward_engine(tmp_path, reward_presses=10_000)
    try:
        end = press(engine, 12, gap=0.5)          # ~5.5 s banked
        banked = engine._active_seconds
        assert banked > 4.0
        engine.notify_activity(end + 300.0)       # long break — keeps the bank
        assert engine._active_seconds == pytest.approx(banked)
        press(engine, 12, start=end + 300.5, gap=0.5)
        assert engine.party_active is True
        assert engine._active_seconds == 0.0      # spent on the party
        assert engine._press_count == 0
    finally:
        engine.close()


def test_presses_during_a_party_do_not_bank_the_next_one(tmp_path):
    engine = reward_engine(tmp_path)
    try:
        press(engine, 20, gap=0.05)
        assert engine.party_active is True
        press(engine, 50, start=5.0, gap=0.2)
        assert engine._press_count == 0
        assert engine._active_seconds == 0.0
    finally:
        engine.close()


# ------------------------------------------------------------- the lifecycle

def test_party_holds_through_the_silent_fanfare_gap(tmp_path):
    """The mixer is idle between the fireworks and the first note. Reading
    that as "the track finished" would end every party the instant it began."""
    engine = reward_engine(tmp_path)
    try:
        press(engine, 20, gap=0.05)
        assert engine.consume_party_started() is True
        assert engine.consume_party_started() is False   # one shot only
        engine.tick(1.0)
        assert engine.party_active is True
        assert engine._party == "starting"
    finally:
        engine.close()


def test_the_track_starts_after_the_fanfare_and_the_party_ends_with_it(tmp_path):
    engine = reward_engine(tmp_path)
    try:
        press(engine, 20, gap=0.05)
        started = engine._party_at
        engine.tick(started + PARTY_FANFARE_SECONDS + 0.1)
        assert engine._party == "playing"
        assert engine._music_playing() is True
        engine._music_playing = lambda: False        # the track ran out
        engine.tick(started + PARTY_FANFARE_SECONDS + 5.0)
        assert engine.party_active is False
    finally:
        engine.close()


def test_key_cues_duck_under_the_track_and_recover(tmp_path):
    engine = reward_engine(tmp_path)
    try:
        assert engine._duck == 1.0
        press(engine, 20, gap=0.05)
        # Still unducked through the fanfare — that cue plays into silence,
        # and it is the moment the whole reward is about.
        assert engine._duck == 1.0
        started = engine._party_at
        engine.tick(started + PARTY_FANFARE_SECONDS + 0.1)
        assert engine._duck == PARTY_DUCK
        engine._music_playing = lambda: False
        engine.tick(started + PARTY_FANFARE_SECONDS + 5.0)
        assert engine._duck == 1.0
    finally:
        engine.close()


def test_a_wedged_mixer_cannot_latch_the_party_on_forever(tmp_path):
    engine = reward_engine(tmp_path)
    try:
        press(engine, 20, gap=0.05)
        engine._music_playing = lambda: True         # never finishes
        engine.tick(engine._party_at + PARTY_FANFARE_SECONDS + 0.1)
        assert engine._party == "playing"
        engine.tick(engine._party_at + PARTY_MAX_SECONDS + 1.0)
        assert engine.party_active is False
    finally:
        engine.close()


def test_no_playable_track_ends_the_party_instead_of_dancing_in_silence(tmp_path):
    engine = AudioEngine(tmp_path, mute=False, autogen=False, tunes="reward",
                         background_folder=tmp_path / "nope",
                         reward_presses=5)
    try:
        press(engine, 5, gap=0.05)
        assert engine.party_active is True
        engine.tick(engine._party_at + PARTY_FANFARE_SECONDS + 0.1)
        assert engine.party_active is False
    finally:
        engine.close()


def test_generated_tune_fallback_plays_once_so_the_party_can_end(tmp_path):
    """Idle mode's tunes loop forever; a reward track must not."""
    for name in TUNE_NAMES:
        _silent_wav(tmp_path / f"tune_{name}.wav")
    engine = AudioEngine(tmp_path, mute=False, autogen=False, tunes="reward",
                         background_folder=tmp_path / "nope",
                         reward_presses=5)
    loops_seen = []
    engine._start_tune = lambda loops=-1: loops_seen.append(loops)
    engine._music_playing = lambda: True
    try:
        press(engine, 5, gap=0.05)
        engine.tick(engine._party_at + PARTY_FANFARE_SECONDS + 0.1)
        assert loops_seen == [0]
    finally:
        engine.close()


def test_idle_mode_tunes_still_loop_forever(tmp_path, monkeypatch):
    _silent_wav(tmp_path / f"tune_{TUNE_NAMES[0]}.wav")
    engine = AudioEngine(tmp_path, mute=False, autogen=False, tunes="idle")
    import pygame
    calls = []
    monkeypatch.setattr(pygame.mixer.music, "load", lambda *a, **k: None)
    monkeypatch.setattr(pygame.mixer.music, "play", lambda *a, **k: calls.append(k))
    try:
        engine.set_idle(True)
        assert calls[-1]["loops"] == -1
    finally:
        engine.close()


def test_muted_never_starts_a_party(tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    _silent_wav(folder / "song.wav")
    engine = AudioEngine(tmp_path, mute=True, autogen=False, tunes="reward",
                         background_folder=folder, reward_presses=2)
    try:
        press(engine, 20, gap=0.05)
        engine.tick(10.0)               # must not raise
        assert engine.party_active is False
    finally:
        engine.close()


@pytest.mark.parametrize("mode", ["idle", "off", "always", "active"])
def test_other_tune_modes_never_run_the_meter(tmp_path, mode):
    folder = tmp_path / "music"
    folder.mkdir()
    _silent_wav(folder / "song.wav")
    engine = AudioEngine(tmp_path, mute=False, autogen=False, tunes=mode,
                         background_folder=folder, reward_presses=2)
    try:
        press(engine, 20, gap=0.05)
        assert engine.party_active is False
        assert engine.consume_party_started() is False
    finally:
        engine.close()


# --------------------------------------------------------------- config wiring

def test_reward_is_the_default_mode_and_a_valid_one(tmp_path):
    assert load_config(None).music.tunes == "reward"
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[music]\ntunes = "reward"\nreward_seconds = 5\n'
        'reward_presses = 7\nreward_window = 3\n', encoding="utf-8")
    cfg = load_config(cfg_file)
    assert (cfg.music.reward_seconds, cfg.music.reward_presses,
            cfg.music.reward_window) == (5.0, 7, 3.0)


def test_reward_survives_the_audio_engine_mode_whitelist(tmp_path):
    """config.py and audio/engine.py keep separate lists of valid modes —
    a mode missing from the second is silently coerced to "idle"."""
    engine = AudioEngine(tmp_path, mute=True, tunes="reward")
    assert engine.tunes == "reward"
    engine.close()


# ------------------------------------------------------------- the visual side

def _engine() -> EffectEngine:
    return EffectEngine(SCREEN, rng=random.Random(3), idle_timeout=1.0,
                        sleep_timeout=5.0)


def test_start_party_throws_fireworks_and_makes_pip_dance():
    eng = _engine()
    eng.start_party(now=100.0)
    assert eng.party is True
    assert eng.frog.dancing is True
    assert eng.consume_celebration() is True     # the fanfare cue fires
    assert len(eng.effects) > 0
    eng.end_party(now=100.0)
    assert eng.frog.dancing is False


def test_a_dance_party_keeps_the_room_awake():
    """Nobody presses a key while watching the frog dance, and a track runs
    minutes — longer than both the attract and the sleep timeout."""
    eng = _engine()
    eng.start_party(now=100.0)
    now = 100.0
    for _ in range(600):
        now += 1 / 30
        eng.update(1 / 30, now)
    assert eng.asleep is False
    assert eng.attract is None


def test_the_room_still_sleeps_once_the_party_is_over():
    eng = _engine()
    eng.start_party(now=100.0)
    eng.end_party(now=100.0)
    now = 100.0
    for _ in range(300):
        now += 1 / 30
        eng.update(1 / 30, now)
    assert eng.asleep is True


def test_a_long_track_does_not_end_in_an_instant_blackout():
    """A five-minute track outlasts BOTH timeouts while nobody presses a key.
    If the idle clock isn't restarted when the party ends, the celebration
    cuts straight to attract mode — or to a black screen."""
    eng = _engine()          # idle_timeout 1 s, sleep_timeout 5 s
    eng.start_party(now=100.0)
    now = 100.0
    for _ in range(12_000):                 # 400 s of dancing
        now += 1 / 30
        eng.update(1 / 30, now)
    eng.end_party(now)
    eng.update(1 / 30, now + 1 / 30)
    assert eng.asleep is False
    assert eng.attract is None              # not attract-mode the same frame
    for _ in range(60):                     # 2 s later it may attract again
        now += 1 / 30
        eng.update(1 / 30, now)
    assert eng.attract is not None


def test_milestone_parties_stay_out_of_the_way_during_a_dance_party():
    eng = _engine()
    eng.start_party(now=100.0)
    assert eng._celebrate(big=False, now=1000.0) is False


# ------------------------------------------------------------ the glyph cap

def test_a_flurry_of_letters_never_stacks_more_than_the_cap():
    eng = EffectEngine(SCREEN, rng=random.Random(5))
    now = 100.0
    for letter in "ABCDEFGHIJKLMNOP":
        now += 0.05
        eng.spawn(classify(letter), now)
    live = [e for e in eng.effects
            if type(e).__name__ in ("GiantLetter", "CountAlong")
            and not eng._retired(e)]
    assert len(live) <= MAX_GLYPHS


def test_the_cap_retires_the_oldest_glyph_not_the_newest():
    eng = EffectEngine(SCREEN, rng=random.Random(5))
    now = 100.0
    for letter in "ABCDEFG":
        now += 0.05
        eng.spawn(classify(letter), now)
    glyphs = [e for e in eng.effects if type(e).__name__ == "GiantLetter"]
    assert eng._retired(glyphs[0]) is True      # first pressed, first retired
    assert eng._retired(glyphs[-1]) is False    # the key you just hit is visible


def test_a_dancing_frog_actually_keeps_hopping():
    """The party is only a party if Pip moves for the whole track — the
    joy-hop relaunch is open-ended here, not a three-second countdown."""
    eng = _engine()
    eng.start_party(now=100.0)
    airborne = 0
    xs = []
    for _ in range(600):                       # 20 s at 30 fps
        eng.frog.update(1 / 30)
        xs.append(eng.frog.x)
        if eng.frog.y < eng.frog.floor_y - 1:
            airborne += 1
    assert airborne > 300                      # off his pad most of the time
    assert max(xs) - min(xs) > eng.frog.r      # and working the room
    eng.end_party(now=100.0)
    for _ in range(120):
        eng.frog.update(1 / 30)
    assert eng.frog.y >= eng.frog.floor_y - 1  # settles once the music stops
