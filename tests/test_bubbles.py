import random

import pygame

from lilypad.effects.base import EffectContext
from lilypad.effects.bubbles import BubbleField, bubble_sprite


def ctx(scale: float = 1.0, seed: int = 1234) -> EffectContext:
    return EffectContext(size=(640, 480), rng=random.Random(seed), scale=scale)


# ---------------------------------------------------------------- sprite cache

def test_sprite_bucketing_same_bucket_is_identical_object():
    assert bubble_sprite(18) is bubble_sprite(19)


def test_sprite_bucketing_different_bucket_is_different_object():
    assert bubble_sprite(18) is not bubble_sprite(30)


def test_sprite_is_srcalpha_surface():
    sprite = bubble_sprite(24)
    assert isinstance(sprite, pygame.Surface)
    assert sprite.get_flags() & pygame.SRCALPHA


# ---------------------------------------------------------------- spawning

def test_field_spawns_expected_count():
    field = BubbleField(ctx(), count=8)
    assert len(field.bubbles) == 8
    assert len(field) == 8


def test_field_respects_scale():
    full = BubbleField(ctx(scale=1.0), count=8)
    tiny = BubbleField(ctx(scale=0.25), count=8)
    assert len(tiny.bubbles) < len(full.bubbles)


def test_field_spawn_count_has_a_floor():
    field = BubbleField(ctx(scale=0.0), count=8)
    assert len(field.bubbles) >= 3


# ---------------------------------------------------------------- rising / dying

def test_bubbles_rise_over_time():
    field = BubbleField(ctx(), count=5)
    start_ys = [b.y for b in field.bubbles]
    for _ in range(30):
        field.update(1 / 60)
    end_ys = [b.y for b in field.bubbles]
    # Every bubble still alive after half a second must have moved upward.
    assert all(e < s for s, e in zip(start_ys, end_ys))


def test_all_bubbles_eventually_die():
    field = BubbleField(ctx(), count=6)
    surface = pygame.Surface((640, 480))
    alive_frames = 0
    max_frames = 60 * 30  # 30 s safety cap, lives are at most 14 s
    while field.update(1 / 60) and alive_frames < max_frames:
        field.draw(surface)
        alive_frames += 1
    assert alive_frames < max_frames, "bubble field never finished"
    assert len(field) == 0


# ---------------------------------------------------------------- popping

def test_pop_near_only_pops_in_range_bubbles():
    field = BubbleField(ctx(), count=6)
    # Force known, well-separated positions so range checks are unambiguous.
    for i, b in enumerate(field.bubbles):
        b.x, b.y, b.radius = i * 200.0, 100.0, 20.0

    popped = field.pop_near((0.0, 100.0), radius=5.0)

    assert len(popped) == 1
    x, y, color = popped[0]
    assert x == 0.0 and y == 100.0
    assert isinstance(color, tuple) and len(color) == 3
    assert len(field.bubbles) == 5
    # The popped bubble is gone but its droplet spray remains.
    assert len(field.droplets) > 0


def test_pop_near_pops_multiple_in_range():
    field = BubbleField(ctx(), count=6)
    for i, b in enumerate(field.bubbles):
        b.x, b.y, b.radius = i * 10.0, 100.0, 20.0  # tightly clustered

    popped = field.pop_near((0.0, 100.0), radius=1000.0)

    assert len(popped) == 6
    assert len(field.bubbles) == 0


def test_droplets_from_pop_eventually_expire():
    field = BubbleField(ctx(), count=1)  # count floors to 3 bubbles minimum
    for b in list(field.bubbles):
        field.pop_near((b.x, b.y), radius=1.0)
    assert len(field.bubbles) == 0
    assert len(field.droplets) > 0

    alive_frames = 0
    while field.update(1 / 60) and alive_frames < 60 * 10:
        alive_frames += 1
    assert alive_frames < 60 * 10
    assert len(field) == 0
    assert len(field.droplets) == 0


# ---------------------------------------------------------------- draw / __len__

def test_draw_never_crashes_mid_life_or_after_pop():
    field = BubbleField(ctx(), count=6)
    surface = pygame.Surface((640, 480))
    field.draw(surface)  # full life
    field.update(1 / 60)
    field.draw(surface)  # mid life

    b = field.bubbles[0]
    field.pop_near((b.x, b.y), radius=1.0)
    field.draw(surface)  # right after a pop (bubbles + droplets mixed)

    for _ in range(20):
        field.update(1 / 60)
        field.draw(surface)  # through droplet fade-out


def test_len_tracks_bubbles_and_droplets():
    field = BubbleField(ctx(), count=4)
    assert len(field) == len(field.bubbles) + len(field.droplets)

    b = field.bubbles[0]
    field.pop_near((b.x, b.y), radius=1.0)
    assert len(field) == len(field.bubbles) + len(field.droplets)
    assert len(field.droplets) > 0
