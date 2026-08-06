import random

import pygame

from lilypad.effects import glow


def setup_function(_fn):
    glow.clear_cache()


def _channel_sum(color) -> int:
    return int(color[0]) + int(color[1]) + int(color[2])


def test_bucket_radius_boundaries():
    assert glow._bucket_radius(0) == 2      # below min clamps up
    assert glow._bucket_radius(1) == 2
    assert glow._bucket_radius(2) == 2
    assert glow._bucket_radius(3) == 4      # rounds half-up to next even step
    assert glow._bucket_radius(4) == 4
    assert glow._bucket_radius(5) == 6
    assert glow._bucket_radius(30) == 30
    assert glow._bucket_radius(31) == 32
    assert glow._bucket_radius(32) == 32
    assert glow._bucket_radius(100) == 32   # above max clamps down
    assert glow._bucket_radius(-50) == 2    # negative clamps to min


def test_quantize_channel_boundaries():
    assert glow._quantize_channel(0) == 0
    assert glow._quantize_channel(31) == 0
    assert glow._quantize_channel(32) == 32
    assert glow._quantize_channel(63) == 32
    assert glow._quantize_channel(64) == 64
    assert glow._quantize_channel(255) == 224
    assert glow._quantize_channel(-10) == 0     # clamps low
    assert glow._quantize_channel(999) == 224   # clamps high then floors


def test_glow_sprite_caching_identity():
    a = glow.glow_sprite((10, 10, 10), 2)
    b = glow.glow_sprite((20, 20, 20), 2)   # same quantization bucket (both -> 0)
    assert a is b

    c = glow.glow_sprite((32, 32, 32), 2)   # crosses a quantization boundary
    assert c is not a

    d = glow.glow_sprite((10, 10, 10), 10)  # different radius bucket
    assert d is not a

    # Re-requesting the original key still returns the same cached object.
    e = glow.glow_sprite((10, 10, 10), 2)
    assert e is a


def test_glow_sprite_size_matches_bucketed_radius():
    sprite = glow.glow_sprite((100, 100, 100), 7)   # 7 -> bucket 8
    assert sprite.get_size() == (32, 32)            # side == 4 * bucketed radius


def test_glow_sprite_is_plain_rgb_not_srcalpha():
    sprite = glow.glow_sprite((200, 50, 50), 16)
    assert not (sprite.get_flags() & pygame.SRCALPHA)


def test_glow_sprite_brighter_at_center_than_edge_and_corners_near_black():
    sprite = glow.glow_sprite((255, 60, 60), 16)
    w, h = sprite.get_size()
    center = sprite.get_at((w // 2, h // 2))
    edge = sprite.get_at((w // 2, 1))
    corner = sprite.get_at((0, 0))

    assert _channel_sum(center) > _channel_sum(edge)
    assert _channel_sum(edge) > _channel_sum(corner)
    assert _channel_sum(corner) < 10   # near-black


def test_draw_glow_brightens_pixel_and_is_additive():
    surface = pygame.Surface((64, 64))
    surface.fill((0, 0, 0))
    pos = (32, 32)

    before = _channel_sum(surface.get_at((32, 32)))
    glow.draw_glow(surface, (255, 255, 255), pos, 8)
    after_once = _channel_sum(surface.get_at((32, 32)))
    assert after_once > before

    glow.draw_glow(surface, (255, 255, 255), pos, 8)
    after_twice = _channel_sum(surface.get_at((32, 32)))
    assert after_twice >= after_once   # additive blend, may clamp at white


def test_draw_glow_clamps_tiny_and_huge_radii_without_crash():
    surface = pygame.Surface((64, 64))
    glow.draw_glow(surface, (10, 20, 30), (5, 5), 0)
    glow.draw_glow(surface, (10, 20, 30), (5, 5), -100)
    glow.draw_glow(surface, (10, 20, 30), (5, 5), 0.3)
    glow.draw_glow(surface, (10, 20, 30), (5, 5), 9999)
    # Off-surface position should also be safe (no crash / no OOB blit error).
    glow.draw_glow(surface, (10, 20, 30), (-500, -500), 12)


def test_cache_size_stays_bounded():
    rng = random.Random(42)
    for _ in range(5000):
        color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        radius = rng.uniform(-50, 500)
        glow.glow_sprite(color, radius)

    # 256 // 32 == 8 values per channel -> 8**3 == 512 quantized colors;
    # (32 - 2) // 2 + 1 == 16 radius buckets. Upper bound is their product.
    assert len(glow._cache) <= 512 * 16
    assert len(glow._cache) > 0


def test_clear_cache_empties_and_new_calls_rebuild():
    glow.glow_sprite((1, 2, 3), 4)
    assert len(glow._cache) > 0
    glow.clear_cache()
    assert len(glow._cache) == 0
    glow.glow_sprite((1, 2, 3), 4)
    assert len(glow._cache) == 1
