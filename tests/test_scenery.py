import random

import pygame

from lilypad.effects.base import EffectContext
from lilypad.effects.scenery import PondBackground

SENTINEL = (1, 2, 3)


def ctx(size=(640, 480), seed=1234):
    return EffectContext(size=size, rng=random.Random(seed))


def test_construction_at_a_couple_sizes():
    for size in ((640, 480), (1280, 720)):
        pond = PondBackground(ctx(size=size))
        assert len(pond) > 0


def test_update_always_true():
    pond = PondBackground(ctx())
    for _ in range(10):
        assert pond.update(1 / 60) is True


def test_draw_fills_screen_opaquely():
    size = (640, 480)
    pond = PondBackground(ctx(size=size))
    surface = pygame.Surface(size)
    surface.fill(SENTINEL)
    pond.draw(surface)
    w, h = size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for corner in corners:
        assert surface.get_at(corner)[:3] != SENTINEL


def test_variant_crossfade_executes_without_crash():
    size = (320, 240)
    pond = PondBackground(ctx(size=size))
    surface = pygame.Surface(size)

    # Cross the 300s variant-cycle threshold in small steps so the
    # mid-crossfade draw path (extra alpha-blended blit) actually runs.
    for _ in range(310):
        pond.update(1.0)
        pond.draw(surface)

    # And a big single dt that jumps straight through a whole crossfade.
    pond.update(500.0)
    pond.draw(surface)


def test_len_positive():
    pond = PondBackground(ctx())
    assert len(pond) > 0


def test_deterministic_star_layout_with_seeded_rng():
    pond_a = PondBackground(ctx(seed=42))
    pond_b = PondBackground(ctx(seed=42))

    for variant_a, variant_b in zip(pond_a._variants, pond_b._variants):
        assert variant_a.stars == variant_b.stars
        assert variant_a.twinkle_idx == variant_b.twinkle_idx
        assert variant_a.twinkle_phases == variant_b.twinkle_phases

    assert pond_a._lily_pads == pond_b._lily_pads


def test_different_seed_gives_different_star_layout():
    pond_a = PondBackground(ctx(seed=1))
    pond_b = PondBackground(ctx(seed=2))
    assert pond_a._variants[0].stars != pond_b._variants[0].stars
