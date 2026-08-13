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
        "shape": Action(kind="shape", key="COMMA", letter="circle"),
        "color": Action(kind="color", key="GRAVE", letter="red"),
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


def test_every_letter_brings_a_creature_along():
    """The whole point of the upgrade: no letter is animal-less."""
    import string

    from lilypad.effects.animals import AnimalCrossing, PeekabooAnimal
    for letter in string.ascii_uppercase:
        effects = effects_for(ctx(), classify(letter))
        assert any(isinstance(e, (PeekabooAnimal, AnimalCrossing)) for e in effects), \
            f"{letter} summoned no animal"


def test_b_still_blows_bubbles_as_well_as_its_animal():
    from lilypad.effects.animals import AnimalCrossing, PeekabooAnimal
    from lilypad.effects.bubbles import BubbleField
    effects = effects_for(ctx(), classify("B"))
    assert any(isinstance(e, BubbleField) for e in effects)
    assert any(isinstance(e, (PeekabooAnimal, AnimalCrossing)) for e in effects)


def test_the_dinosaur_key_produces_a_dinosaur():
    from lilypad.effects.animals import DINOSAURS, AnimalCrossing
    seen = set()
    for seed in range(30):
        c = EffectContext(size=(640, 480), rng=random.Random(seed))
        effects = effects_for(c, Action(kind="special", letter="dino"))
        crossings = [e for e in effects if isinstance(e, AnimalCrossing)]
        assert len(crossings) == 1
        assert crossings[0].name in DINOSAURS
        seen.add(crossings[0].name)
    assert len(seen) > 1, "the dinosaur key should not always send the same one"


def test_the_f_keys_are_split_between_balloons_and_dinosaurs():
    assert {_SPECIALS[f"F{i}"] for i in range(1, 7)} == {"balloon"}
    assert {_SPECIALS[f"F{i}"] for i in range(7, 13)} == {"dino"}


def test_degradation_scale_reduces_particles():
    full = EffectContext(size=(640, 480), rng=random.Random(1), scale=1.0)
    tiny = EffectContext(size=(640, 480), rng=random.Random(1), scale=0.25)
    from lilypad.effects.particles import burst
    assert len(burst(tiny, (100, 100))) < len(burst(full, (100, 100)))
