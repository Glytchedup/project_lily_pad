"""Encounters run on simulation time and never roll the pond's shared dice."""

import random

import pytest

from lilypad.effects.base import EffectContext
from lilypad.effects.critter import Frog
from lilypad.effects.ecosystem import AnimalView, CrossingGeometry, Director


def actor(name, x=480, *, key=1, direction=1, height=170, back=(0.45, 0.1), gait="walk"):
    geometry = CrossingGeometry(height=height, back_at=back, speed=400)
    return (key, name, x, 160, gait, direction, geometry)


@pytest.fixture
def pond():
    ctx = EffectContext((960, 540), random.Random(19))
    frog = Frog(ctx.size)
    frog.y = frog.floor_y
    return Director(ctx, seed=17), ctx, frog


@pytest.mark.parametrize("animal,expected", [
    (actor("giraffe"), "pip_duck"),
    (actor("elephant", back=None), "pip_ride"),
    (actor("brachiosaurus"), "pip_ride"),
    (actor("alligator"), "pip_jump"),
    (actor("iguana"), "pip_jump"),
    (actor("owl", gait="fly"), "pip_wave"),
    (actor("bear", height=154), "pip_ride"),  # Pip is 96 px tall
    (actor("bear", height=154, back=None), "pip_duck"),
    (actor("bear", height=153), "pip_jump"),
])
def test_pip_meets_crossing(pond, animal, expected):
    director, _, frog = pond
    intent, = director.tick(0, [animal], frog)
    assert (intent.kind, intent.animal_id, intent.other_id) == (expected, 1, None)


@pytest.mark.parametrize("animal", [
    actor("owl", x=-100, gait="fly"), actor("bear", x=700, direction=1),
    actor("whale", gait="swim"), actor("rabbit", gait="hop"),
])
def test_only_nearby_approaching_walkers_and_flyers_react(pond, animal):
    director, _, frog = pond
    assert director.tick(1, [animal], frog) == []


def test_greet_precedes_pip_and_shares_the_six_second_limit(pond):
    director, _, frog = pond
    left = actor("giraffe", x=360)
    right = actor("elephant", x=600, key=2, direction=-1)
    pair = [right, left]
    hello, = director.tick(0, pair, frog)
    assert (hello.kind, hello.animal_id, hello.other_id) == ("greet", 1, 2)
    assert director.tick(5.99, pair, frog) == []
    assert director.tick(0.02, [actor("owl", gait="fly")], frog)[0].kind == "pip_wave"
    assert director.tick(5.99, pair, frog) == []
    assert director.tick(0.02, pair, frog) == [hello]


@pytest.mark.parametrize("positions,directions", [
    ((10, 251), (1, -1)), ((10, 100), (-1, 1)), ((10, 100), (1, 1)),
    ((-100, 10), (1, -1)),
])
def test_walkers_must_be_visible_facing_and_in_range(pond, positions, directions):
    director, _, frog = pond
    walkers = [actor("bear", x=x, key=i, direction=d) for i, (x, d)
               in enumerate(zip(positions, directions))]
    assert director.tick(1, walkers, frog) == []


def test_degradation_and_seed_never_consume_context_randomness(pond):
    director, ctx, frog = pond
    initial = ctx.rng.getstate()
    actors = [actor("owl", gait="fly", key=i) for i in range(5)]
    ctx.scale = 0.49
    assert director.tick(10, actors, frog) == []
    ctx.scale = 0.5
    other = Director(ctx, seed=17)
    sequence = [director.tick(6, actors, frog) for _ in range(12)]
    assert sequence == [other.tick(6, actors, frog) for _ in range(12)]
    assert len({intent.animal_id for intent, in sequence}) > 1
    assert ctx.rng.getstate() == initial


@pytest.mark.parametrize("seed", [1, 2])
def test_jump_clears_a_moving_walker_in_both_directions(seed, monkeypatch):
    from lilypad.effects import animals
    from lilypad.effects.layout import POND

    monkeypatch.setattr(animals, "_layout", POND)
    monkeypatch.setattr(animals, "_max_sprite_width", 0.60)
    ctx = EffectContext((960, 540), random.Random(seed))
    crossing = animals.AnimalCrossing(ctx, "alligator")
    frog = Frog(ctx.size)
    frog.y = frog.floor_y
    director = Director(ctx)
    jumps = 0
    cleared = False
    for _ in range(300):
        crossing.update(1 / 60)
        for intent in director.tick(1 / 60, [AnimalView.from_crossing(crossing)], frog):
            assert intent.kind == "pip_jump"
            frog.jump_over()
            jumps += 1
        frog.update(1 / 60)
        if abs(crossing.x - frog.x) < crossing.speed / 60:
            assert frog.y + frog._feet < crossing.back_anchor()[1]
            cleared = True
    assert cleared and jumps == 1
    assert frog.y == frog.floor_y and frog.vy == 0
