"""The reward loop: play earns a track, the track is a party.

The economy has to be legible to a 2-year-old — press keys, something big
happens — and legible to a parent reading the log. These tests pin the parts
that are easy to get subtly wrong: what counts as "engaged" play, the gap
between the fireworks and the music (where the mixer is idle but the party is
not over), and everything that must NOT happen while the frog is dancing.
"""

import random
import wave

import pygame

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


def test_the_party_track_is_louder_than_a_background_bed(tmp_path, monkeypatch):
    """The reward track is the event, not a bed under the keys: it must be
    lifted off tune_volume once it starts, and the cues ducked under it."""
    engine = reward_engine(tmp_path, party_volume=0.95, party_duck=0.25)
    import pygame
    vols = []
    monkeypatch.setattr(pygame.mixer.music, "set_volume", lambda v: vols.append(v))
    monkeypatch.setattr(pygame.mixer.music, "load", lambda *a, **k: None)
    monkeypatch.setattr(pygame.mixer.music, "play", lambda *a, **k: None)
    engine._music_playing = lambda: True
    try:
        press(engine, 20, gap=0.05)
        engine.tick(engine._party_at + PARTY_FANFARE_SECONDS + 0.1)
        assert vols[-1] == pytest.approx(0.95)   # last word is the party level
        assert engine._duck == pytest.approx(0.25)
    finally:
        engine.close()


def test_party_mix_is_configurable(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[music]\nparty_volume = 0.8\nparty_duck = 0.1\n',
                        encoding="utf-8")
    cfg = load_config(cfg_file)
    assert (cfg.music.party_volume, cfg.music.party_duck) == (0.8, 0.1)


# ------------------------------------------------------------- the party bar

def test_the_meter_tracks_whichever_threshold_is_further_along(tmp_path):
    engine = reward_engine(tmp_path, reward_seconds=10.0, reward_presses=50)
    try:
        assert engine.reward_progress == 0.0
        press(engine, 10, gap=0.05)          # 10/50 presses, ~0.5s of play
        assert engine.reward_progress == pytest.approx(10 / 50)
        engine2 = reward_engine(tmp_path, reward_seconds=10.0,
                                reward_presses=10_000)
        press(engine2, 11, gap=0.5)          # 5s of play beats the press count
        assert engine2.reward_progress == pytest.approx(0.5, abs=0.05)
        engine2.close()
    finally:
        engine.close()


def test_the_meter_is_hidden_during_a_party_and_when_silent(tmp_path):
    """The party is its own feedback; a full bar during the fireworks tells a
    child nothing they can't already see."""
    engine = reward_engine(tmp_path)
    try:
        press(engine, 20, gap=0.05)
        assert engine.party_active is True
        assert engine.reward_progress == 0.0
    finally:
        engine.close()
    muted = AudioEngine(tmp_path, mute=True, autogen=False, tunes="reward")
    assert muted.reward_progress == 0.0
    muted.close()


@pytest.mark.parametrize("mode", ["idle", "off", "always", "active"])
def test_no_meter_outside_reward_mode(tmp_path, mode):
    engine = AudioEngine(tmp_path, mute=False, autogen=False, tunes=mode)
    try:
        press(engine, 30, gap=0.05)
        assert engine.reward_progress == 0.0
    finally:
        engine.close()


def test_the_meter_never_exceeds_one(tmp_path):
    engine = reward_engine(tmp_path, reward_seconds=1.0, reward_presses=10_000)
    try:
        press(engine, 40, gap=0.5)
        assert 0.0 <= engine.reward_progress <= 1.0
    finally:
        engine.close()


def test_party_bar_draws_without_error_and_only_when_earned():
    """The bar is drawn straight onto the display surface every frame."""
    from lilypad.__main__ import _draw_party_meter
    surface = pygame.Surface((1280, 720))
    surface.fill((0, 0, 0))
    _draw_party_meter(surface, 0.0)
    assert surface.get_at((1180, 30))[:3] == (0, 0, 0)   # nothing at zero
    for p in (0.01, 0.5, 1.0):
        _draw_party_meter(surface, p)
    assert surface.get_at((1180, 30))[:3] != (0, 0, 0)   # something is there


# ---------------------------------------------- the "animals" reward rule
#
# A party is earned by meeting N DIFFERENT animals, spaced by a minimum gap
# from the previous party's end. Mashing one key, numbers and non-animal keys
# earn nothing. The effect engine's on_animal hook names the creature that
# really spawned (F7-F12 dinosaur picks included).

from lilypad.effects.animals import ANIMAL_LETTERS, DINOSAURS  # noqa: E402

CAST = sorted(set(ANIMAL_LETTERS.values()) | set(DINOSAURS))


def animal_engine(tmp_path, **kwargs):
    kwargs.setdefault("reward_rule", "animals")
    kwargs.setdefault("reward_animals", 8)
    kwargs.setdefault("reward_min_gap", 120.0)
    return reward_engine(tmp_path, **kwargs)


def meet(engine, names, start=0.0, gap=0.5):
    """Show each animal in turn (notify_activity follows, as in the main loop)."""
    now = start
    for name in names:
        engine.note_animal(name, now)
        engine.notify_activity(now)
        now += gap
    return now


def test_eight_different_animals_earn_a_party_once_the_gap_has_passed(tmp_path):
    engine = animal_engine(tmp_path, reward_min_gap=0.0)
    try:
        meet(engine, CAST[:7])
        assert engine.party_active is False
        assert engine.reward_progress == pytest.approx(7 / 8)
        engine.note_animal(CAST[7], 10.0)
        assert engine.party_active is True
        assert engine.consume_party_started() is True
    finally:
        engine.close()


def test_repeats_and_mashing_one_key_never_earn_a_party(tmp_path):
    engine = animal_engine(tmp_path, reward_min_gap=0.0)
    try:
        meet(engine, ["cow"] * 500, gap=0.02)
        assert engine.party_active is False
        assert engine.reward_progress == pytest.approx(1 / 8)
        # Far past the "play" rule's seconds and press limits.
        press(engine, 500, start=100.0, gap=7.0)
        assert engine.party_active is False
    finally:
        engine.close()


def test_a_dinosaur_counts_by_the_name_that_spawned(tmp_path):
    engine = animal_engine(tmp_path, reward_min_gap=0.0)
    try:
        meet(engine, ["trex", "trex", "triceratops", "triceratops", "pterodactyl"])
        assert engine.reward_progress == pytest.approx(3 / 8)
    finally:
        engine.close()


def test_number_keys_and_other_actions_never_count(tmp_path):
    """Only an animal name fills the meter: the effect hook is never called
    for a number, and presses alone add nothing."""
    engine = animal_engine(tmp_path, reward_min_gap=0.0)
    try:
        for i, key in enumerate(["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"] * 3):
            engine.on_action(classify(key))
            engine.notify_activity(i * 0.3)
        assert engine.reward_progress == 0.0
        assert engine.party_active is False
        engine.note_animal("", 20.0)            # an unnamed animal is no animal
        assert engine.reward_progress == 0.0
    finally:
        engine.close()


def test_real_key_presses_through_the_effect_engine(tmp_path):
    """End to end: letters and F-key dinos spawn animals that reach the meter;
    digits, Space and Enter spawn none."""
    audio = animal_engine(tmp_path, reward_min_gap=0.0)
    eng = _engine()
    eng.on_animal = audio.note_animal
    try:
        now = 1.0
        for key in ["1", "2", "SPACE", "ENTER"]:
            eng.spawn(classify(key), now)
            audio.notify_activity(now)
            now += 0.2
        assert audio.reward_progress == 0.0
        for key in ["A", "A", "A", "B", "D"]:
            eng.spawn(classify(key), now)
            audio.notify_activity(now)
            now += 0.2
        assert audio.reward_progress == pytest.approx(3 / 8)
        # An F-key summons a random dinosaur, and it is that one that counts
        # (a fresh engine: the five-animal cap would drop it on this one).
        dino_audio = animal_engine(tmp_path, reward_min_gap=0.0)
        try:
            dino_eng = _engine()
            dino_eng.on_animal = dino_audio.note_animal
            dino_eng.spawn(classify("F9"), 1.0)
            assert dino_audio._animals_met and dino_audio._animals_met <= set(DINOSAURS)
            assert dino_audio.reward_progress == pytest.approx(1 / 8)
        finally:
            dino_audio.close()
    finally:
        audio.close()


def test_the_gap_default_is_two_minutes(tmp_path):
    import inspect
    assert inspect.signature(AudioEngine).parameters["reward_min_gap"].default == 120.0
    assert AudioEngine(tmp_path, mute=True).reward_min_gap == 120.0


def test_the_first_party_fires_on_the_eighth_animal_with_no_gap_wait(tmp_path):
    """The gap spaces parties apart; it is not a start-up delay. The 8th
    distinct animal fires it on that very note_animal call (so the main loop
    starts the show the same frame), seconds after launch, with the 2-minute
    default gap nowhere near over."""
    engine = animal_engine(tmp_path, reward_min_gap=120.0)
    try:
        engine.tick(0.0)                                    # app start
        meet(engine, CAST[:7], start=3.0)
        assert engine.party_active is False
        assert engine.reward_progress == pytest.approx(7 / 8)
        engine.note_animal(CAST[7], 8.0)                    # the 8th, 8 s after launch
        assert engine.party_active is True
        assert engine.consume_party_started() is True
        assert engine._party_at == 8.0
    finally:
        engine.close()


def test_a_meter_filled_inside_the_gap_fires_when_the_gap_expires(tmp_path):
    """No further animal and no keypress needed: tick() releases it."""
    engine = animal_engine(tmp_path, reward_min_gap=120.0)
    try:
        meet(engine, CAST[:8], start=1.0)                   # first party, immediately
        assert engine.party_active is True
        engine.consume_party_started()
        engine._end_party(200.0)                            # the gap runs from the END
        meet(engine, CAST[8:16], start=201.0)               # a full meter again
        assert engine.reward_progress == 1.0
        assert engine.party_active is False                 # held by the gap
        press(engine, 10, start=210.0, gap=5.0)             # presses inside the gap
        engine.note_animal(CAST[16], 250.0)                 # extra animals inside it
        assert engine.party_active is False
        engine.tick(319.9)
        assert engine.party_active is False
        engine.tick(320.0)                                  # gap over: fires on this tick
        assert engine.party_active is True
        assert engine.consume_party_started() is True
    finally:
        engine.close()


def test_a_number_key_after_the_gap_releases_a_full_meter(tmp_path):
    engine = animal_engine(tmp_path, reward_min_gap=30.0)
    try:
        meet(engine, CAST[:8], start=1.0)
        engine._end_party(5.0)                              # an earlier party ended at 5 s
        meet(engine, CAST[8:16], start=6.0)
        assert engine.party_active is False
        engine.on_action(classify("5"))
        engine.notify_activity(35.0)
        assert engine.party_active is True
    finally:
        engine.close()


def test_the_counter_resets_after_a_party_and_the_gap_runs_from_its_end(tmp_path):
    engine = animal_engine(tmp_path, reward_min_gap=100.0)
    try:
        engine.tick(0.0)
        meet(engine, CAST[:8], start=101.0)
        assert engine.party_active is True
        assert engine.reward_progress == 0.0                # hidden during the party
        meet(engine, CAST[8:20], start=102.0)               # animals mid-party don't bank
        engine._end_party(200.0)
        assert engine.party_active is False
        assert engine.reward_progress == 0.0                # counter was reset
        meet(engine, CAST[:8], start=201.0)                 # full again, 1 s after the end
        assert engine.reward_progress == 1.0
        assert engine.party_active is False                 # gap runs from the END (200)
        engine.notify_activity(299.0)
        assert engine.party_active is False
        engine.notify_activity(300.0)
        assert engine.party_active is True
    finally:
        engine.close()


def test_animals_met_before_a_party_do_not_carry_over(tmp_path):
    engine = animal_engine(tmp_path, reward_min_gap=0.0)
    try:
        meet(engine, CAST[:8])
        assert engine.party_active is True
        engine._end_party(50.0)
        meet(engine, CAST[:7], start=51.0)                  # the same seven again
        assert engine.party_active is False
        assert engine.reward_progress == pytest.approx(7 / 8)
    finally:
        engine.close()


def test_the_party_failsafe_is_untouched_under_the_animals_rule(tmp_path, monkeypatch):
    engine = animal_engine(tmp_path, reward_min_gap=0.0)
    try:
        meet(engine, CAST[:8])
        assert engine.party_active is True
        monkeypatch.setattr(engine, "_music_playing", lambda: True)   # never finishes
        engine.tick(engine._party_at + PARTY_FANFARE_SECONDS + 0.1)
        assert engine._party == "playing"
        engine.tick(engine._party_at + PARTY_MAX_SECONDS + 1.0)
        assert engine.party_active is False
    finally:
        engine.close()


def test_animals_rule_is_silent_when_muted_or_outside_reward_mode(tmp_path):
    muted = AudioEngine(tmp_path, mute=True, autogen=False, tunes="reward",
                        reward_rule="animals", reward_animals=2, reward_min_gap=0.0)
    muted.note_animal("cow", 0.0)
    muted.note_animal("pig", 1.0)
    assert muted.party_active is False and muted.reward_progress == 0.0
    muted.close()
    idle = AudioEngine(tmp_path, mute=False, autogen=False, tunes="idle",
                       reward_rule="animals", reward_animals=2, reward_min_gap=0.0)
    idle.note_animal("cow", 0.0)
    idle.note_animal("pig", 1.0)
    assert idle.party_active is False and idle.reward_progress == 0.0
    idle.close()


# ------------------------------------------------ the "play" rule is unchanged

def test_play_rule_ignores_animals_and_the_gap(tmp_path):
    """The play rule earns on seconds-or-presses exactly as before: animals
    are not counted and the animals-rule spacing gap does not apply."""
    engine = reward_engine(tmp_path, reward_rule="play", reward_min_gap=10_000.0,
                           reward_animals=1, reward_presses=20)
    try:
        for name in CAST:
            engine.note_animal(name, 0.0)
        assert engine.party_active is False
        assert engine.reward_progress == 0.0
        press(engine, 19, gap=0.05)
        assert engine.party_active is False
        engine.notify_activity(1.0)
        assert engine.party_active is True       # no gap holds it back
        assert engine._press_count == 0
    finally:
        engine.close()


def test_play_rule_progress_is_the_older_meter(tmp_path):
    engine = reward_engine(tmp_path, reward_rule="play", reward_seconds=10_000.0,
                           reward_presses=20)
    try:
        press(engine, 10, gap=0.05)
        assert engine.reward_progress == pytest.approx(10 / 20)
    finally:
        engine.close()


def test_the_bare_constructor_keeps_the_play_rule(tmp_path):
    engine = reward_engine(tmp_path)
    try:
        assert engine.reward_rule == "play"
    finally:
        engine.close()


def test_unknown_rule_falls_back_to_play(tmp_path):
    engine = reward_engine(tmp_path, reward_rule="mashing")
    try:
        assert engine.reward_rule == "play"
    finally:
        engine.close()
