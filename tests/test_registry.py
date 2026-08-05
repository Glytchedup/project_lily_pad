import random

import pygame

from lilypad.effects.base import EffectContext
from lilypad.effects.registry import _SPECIAL_FACTORIES, effects_for, registered_kinds
from lilypad.input.mapper import _SPECIALS, Action, classify


def ctx():
    return EffectContext(size=(640, 480), rng=random.Random(1234))


def test_every_registry_kind_yields_effects():
    samples = {
        "letter": Action(kind="letter", letter="Q"),
        "number": Action(kind="number", count=4),
        "space": Action(kind="space"),
        "enter": Action(kind="enter"),
        "chord": Action(kind="chord", keys=("A", "B")),
        "sparkle": Action(kind="sparkle", key="MACRO1"),
        "special": Action(kind="special", key="ESC", letter="swirl"),
    }
    assert set(samples) == registered_kinds()
    for kind, action in samples.items():
        effects = effects_for(ctx(), action)
        assert effects, f"kind {kind} produced no effects"


def test_every_mapper_special_has_a_factory_or_sparkle_fallback():
    # Every special name the mapper can emit must resolve to *something*.
    for name in set(_SPECIALS.values()):
        action = Action(kind="special", letter=name)
        assert effects_for(ctx(), action), f"special {name} produced nothing"


def test_unknown_special_falls_back_to_sparkle():
    action = Action(kind="special", letter="not-a-real-special")
    assert effects_for(ctx(), action)


def test_special_factories_all_run_and_draw():
    surface = pygame.Surface((640, 480))
    for name, factory in _SPECIAL_FACTORIES.items():
        for effect in factory(ctx(), Action(kind="special", letter=name)):
            effect.update(1 / 60)
            effect.draw(surface)


def test_effects_animate_and_die():
    c = ctx()
    surface = pygame.Surface((640, 480))
    for action in (classify("A"), classify("5"), classify("SPACE"), classify("ENTER")):
        for effect in effects_for(c, action):
            alive_frames = 0
            while effect.update(1 / 60) and alive_frames < 60 * 30:
                effect.draw(surface)
                alive_frames += 1
            assert alive_frames < 60 * 30, "effect never finished"


def test_degradation_scale_reduces_particles():
    full = EffectContext(size=(640, 480), rng=random.Random(1), scale=1.0)
    tiny = EffectContext(size=(640, 480), rng=random.Random(1), scale=0.25)
    from lilypad.effects.particles import burst
    assert len(burst(tiny, (100, 100))) < len(burst(full, (100, 100)))
