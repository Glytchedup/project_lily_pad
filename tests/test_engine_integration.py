"""Integration tests for the upgraded EffectEngine: pond, trails, comets,
bubbles, ripples, milestones, and the new registry wiring."""

import random

import pygame

from lilypad.effects.animals import PeekabooAnimal
from lilypad.effects.base import EffectContext
from lilypad.effects.bubbles import BubbleField
from lilypad.effects.comet import Comet
from lilypad.effects.engine import EffectEngine
from lilypad.effects.registry import celebration, effects_for
from lilypad.input.mapper import Action

SIZE = (640, 480)


def make_engine(**kw):
    return EffectEngine(SIZE, rng=random.Random(99), **kw)


def surf():
    return pygame.Surface(SIZE)


def run(engine, seconds, dt=1 / 60):
    steps = int(seconds / dt)
    s = surf()
    for _ in range(steps):
        engine.update(dt, now=0.0)
        engine.draw(s)
    return s


# ---------------------------------------------------------------- registry

def test_animal_letters_spawn_peekaboo():
    ctx = EffectContext(size=SIZE, rng=random.Random(1))
    effects = effects_for(ctx, Action(kind="letter", letter="C"))
    assert any(isinstance(e, PeekabooAnimal) for e in effects)


def test_plain_letter_spawns_no_animal():
    ctx = EffectContext(size=SIZE, rng=random.Random(1))
    effects = effects_for(ctx, Action(kind="letter", letter="Q"))
    assert not any(isinstance(e, PeekabooAnimal) for e in effects)
    assert not any(isinstance(e, BubbleField) for e in effects)


def test_letter_b_spawns_bubbles():
    ctx = EffectContext(size=SIZE, rng=random.Random(1))
    effects = effects_for(ctx, Action(kind="letter", letter="B"))
    assert any(isinstance(e, BubbleField) for e in effects)


def test_celebration_factory_returns_effects():
    ctx = EffectContext(size=SIZE, rng=random.Random(1))
    assert len(celebration(ctx, big=False)) >= 3
    assert len(celebration(ctx, big=True)) >= 4


# ------------------------------------------------------------------ comets

def test_hold_start_creates_comet_hold_end_releases():
    e = make_engine()
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    assert "A" in e.comets
    comet = e.comets["A"]
    assert comet in e.effects
    e.spawn(Action(kind="hold_end", key="A"), now=1.0)
    assert "A" not in e.comets
    run(e, 3.0)  # burst + trail expire
    assert comet not in e.effects


def test_hold_end_without_start_is_harmless():
    e = make_engine()
    e.spawn(Action(kind="hold_end", key="Z"), now=0.0)
    assert e.comets == {}


def test_replacing_a_comet_releases_the_old_one():
    e = make_engine()
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    old = e.comets["A"]
    e.spawn(Action(kind="hold_start", key="A"), now=1.0)
    assert e.comets["A"] is not old
    assert old.released


# -------------------------------------------------------------- milestones

def test_milestone_triggers_celebration():
    e = make_engine(milestone_every=5)
    for i in range(5):
        e.spawn(Action(kind="sparkle", key=f"K{i}"), now=0.0)
    assert e.consume_celebration() is True
    assert e.consume_celebration() is False  # one-shot


def test_milestone_disabled_when_zero():
    e = make_engine(milestone_every=0)
    for i in range(60):
        e.spawn(Action(kind="sparkle", key=f"K{i}"), now=0.0)
    assert e.consume_celebration() is False


def test_alphabet_completion_celebrates_and_resets():
    e = make_engine(milestone_every=0)
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        e.spawn(Action(kind="letter", key=ch, letter=ch), now=0.0)
    assert e.consume_celebration() is True
    assert e.letters_seen == set()


def test_synthetic_actions_do_not_count_as_presses():
    e = make_engine(milestone_every=2)
    e.spawn(Action(kind="chord", keys=("A", "B")), now=0.0)
    e.spawn(Action(kind="mash_start"), now=0.0)
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    assert e.press_count == 0


# ------------------------------------------------------- frog interactions

def test_frog_bounce_spawns_ripple():
    e = make_engine()
    e.frog.vy = 500.0  # slam him into the floor
    e.frog.y = e.frog.h - e.frog.r - 1
    before = len(e.effects)
    e.update(1 / 60, now=0.0)
    assert len(e.effects) > before


def test_frog_pops_bubbles():
    e = make_engine()
    field = BubbleField(e.ctx, count=8)
    # Teleport one bubble onto the frog.
    field.bubbles[0].x, field.bubbles[0].y = e.frog.x, e.frog.y
    n = len(field.bubbles)
    e.effects.append(field)
    e.update(1 / 60, now=0.0)
    assert len(field.bubbles) < n


# ----------------------------------------------------------------- drawing

def test_draw_covers_screen_with_and_without_trails():
    for trails in (True, False):
        e = make_engine(trails=trails)
        s = surf()
        s.fill((255, 0, 255))  # sentinel
        for _ in range(30):    # veil converges over several frames
            e.update(1 / 60, now=0.0)
            e.draw(s)
        corner = s.get_at((1, 1))[:3]
        assert corner != (255, 0, 255)


def test_full_frame_with_everything_live():
    e = make_engine(milestone_every=3)
    e.spawn(Action(kind="letter", key="C", letter="C"), now=0.0)
    e.spawn(Action(kind="letter", key="B", letter="B"), now=0.0)
    e.spawn(Action(kind="number", key="3", count=3), now=0.0)
    e.spawn(Action(kind="enter", key="ENTER"), now=0.0)   # milestone fires here
    e.spawn(Action(kind="hold_start", key="Q"), now=0.0)
    e.spawn(Action(kind="mash_start"), now=0.0)
    run(e, 1.0)
    assert e.particle_count() > 0
    e.spawn(Action(kind="mash_end"), now=2.0)
    e.spawn(Action(kind="hold_end", key="Q"), now=2.0)
    run(e, 8.0)  # everything transient should drain without error


# ------------------------------------------------------- review-round fixes

def test_celebration_cooldown_limits_party_rate():
    e = make_engine(milestone_every=2)
    for i in range(20):
        e.spawn(Action(kind="sparkle", key=f"K{i}"), now=1.0)
    # 10 milestones hit, but only the first lands inside the cooldown window.
    assert e.consume_celebration() is True
    pulses = [x for x in e.effects if type(x).__name__ == "CelebrationPulse"]
    assert len(pulses) == 1
    # After the cooldown, the next milestone parties again.
    e.spawn(Action(kind="sparkle", key="L1"), now=30.0)
    e.spawn(Action(kind="sparkle", key="L2"), now=30.0)
    assert e.consume_celebration() is True


def test_comet_auto_releases_on_stuck_hold():
    from lilypad.effects.comet import _MAX_HOLD_SECONDS
    e = make_engine()
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    comet = e.comets["A"]
    for _ in range(int((_MAX_HOLD_SECONDS + 3) * 30)):
        e.update(1 / 30, now=0.0)
    assert comet.released
    assert comet not in e.effects  # fully drained and pruned


def test_comet_shed_rate_is_frame_rate_independent():
    from lilypad.effects.comet import Comet
    counts = {}
    for fps in (30, 120):
        ctx = EffectContext(size=SIZE, rng=random.Random(5))
        c = Comet(ctx)
        for _ in range(fps * 2):  # 2 simulated seconds
            c.update(1 / fps)
        counts[fps] = len(c.trail)
    assert abs(counts[30] - counts[120]) / max(counts.values()) < 0.25


def test_chaos_overlay_counts_toward_budget():
    e = make_engine()
    base = e.particle_count()
    e.spawn(Action(kind="mash_start"), now=0.0)
    assert e.particle_count() > base + 100
