import random

import pygame
import pytest

from lilypad.effects.animals import (
    ANIMAL_LETTERS,
    MINI_KINDS,
    POSES,
    PeekabooAnimal,
    animal_sprite,
    mini_sprite,
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
    assert ANIMAL_LETTERS == {"C": "cow", "D": "duck", "P": "pig", "S": "sheep"}
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
    assert seen_poses == {"idle", "blink"}, "expected the blink pose during hold"


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


def test_peekaboo_len_is_positive_and_flat():
    effect = PeekabooAnimal(ctx(), "duck")
    assert len(effect) == 25
    effect.update(0.5)
    assert len(effect) == 25
