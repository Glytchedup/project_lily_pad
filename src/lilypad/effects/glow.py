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
giving (32 - 2) // 2 + 1 == 16 distinct buckets, for a theoretical
ceiling of 512 * 16 == 8192 sprites. In practice the ceiling is far
lower: nothing in the effects layer spawns particles bigger than ~9 px,
so only the 2-10 px buckets are reachable (~2560 sprites of <= 40x40 px,
a few MB worst case; measured soaks stabilize under ~1500 entries).

Painted FX have a separate, startup-only cache. set_fx_style selects the
asset root and painted_sprite returns the frames for a particle's lifetime.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import logging
from pathlib import Path
import tomllib

import pygame

from . import assets
from .base import BRIGHT_PALETTE

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
        # Core pushes only ~45% toward white: enough for a hot center, while
        # a single particle still clearly reads as its palette color. (An
        # earlier 92% push made every core near-white — review measured 71%
        # of burst pixels colorless and the fade curve flattened to nothing;
        # true white now only appears where glows OVERLAP and BLEND_ADD sums.)
        blended = tuple(
            max(0, min(255, round(
                (ch * 0.12) + (min(255, ch + (255 - ch) * 0.45) - ch * 0.12) * core_t
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


# Longest side in screen pixels. Quarter turns preserve the texel count.
_FX_SIZES = {
    "star": (8, 14, 20), "petal": (10, 16, 22), "leaf": (10, 16, 22),
    "heart": (8, 14, 20), "bubble": (40, 68, 96), "bokeh": (24, 40, 56),
    "balloon": (56, 84), "glint": (6, 10, 14),
}
_FX_BYTE_LIMIT = 4_000_000
_Color = tuple[int, int, int]
_WHITE = (255, 255, 255)
_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PaintedSprite:
    """One file and tint, with every size and orientation ready to blit."""

    frames: tuple[tuple[pygame.Surface, ...], ...]
    midpoints: tuple[int, ...]
    flags: int

    def frame(self, diameter: float, turn: int = 0) -> pygame.Surface:
        angles = self.frames[bisect_left(self.midpoints, diameter)]
        return angles[turn % len(angles)]

    def draw(self, target: pygame.Surface, x: float, y: float, diameter: float,
             turn: int = 0) -> None:
        frame = self.frame(diameter, turn)
        target.blit(frame, frame.get_rect(center=(int(x), int(y))), special_flags=self.flags)


# kind -> palette colour (or None for untinted art) -> file variants.
_painted: dict[str, dict[_Color | None, list[PaintedSprite]]] = {}


def _cache_file(directory: Path, kind: str, filename: str, tint: bool, blend: str,
                remaining: int) -> int:
    path = Path(filename)
    if (path.anchor or ".." in path.parts or path.suffix.lower() not in (".png", ".webp")):
        raise ValueError("invalid FX frame path")
    image = assets.load_image(directory / path)
    w, h = image.get_size()
    longest = max(w, h)
    if not 0 < longest <= 128:
        raise ValueError("FX frame exceeds 128 px")
    # Keep a known 32-bit alpha format even when warming before a display exists.
    if image.get_bitsize() != 32 or not image.get_masks()[3]:
        rgba = pygame.Surface((w, h), pygame.SRCALPHA, 32)
        rgba.blit(image, (0, 0))
        image = rgba
    flags = pygame.BLEND_ADD if blend == "add" else 0
    if flags:
        # RGB addition ignores source alpha. Bake coverage into RGB so hidden
        # white pixels add nothing and soft painted edges keep their falloff.
        image = image.premul_alpha()
    sizes = _FX_SIZES[kind]
    dims = [(max(1, round(w * s / longest)), max(1, round(h * s / longest))) for s in sizes]
    turns = 4 if kind in ("petal", "leaf") else 1
    colors = BRIGHT_PALETTE if tint else (None,)
    cost = sum(width * height * 4 for width, height in dims) * turns * len(colors)
    if cost > remaining:
        return 0
    scaled = [pygame.transform.smoothscale(image, dim) for dim in dims]
    midpoints = tuple((a + b) // 2 for a, b in zip(sizes, sizes[1:]))
    variants = {}
    for color in colors:
        frames = []
        for base in scaled:
            frame = base
            if color is not None:
                frame = base.copy()
                frame.fill(color, special_flags=pygame.BLEND_RGB_MULT)
            frames.append((frame,) + tuple(pygame.transform.rotate(frame, i * 90)
                                           for i in range(1, turns)))
        variants[color] = PaintedSprite(tuple(frames), midpoints, flags)
    # Publish only a complete file, including every palette colour.
    by_color = _painted.setdefault(kind, {})
    for color, variant in variants.items():
        by_color.setdefault(color, []).append(variant)
    return cost


def set_fx_style(mode: str, root: Path | None = None) -> None:
    """Warm painted FX at startup. The asset root contains fx/manifest.toml."""
    if mode not in ("glow", "painted"):
        raise ValueError(f"unknown FX style {mode!r}")
    _painted.clear()
    if mode == "glow":
        return
    directory = (root if root is not None else assets.asset_root()) / "fx"
    try:
        with (directory / "manifest.toml").open("rb") as stream:
            data = tomllib.load(stream)
        rows = data.get("sprites", {})
        if type(data.get("schema")) is not int or data["schema"] != 1 or not isinstance(rows, dict):
            raise ValueError("expected schema 1 and a sprites table")
    except (OSError, ValueError) as exc:
        _log.info("Using glow FX: %s", exc)
        return

    # Give every family its first file before spending space on extra variants.
    files = []
    skipped = 0
    for kind, row in rows.items():
        if (kind not in _FX_SIZES or not isinstance(row, dict)
                or not isinstance(row.get("files"), list) or type(row.get("tint")) is not bool
                or row.get("blend") not in ("add", "alpha")):
            skipped += 1
            continue
        for index, filename in enumerate(row["files"]):
            if isinstance(filename, str):
                files.append((index, kind, filename, row["tint"], row["blend"]))
            else:
                skipped += 1
    remaining = _FX_BYTE_LIMIT
    for _, kind, filename, tint, blend in sorted(files):
        try:
            cost = _cache_file(directory, kind, filename, tint, blend, remaining)
        except (OSError, ValueError, pygame.error, NotImplementedError):
            cost = 0
        remaining -= cost
        if not cost:
            skipped += 1
    if not _painted:
        _log.info("Using glow FX: no usable painted sprites in %s", directory)
    elif skipped:
        _log.info("Painted FX: skipped %d invalid or over-budget entries in %s", skipped, directory)


def painted_sprite(kind: str, variant: int, color: _Color = _WHITE) -> PaintedSprite | None:
    """Choose among prebuilt files. A missing family keeps its procedural effect."""
    colors = _painted.get(kind)
    if not colors:
        return None
    variants = colors.get(None) or colors.get(color)
    if variants is None:
        # Custom burst palettes borrow the nearest prewarmed tint at spawn time.
        nearest = min(BRIGHT_PALETTE, key=lambda c: sum((a - b) ** 2 for a, b in zip(color, c)))
        variants = colors[nearest]
    return variants[variant % len(variants)]
