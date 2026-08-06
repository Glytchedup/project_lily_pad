"""Additive glow rendering for particles (VISUAL_REVIEW.md recommendation #3).

Replaces flat ``pygame.draw.circle`` particle dots with a pre-rendered
radial-gradient sprite blitted with ``special_flags=pygame.BLEND_ADD``.
Overlapping glows sum toward white instead of stacking as flat confetti.

Per-call cost for ``draw_glow`` is exactly one dict lookup (cache hit) plus
one blit — sprite construction only ever happens once per (quantized color,
bucketed radius) pair, at whatever moment that pair is first requested.

Cache bound: colors are quantized to 32-wide steps per channel, giving
256 // 32 == 8 possible values per channel, so 8**3 == 512 distinct
quantized colors. Radii are bucketed to even steps between 2 and 32,
giving (32 - 2) // 2 + 1 == 16 distinct buckets. So the cache can never
hold more than 512 * 16 == 8192 tiny surfaces, however many arbitrarily
faded particle colors the effects layer throws at it — bounded, small
(each sprite is at most 128x128 px), and independent of runtime.
"""

from __future__ import annotations

import pygame

_MIN_RADIUS = 2
_MAX_RADIUS = 32
_RADIUS_STEP = 2
_COLOR_STEP = 32

# (quantized color, bucketed radius) -> pre-rendered glow sprite.
_cache: dict[tuple[tuple[int, int, int], int], pygame.Surface] = {}


def _quantize_channel(value: int) -> int:
    """Floor a single 0-255 channel to the nearest 32-wide step."""
    clamped = max(0, min(255, int(value)))
    return (clamped // _COLOR_STEP) * _COLOR_STEP


def _quantize_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = color
    return (_quantize_channel(r), _quantize_channel(g), _quantize_channel(b))


def _bucket_radius(radius: float) -> int:
    """Clamp to [2, 32] and round to the nearest even step of 2."""
    clamped = max(float(_MIN_RADIUS), min(float(_MAX_RADIUS), float(radius)))
    # Round-half-up on whole-step boundaries (avoids banker's-rounding
    # surprises from the builtin round()) then re-clamp for safety.
    bucket = int((clamped + 1.0) // _RADIUS_STEP) * _RADIUS_STEP
    return max(_MIN_RADIUS, min(_MAX_RADIUS, bucket))


def _build_sprite(color: tuple[int, int, int], radius: int) -> pygame.Surface:
    """Draw a radial gradient by painting concentric circles outside-in.

    Plain RGB surface (no SRCALPHA) on a black background: blitted with
    BLEND_ADD, black contributes nothing, so only the painted gradient
    shows through and overlapping sprites sum toward white. The sprite is
    4x the bucketed radius on a side so the soft glow has room to breathe
    past the particle's nominal radius instead of hard-clipping at it.
    """
    side = 4 * radius
    sprite = pygame.Surface((side, side))
    sprite.fill((0, 0, 0))
    center = side / 2.0
    max_r = side / 2.0
    steps = radius  # ~radius concentric circles; init-time only, cheap.

    for i in range(steps, 0, -1):
        outer_t = i / steps            # 1.0 at the outer edge, shrinking inward
        core_t = (1.0 - outer_t) ** 1.6  # eased: ~0 at edge, ~1 near the core
        r = max(1, round(max_r * outer_t))
        blended = tuple(
            max(0, min(255, round(
                (ch * 0.12) + (min(255, ch + (255 - ch) * 0.92) - ch * 0.12) * core_t
            )))
            for ch in color
        )
        pygame.draw.circle(sprite, blended, (int(center), int(center)), r)

    return sprite.convert()


def glow_sprite(color: tuple[int, int, int], radius: int) -> pygame.Surface:
    """Return the cached glow sprite for (quantized color, bucketed radius).

    Builds and caches it on first request; every later call with a color/
    radius that quantizes to the same bucket returns the same object.
    """
    key = (_quantize_color(color), _bucket_radius(radius))
    sprite = _cache.get(key)
    if sprite is None:
        sprite = _build_sprite(*key)
        _cache[key] = sprite
    return sprite


def draw_glow(surface: pygame.Surface, color: tuple[int, int, int],
              pos: tuple[float, float], radius: float) -> None:
    """Blit the cached glow sprite for `color`/`radius`, centered at `pos`.

    One dict-lookup (via glow_sprite) and one additive blit — nothing else.
    """
    sprite = glow_sprite(color, radius)
    half_w = sprite.get_width() // 2
    half_h = sprite.get_height() // 2
    dest = (int(pos[0]) - half_w, int(pos[1]) - half_h)
    surface.blit(sprite, dest, special_flags=pygame.BLEND_ADD)


def clear_cache() -> None:
    """Drop all cached sprites (tests only)."""
    _cache.clear()
