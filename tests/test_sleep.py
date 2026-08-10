"""After ten quiet minutes the playground should go dark.

The room this runs in is a toddler's bedroom, so "nobody has touched it in ten
minutes" has to end with a black screen and unlit keys — not an attract loop
and a breathing rainbow keyboard playing music to an empty room.

Note what this is *not*: the HDMI output stays on. On a Pi 5 there is no way to
power it down from software (``vcgencmd display_power`` is gone and the DRM
``dpms`` node is read-only, both verified on the device), and blanking the
output would risk the monitor dropping hot-plug detect — the deadlock that
forced a fixed ``video=`` mode into cmdline.txt in the first place.
"""

import random

import pygame
import pytest

from lilypad.config import load as load_config
from lilypad.effects.base import EffectContext  # noqa: F401 — import sanity
from lilypad.effects.engine import EffectEngine
from lilypad.input.mapper import classify
from lilypad.lighting.base import LightingEngine
from lilypad.lighting.mock import MockLightingBackend

SCREEN = (320, 240)


def engine(sleep_timeout: float = 600.0) -> EffectEngine:
    return EffectEngine(SCREEN, rng=random.Random(7), sleep_timeout=sleep_timeout)


def _run_quiet(eng: EffectEngine, seconds: float, start: float = 1000.0) -> float:
    """Advance ``seconds`` of wall clock with nobody pressing anything."""
    now = start
    step = 1 / 30
    end = start + seconds
    while now < end:
        now += step
        eng.update(step, now)
    return now


# --------------------------------------------------------------- falling asleep

def test_stays_awake_well_past_the_attract_timeout():
    eng = engine()
    eng.last_action_time = 1000.0
    now = _run_quiet(eng, 120.0)
    assert eng.asleep is False, "two minutes is attract mode, not bedtime"
    assert eng.attract is not None, "attract should still be running"
    assert now > 1000.0


def test_goes_black_after_the_sleep_timeout():
    eng = engine(sleep_timeout=60.0)
    eng.last_action_time = 1000.0
    _run_quiet(eng, 75.0)
    assert eng.asleep is True
    assert eng.attract is None, "attract must stop, or the music keeps playing"


def test_sleeping_draws_pure_black_and_nothing_else():
    eng = engine(sleep_timeout=1.0)
    eng.last_action_time = 1000.0
    eng.spawn(classify("SPACE"), 1000.0)      # leave live effects on screen
    assert eng.effects
    _run_quiet(eng, 2.0)

    surface = pygame.Surface(SCREEN)
    surface.fill((90, 20, 140))               # anything but black
    eng.draw(surface)
    corners = [surface.get_at(p)[:3] for p in
               ((0, 0), (SCREEN[0] - 1, 0), (0, SCREEN[1] - 1),
                (SCREEN[0] - 1, SCREEN[1] - 1), (SCREEN[0] // 2, SCREEN[1] // 2))]
    assert all(c == (0, 0, 0) for c in corners), corners
    assert eng.effects == [], "live effects should be dropped, not left running"


def test_falling_asleep_and_waking_are_both_logged(caplog):
    """A black screen looks exactly like a crashed app from outside the room.

    These two lines are the only way to tell the difference over SSH, and the
    on-device verification of this feature depends on them.
    """
    eng = engine(sleep_timeout=1.0)
    eng.last_action_time = 1000.0
    with caplog.at_level("INFO", logger="lilypad.effects.engine"):
        now = _run_quiet(eng, 2.0)
        assert any("asleep" in r.message for r in caplog.records)
        caplog.clear()
        eng.wake(now)
        assert any("woken" in r.message for r in caplog.records)


def test_waking_something_already_awake_logs_nothing(caplog):
    eng = engine(sleep_timeout=600.0)
    with caplog.at_level("INFO", logger="lilypad.effects.engine"):
        eng.wake(1000.0)
        assert not caplog.records


def test_sleep_can_be_disabled():
    eng = engine(sleep_timeout=0.0)
    eng.last_action_time = 1000.0
    _run_quiet(eng, 3600.0)
    assert eng.asleep is False


# ------------------------------------------------------------------- waking up

def test_any_key_wakes_it_even_one_that_does_nothing_else():
    """A lone Shift produces no Action, but somebody is clearly there.

    The parent escape combo is two Shifts and Backspace — if holding it in
    front of a black screen showed nothing, the hatch would look broken at the
    exact moment a parent needs it.
    """
    eng = engine(sleep_timeout=1.0)
    eng.last_action_time = 1000.0
    now = _run_quiet(eng, 2.0)
    assert eng.asleep is True

    assert eng.wake(now) is True, "wake() reports that it had been asleep"
    assert eng.asleep is False
    assert eng.wake(now) is False, "already awake"


def test_waking_restarts_the_idle_clock():
    eng = engine(sleep_timeout=10.0)
    eng.last_action_time = 1000.0
    now = _run_quiet(eng, 12.0)
    assert eng.asleep is True
    eng.wake(now)
    # Nine more seconds of quiet is not enough to sleep again.
    _run_quiet(eng, 9.0, start=now)
    assert eng.asleep is False


def test_a_keypress_wakes_and_still_produces_its_effect():
    eng = engine(sleep_timeout=1.0)
    eng.last_action_time = 1000.0
    now = _run_quiet(eng, 2.0)
    eng.spawn(classify("A"), now)
    assert eng.asleep is False
    assert eng.effects, "the key that woke the screen must still do something"


def test_drawing_after_waking_paints_the_pond_again():
    eng = engine(sleep_timeout=1.0)
    eng.last_action_time = 1000.0
    now = _run_quiet(eng, 2.0)
    eng.wake(now)
    eng.update(1 / 60, now)
    surface = pygame.Surface(SCREEN)
    eng.draw(surface)
    assert surface.get_at((SCREEN[0] // 2, SCREEN[1] // 2))[:3] != (0, 0, 0)


# -------------------------------------------------------------------- lighting

def test_lighting_blanks_once_and_then_stops_sending_frames():
    backend = MockLightingBackend()
    frames = []
    backend.apply = lambda grid: frames.append(grid)     # type: ignore[method-assign]
    lights = LightingEngine(backend, fps=30)

    lights.key_pressed("A", 100.0)
    lights.tick(100.0)
    assert len(frames) == 1

    lights.set_sleep(True)
    assert len(frames) == 2, "sleeping should push one blank frame"
    assert all(px == (0, 0, 0) for row in frames[-1] for px in row)

    for i in range(30):
        lights.tick(101.0 + i)
    assert len(frames) == 2, "a sleeping keyboard must not keep sending frames"


def test_lighting_comes_back_immediately_on_wake():
    backend = MockLightingBackend()
    frames = []
    backend.apply = lambda grid: frames.append(grid)     # type: ignore[method-assign]
    lights = LightingEngine(backend, fps=30)
    lights.set_sleep(True)
    before = len(frames)

    lights.set_sleep(False)
    # Same instant as the blank frame: without resetting the frame clock this
    # would be swallowed by the fps interval and the keyboard would stay dark
    # for up to a frame after the child pressed a key.
    lights.tick(100.0)
    assert len(frames) == before + 1
    assert any(px != (0, 0, 0) for row in frames[-1] for px in row)


def test_repeated_set_sleep_is_a_no_op():
    backend = MockLightingBackend()
    frames = []
    backend.apply = lambda grid: frames.append(grid)     # type: ignore[method-assign]
    lights = LightingEngine(backend, fps=30)
    lights.set_sleep(True)
    lights.set_sleep(True)
    lights.set_sleep(True)
    assert len(frames) == 1


# ---------------------------------------------------------------------- config

def test_sleep_timeout_defaults_to_ten_minutes():
    assert load_config(None).display.sleep_timeout == 600.0


def test_sleep_timeout_is_read_and_clamped(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[display]\nsleep_timeout = 90.5\n", encoding="utf-8")
    assert load_config(cfg).display.sleep_timeout == 90.5

    cfg.write_text("[display]\nsleep_timeout = -5\n", encoding="utf-8")
    assert load_config(cfg).display.sleep_timeout == 0.0, "negative means never"


def test_main_loop_slows_down_while_asleep():
    """Painting black 60 times a second is pure heat."""
    import inspect

    from lilypad import __main__ as entry
    src = inspect.getsource(entry.main)
    assert "SLEEP_FPS if engine.asleep" in src
    assert entry.SLEEP_FPS < 60
    assert "lighting.set_sleep(engine.asleep)" in src


def test_main_loop_wakes_on_the_raw_event_not_the_action():
    import inspect

    from lilypad import __main__ as entry
    src = inspect.getsource(entry.main)
    wake = src.index("engine.wake(now)")
    mapper = src.index("mapper.feed(ev)")
    assert wake < mapper, "must wake before the mapper decides the key is a no-op"


@pytest.mark.parametrize("timeout", (0.0, 1.0, 600.0))
def test_engine_accepts_any_sane_timeout(timeout):
    EffectEngine(SCREEN, sleep_timeout=timeout)


# ------------------------------------------------------- concurrent animals

def test_concurrent_animals_are_capped_but_keys_still_do_something():
    """Every letter has a creature now, so running a hand along the keyboard
    would otherwise stack a dozen full-height sprites, each an alpha blit
    every frame."""
    from lilypad.effects.engine import MAX_ANIMALS
    from lilypad.effects.letters import GiantLetter

    eng = engine()
    now = 1000.0
    for i, letter in enumerate("ABCDEFGHIJKLMNOP"):
        now += 0.05
        eng.spawn(classify(letter), now)
        assert eng.animal_count() <= MAX_ANIMALS
    # The 16th letter still put its giant letter on screen.
    assert any(isinstance(e, GiantLetter) for e in eng.effects)


def test_animals_come_back_once_the_earlier_ones_have_left():
    from lilypad.effects.engine import MAX_ANIMALS
    eng = engine()
    now = 1000.0
    for letter in "ABCDEFGH":
        now += 0.05
        eng.spawn(classify(letter), now)
    assert eng.animal_count() == MAX_ANIMALS
    for _ in range(int(5.0 * 60)):          # let them all finish crossing
        now += 1 / 60
        eng.update(1 / 60, now)
    assert eng.animal_count() == 0
    eng.spawn(classify("Z"), now)
    assert eng.animal_count() == 1
