import random

import pygame
import pytest

from lilypad.effects.animals import (
    ANIMAL_LETTERS,
    ANIMAL_VOICES,
    DINOSAURS,
    GAITS,
    MINI_KINDS,
    PEEKABOO_CAST,
    POSES,
    AnimalCrossing,
    PeekabooAnimal,
    animal_effect,
    animal_for_letter,
    animal_sprite,
    animal_sprite_facing,
    faces_right,
    mini_sprite,
    random_dinosaur,
)
from lilypad.effects.base import EffectContext

SCREEN = (640, 480)


def ctx(seed: int = 4321) -> EffectContext:
    return EffectContext(size=SCREEN, rng=random.Random(seed))


def has_visible_pixels(surface: pygame.Surface) -> bool:
    """Sample a coarse grid for any non-transparent pixel.

    Pixel reads are a test-time-only tool — nothing in the runtime path does
    per-pixel work (see the animals.py / particles.py header rules).
    """
    w, h = surface.get_size()
    step = max(1, min(w, h) // 24)
    for x in range(0, w, step):
        for y in range(0, h, step):
            if surface.get_at((x, y)).a > 0:
                return True
    return False


# ---------------------------------------------------------------------------
# Sprites
# ---------------------------------------------------------------------------
def test_animal_letters_map_to_known_animals():
    import string
    assert set(ANIMAL_LETTERS) == set(string.ascii_uppercase)
    for name in ANIMAL_LETTERS.values():
        assert animal_sprite(name, 200) is not None


@pytest.mark.parametrize("name", sorted(set(ANIMAL_LETTERS.values())))
@pytest.mark.parametrize("pose", POSES)
def test_every_animal_renders_every_pose(name, pose):
    sprite = animal_sprite(name, 240, pose)
    assert sprite.get_flags() & pygame.SRCALPHA
    assert sprite.get_height() == 240
    assert sprite.get_width() > 0
    assert has_visible_pixels(sprite), f"{name}/{pose} rendered nothing"


def test_animal_sprite_is_cached_per_key():
    a = animal_sprite("cow", 180, "idle")
    b = animal_sprite("cow", 180, "idle")
    assert a is b
    assert animal_sprite("cow", 180, "blink") is not a
    assert animal_sprite("cow", 181, "idle") is not a
    assert animal_sprite("pig", 180, "idle") is not a


def test_unknown_pose_falls_back_to_idle_and_unknown_name_raises():
    assert animal_sprite("duck", 150, "nonsense") is animal_sprite("duck", 150, "idle")
    with pytest.raises(KeyError):
        animal_sprite("dinosaur", 150)


@pytest.mark.parametrize("height", (120, 260, 500))
def test_animals_render_across_the_useful_size_range(height):
    for name in ANIMAL_LETTERS.values():
        sprite = animal_sprite(name, height, "idle")
        assert sprite.get_height() == height
        assert has_visible_pixels(sprite)


@pytest.mark.parametrize("kind", MINI_KINDS)
@pytest.mark.parametrize("size", (60, 100, 160))
def test_every_mini_kind_renders(kind, size):
    sprite = mini_sprite(kind, size)
    assert sprite.get_flags() & pygame.SRCALPHA
    assert sprite.get_size() == (size, size)
    assert has_visible_pixels(sprite), f"mini {kind}@{size} rendered nothing"


def test_mini_sprite_is_cached_per_key():
    a = mini_sprite("apple", 90)
    assert mini_sprite("apple", 90) is a
    assert mini_sprite("apple", 91) is not a
    assert mini_sprite("star", 90) is not a
    with pytest.raises(KeyError):
        mini_sprite("banana", 90)


# ---------------------------------------------------------------------------
# PeekabooAnimal
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(set(ANIMAL_LETTERS.values())))
def test_peekaboo_lifecycle(name):
    effect = PeekabooAnimal(ctx(), name)
    dt = 1 / 60
    frames = int(effect.total / dt)
    for i in range(frames - 1):
        assert effect.update(dt) is True, f"{name} died early at frame {i}"
    # Run past the end; it must finish and stay finished.
    for _ in range(10):
        alive = effect.update(dt)
    assert alive is False


def test_peekaboo_draws_at_every_phase():
    surface = pygame.Surface(SCREEN)
    effect = PeekabooAnimal(ctx(), "sheep")
    seen_poses = set()
    t = 0.0
    while t < effect.total + 0.2:
        effect.update(1 / 60)
        effect.draw(surface)
        seen_poses.add(effect.pose)
        t += 1 / 60
    # A jump owns the pose while it runs, so the blink windows have to sit
    # between the jumps — overlapping them is exactly how the blinks vanished
    # when the jumps were first added.
    assert {"idle", "blink", "squash"} <= seen_poses


def test_peekaboo_rises_then_falls_off_screen():
    effect = PeekabooAnimal(ctx(), "cow")
    start_y = effect.y
    effect.update(effect.RISE_TIME)
    risen_y = effect.y
    assert risen_y < start_y, "animal should slide up from below"
    for _ in range(int((effect.HOLD_TIME + effect.FALL_TIME) * 60) + 4):
        effect.update(1 / 60)
    assert effect.y >= SCREEN[1] - 1, "animal should end fully off-screen"


def test_peekaboo_is_positioned_in_the_middle_of_the_screen():
    for seed in range(30):
        effect = PeekabooAnimal(ctx(seed), "duck")
        assert 0 <= effect.x - effect._sprite_w / 2
        assert effect.x + effect._sprite_w / 2 <= SCREEN[0]


def test_peekaboo_is_deterministic_for_a_seeded_rng():
    a = PeekabooAnimal(ctx(99), "pig")
    b = PeekabooAnimal(ctx(99), "pig")
    c = PeekabooAnimal(ctx(100), "pig")
    assert a.x == b.x
    assert a.x != c.x


def test_peekaboo_len_stays_bounded():
    effect = PeekabooAnimal(ctx(), "duck")
    assert len(effect) == 25
    for _ in range(int(effect.total * 60)):
        effect.update(1 / 60)
        # Dust puffs are the only thing that can grow it, and they expire.
        assert len(effect) < 60


# ---------------------------------------------------------------------------
# The A-Z cast
# ---------------------------------------------------------------------------
def test_every_letter_has_a_creature_that_can_be_drawn_and_performed():
    import string
    for letter in string.ascii_uppercase:
        name = animal_for_letter(letter)
        assert name is not None, f"{letter} has no animal"
        assert animal_sprite(name, 180) is not None
        assert animal_effect(ctx(), name) is not None


def test_animal_lookup_is_case_insensitive_and_total():
    assert animal_for_letter("q") == animal_for_letter("Q")
    assert animal_for_letter("4") is None
    assert animal_for_letter("") is None


@pytest.mark.parametrize("name", sorted(ANIMAL_LETTERS.values()))
@pytest.mark.parametrize("pose", POSES)
def test_the_whole_cast_renders_every_pose(name, pose):
    sprite = animal_sprite(name, 200, pose)
    assert sprite.get_height() == 200
    assert has_visible_pixels(sprite), f"{name}/{pose} rendered nothing"


@pytest.mark.parametrize("name", sorted(ANIMAL_LETTERS.values()))
def test_nothing_in_the_cast_is_clipped_by_its_own_sprite(name):
    """Content touching a side edge means a jaw, tail or horn got sliced off.

    Every one of these was a real bug found by looking at a contact sheet:
    alligator tails, rabbit ears, a unicorn's horn and a triceratops' beak all
    ran off the edge of the surface they were drawn into.
    """
    if name in PEEKABOO_CAST:
        pytest.skip("front-on originals are drawn to fill their box")
    sprite = animal_sprite(name, 200)
    w, h = sprite.get_size()
    left = any(sprite.get_at((0, y)).a > 0 for y in range(0, h, 2))
    right = any(sprite.get_at((w - 1, y)).a > 0 for y in range(0, h, 2))
    top = any(sprite.get_at((x, 0)).a > 0 for x in range(0, w, 2))
    assert not (left or right or top), \
        f"{name} touches {'L' if left else ''}{'R' if right else ''}{'T' if top else ''}"


def test_every_dinosaur_is_a_real_animal_and_reachable():
    for name in DINOSAURS:
        assert animal_sprite(name, 180) is not None
    # Two of them have their own letter; the rest need the dinosaur key, or
    # they would exist in the code and never appear on screen.
    by_letter = set(ANIMAL_LETTERS.values()) & set(DINOSAURS)
    assert by_letter, "at least one dinosaur should have its own letter"
    assert set(DINOSAURS) - by_letter, "the dinosaur key should add more"


def test_random_dinosaur_only_ever_returns_dinosaurs():
    picks = {random_dinosaur(ctx(seed)) for seed in range(60)}
    assert picks <= set(DINOSAURS)
    assert len(picks) > 1, "should not always pick the same one"


def test_every_creature_with_a_voice_has_a_sprite():
    for name in ANIMAL_VOICES:
        assert animal_sprite(name, 120) is not None, f"{name} has a call but no art"


# ---------------------------------------------------------------------------
# AnimalCrossing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(set(ANIMAL_LETTERS.values()) - PEEKABOO_CAST))
def test_crossing_lifecycle(name):
    effect = AnimalCrossing(ctx(), name)
    dt = 1 / 60
    for i in range(int(effect.total / dt) - 1):
        assert effect.update(dt) is True, f"{name} died early at frame {i}"
    for _ in range(10):
        alive = effect.update(dt)
    assert alive is False


@pytest.mark.parametrize("name", sorted(set(ANIMAL_LETTERS.values()) - PEEKABOO_CAST))
def test_crossing_starts_and_ends_off_screen(name):
    effect = AnimalCrossing(ctx(), name)
    half = effect._sprite_w / 2
    assert effect.x + half <= 0 or effect.x - half >= SCREEN[0], \
        "should start fully off one edge"
    while effect.update(1 / 60):
        pass
    assert effect.x + half <= 0 or effect.x - half >= SCREEN[0], \
        "should leave fully off the other edge"


def test_crossing_travels_all_the_way_across():
    effect = AnimalCrossing(ctx(1), "fox")
    start = effect.x
    for _ in range(int(effect.total * 60)):
        effect.update(1 / 60)
    assert abs(effect.x - start) > SCREEN[0], "must actually cross the screen"


def test_crossing_goes_both_ways_over_many_spawns():
    directions = {AnimalCrossing(ctx(seed), "horse").going_left
                  for seed in range(40)}
    assert directions == {True, False}


def test_a_side_on_animal_is_mirrored_when_it_walks_the_other_way():
    right = animal_sprite_facing("fox", 150, "idle", going_left=False)
    left = animal_sprite_facing("fox", 150, "idle", going_left=True)
    assert left is not right
    assert left.get_size() == right.get_size()
    # Cached, not re-flipped every frame.
    assert animal_sprite_facing("fox", 150, "idle", going_left=True) is left


def test_front_on_originals_are_never_mirrored():
    """A mirrored front view is just a different, slightly wrong front view."""
    for name in PEEKABOO_CAST:
        assert faces_right(name) is False
        sprite = animal_sprite("cow", 150, "idle")
        assert animal_sprite_facing("cow", 150, "idle", going_left=True) is sprite


def test_hopping_animals_land_squashed_and_kick_dust():
    effect = AnimalCrossing(ctx(), "rabbit", gait="hop")
    poses, dust_seen = set(), 0
    for _ in range(int(effect.total * 60)):
        effect.update(1 / 60)
        poses.add(effect.pose)
        dust_seen = max(dust_seen, len(effect._dust))
    assert "squash" in poses, "a hop with no landing squash has no weight"
    assert dust_seen > 0, "landings should kick up dust"


def test_walking_animals_keep_their_feet_near_the_ground():
    effect = AnimalCrossing(ctx(), "bear", gait="walk")
    ys = []
    for _ in range(int(effect.total * 60)):
        effect.update(1 / 60)
        ys.append(effect.y)
    assert max(ys) - min(ys) < SCREEN[1] * 0.06, "a walk is not a hop"
    assert effect.airborne is False


@pytest.mark.parametrize("gait", ("fly", "swim"))
def test_air_and_water_gaits_stay_on_screen_vertically(gait):
    for seed in range(20):
        effect = AnimalCrossing(ctx(seed), "owl", gait=gait)
        assert effect.airborne is True
        half = effect.height / 2
        while effect.update(1 / 60):
            assert -1 <= effect.y - half and effect.y + half <= SCREEN[1] + 1, \
                f"{gait} drifted off screen vertically at y={effect.y}"


def test_gaits_are_only_ever_ones_the_crossing_implements():
    known = set(AnimalCrossing._SIZE)
    assert set(GAITS.values()) <= known, f"unknown gait in GAITS: {set(GAITS.values()) - known}"


def test_animal_effect_picks_the_right_performance():
    for name in PEEKABOO_CAST:
        assert isinstance(animal_effect(ctx(), name), PeekabooAnimal)
    assert isinstance(animal_effect(ctx(), "trex"), AnimalCrossing)


def test_crossing_draws_at_every_phase_without_error():
    surface = pygame.Surface(SCREEN)
    for name in ("trex", "owl", "whale", "rabbit", "jellyfish"):
        effect = AnimalCrossing(ctx(), name)
        while effect.update(1 / 60):
            effect.draw(surface)
