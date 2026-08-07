"""A living pond scene — the full-screen background the engine draws first
each frame, in place of the flat ``surface.fill(BACKGROUND)``.

Everything expensive happens once at init: three moody near-black gradient
surfaces (``night`` / ``dusk`` / ``aurora``) are pre-rendered with a baked
crescent moon and starfield, one per variant. Per-frame work stays cheap —
a handful of small circles for twinkling stars and a few sprite blits for
gently swaying lily pads — matching the performance rules in
``particles.py``'s header comment. The three lily-pad sprites are cached
surfaces built once and blitted at a swaying offset each frame rather than
baked into the background, so the sway doesn't need any per-frame redraw of
the pad shape itself.

Variant cycling crossfades every ``_VARIANT_PERIOD_S`` of accumulated
``update(dt)`` time (never wall-clock) over ``_CROSSFADE_S`` seconds, via
``set_alpha`` on the incoming surface — one extra full-screen blit only
while the crossfade is in flight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from .base import EffectContext

VARIANTS: tuple[str, ...] = ("night", "dusk", "aurora")

# Vertical gradient endpoints per variant: (top color, waterline color).
# Kept dark — max channel ~40 — so foreground effects still pop; the aurora
# variant gets an extra teal/green band mixed in up to ~70.
_GRADIENTS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "night": ((6, 8, 16), (14, 22, 36)),
    "dusk": ((10, 6, 18), (26, 16, 38)),
    "aurora": ((6, 10, 14), (10, 26, 30)),
}

_MOON_COLOR = (232, 232, 214)
_STAR_COLOR = (215, 220, 235)
_PAD_DARK = (18, 62, 40)
_PAD_RIM = (34, 96, 58)
_LOTUS_PINK = (219, 112, 147)
_LOTUS_PINK_LIGHT = (255, 182, 200)

_STAR_COUNT = 30
_TWINKLE_COUNT = 10
_LILY_COUNT = 3
_VARIANT_PERIOD_S = 300.0
_CROSSFADE_S = 4.0


def _lerp_color(a: tuple[int, int, int], b: tuple[int, int, int],
                 t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _gen_stars(rng, w: int, h: int, count: int) -> list[dict]:
    stars = []
    for _ in range(count):
        stars.append({
            "x": rng.uniform(0, w),
            "y": rng.uniform(0, h * 0.6),
            "r": rng.choice((1, 1, 2, 2, 3)),
        })
    return stars


def _gen_sky_layout(rng, w: int, h: int) -> dict:
    """Moon position, starfield, and twinkle selection — generated ONCE and
    shared by all three variants, so the crossfade blends one sky into
    different light rather than showing two moons and two starfields."""
    stars = _gen_stars(rng, w, h, _STAR_COUNT)
    order = list(range(len(stars)))
    rng.shuffle(order)
    return {
        "moon": (int(w * rng.uniform(0.70, 0.86)),
                 int(h * rng.uniform(0.10, 0.22)),
                 max(14, int(h * 0.045))),
        "stars": stars,
        "twinkle_idx": order[:min(_TWINKLE_COUNT, len(stars))],
        "twinkle_phases": [rng.uniform(0, math.tau) for _ in range(
            min(_TWINKLE_COUNT, len(stars)))],
    }


def _draw_moon(surf: pygame.Surface, moon: tuple[int, int, int], h: int,
                top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    cx, cy, r = moon
    pygame.draw.circle(surf, _MOON_COLOR, (cx, cy), r)
    # Crescent trick: overlay a second circle painted in the local gradient
    # color to bite a chunk out of the disc.
    bite_color = _lerp_color(top, bottom, cy / h)
    offset = int(r * 0.55)
    pygame.draw.circle(surf, bite_color, (cx + offset, cy - int(offset * 0.3)), int(r * 0.92))


@dataclass
class _Variant:
    name: str
    surface: pygame.Surface
    stars: list[dict]
    twinkle_idx: list[int]
    twinkle_phases: list[float]


def _build_variant(size: tuple[int, int], name: str, layout: dict) -> _Variant:
    w, h = size
    top, bottom = _GRADIENTS[name]
    surf = pygame.Surface(size).convert()

    strip = max(2, h // 80)
    band_center = h * 0.32
    band_half = h * 0.10
    y = 0
    while y < h:
        t = y / h
        color = _lerp_color(top, bottom, t)
        if name == "aurora":
            dist = abs((y + strip / 2) - band_center)
            if dist < band_half:
                boost = 1.0 - dist / band_half
                color = (
                    color[0],
                    min(70, int(color[1] + 55 * boost)),
                    min(70, int(color[2] + 40 * boost)),
                )
        pygame.draw.rect(surf, color, (0, y, w, strip))
        y += strip

    _draw_moon(surf, layout["moon"], h, top, bottom)

    stars = layout["stars"]
    for s in stars:
        pygame.draw.circle(surf, _STAR_COLOR, (int(s["x"]), int(s["y"])), s["r"])

    return _Variant(name=name, surface=surf, stars=stars,
                     twinkle_idx=layout["twinkle_idx"],
                     twinkle_phases=layout["twinkle_phases"])


def _build_lily_sprite(r: float, lotus: bool) -> pygame.Surface:
    """One cached SRCALPHA lily-pad sprite: dark green ellipse, lighter
    rim, and a pie-notch cut to transparent (drawing alpha 0 directly
    overwrites the pixel alpha — the standard pygame.draw cutout trick)."""
    rw = max(10, int(r))
    rh = max(6, int(r * 0.6))
    pad = 4
    size = (rw * 2 + pad * 2, rh * 2 + pad * 2)
    sprite = pygame.Surface(size, pygame.SRCALPHA)
    cx, cy = size[0] // 2, size[1] // 2
    rect = pygame.Rect(0, 0, rw * 2, rh * 2)
    rect.center = (cx, cy)
    pygame.draw.ellipse(sprite, _PAD_DARK, rect)
    pygame.draw.ellipse(sprite, _PAD_RIM, rect, max(1, rw // 12))

    notch_half = max(4, int(rh * 0.25))
    notch = [(cx, cy), (cx + rw + pad, cy - notch_half), (cx + rw + pad, cy + notch_half)]
    pygame.draw.polygon(sprite, (0, 0, 0, 0), notch)

    if lotus:
        fx, fy = cx - rw // 3, cy - int(rh * 0.5)
        pygame.draw.circle(sprite, _LOTUS_PINK, (fx, fy), max(4, rw // 4))
        pygame.draw.circle(sprite, _LOTUS_PINK_LIGHT, (fx, fy), max(2, rw // 7))

    return sprite.convert_alpha()


def _gen_lily_pads(rng, w: int, h: int, count: int) -> list[dict]:
    lotus_i = rng.randrange(count)
    pads = []
    for i in range(count):
        frac = 0.18 + 0.64 * (i / max(1, count - 1))
        x = frac * w + rng.uniform(-0.04, 0.04) * w
        r = rng.uniform(0.035, 0.055) * h
        # Center sits roughly one pad-half-height above the edge so most of
        # the pad (and the lotus) is actually visible, not a bottom sliver.
        y = h - r * 0.6 - rng.uniform(0.0, 0.015) * h
        pads.append({
            "x": x, "y": y, "r": r,
            "phase": rng.uniform(0, math.tau),
            "lotus": i == lotus_i,
        })
    return pads


class PondBackground:
    """Persistent full-screen background — the engine owns exactly one and
    draws it before anything else each frame (update() always True)."""

    def __init__(self, ctx: EffectContext) -> None:
        self.ctx = ctx
        w, h = ctx.size
        self._w, self._h = w, h

        layout = _gen_sky_layout(ctx.rng, w, h)   # one sky, three lights
        self._variants: list[_Variant] = [
            _build_variant((w, h), name, layout) for name in VARIANTS
        ]

        self._lily_pads = _gen_lily_pads(ctx.rng, w, h, _LILY_COUNT)
        self._lily_sprites = [
            _build_lily_sprite(p["r"], p["lotus"]) for p in self._lily_pads
        ]

        self._index = 0
        self._next_index = 1 % len(self._variants)
        self._time_in_variant = 0.0
        self._crossfading = False
        self._crossfade_elapsed = 0.0
        self._age = 0.0

    def update(self, dt: float) -> bool:
        self._age += dt
        self._time_in_variant += dt

        if not self._crossfading and self._time_in_variant >= _VARIANT_PERIOD_S:
            self._crossfading = True
            self._crossfade_elapsed = 0.0
            self._next_index = (self._index + 1) % len(self._variants)

        if self._crossfading:
            self._crossfade_elapsed += dt
            if self._crossfade_elapsed >= _CROSSFADE_S:
                self._crossfading = False
                self._index = self._next_index
                self._time_in_variant = 0.0

        return True  # persistent; the engine owns it

    def draw(self, surface: pygame.Surface) -> None:
        current = self._variants[self._index]
        surface.blit(current.surface, (0, 0))

        active = current
        if self._crossfading:
            incoming = self._variants[self._next_index]
            alpha = int(255 * min(1.0, self._crossfade_elapsed / _CROSSFADE_S))
            incoming.surface.set_alpha(alpha)
            surface.blit(incoming.surface, (0, 0))
            incoming.surface.set_alpha(255)
            if alpha > 127:
                active = incoming

        self._draw_twinkles(surface, active)
        self._draw_lily_pads(surface)

    def _draw_twinkles(self, surface: pygame.Surface, variant: _Variant) -> None:
        for pos, star_idx in enumerate(variant.twinkle_idx):
            star = variant.stars[star_idx]
            phase = variant.twinkle_phases[pos]
            b = 0.5 + 0.5 * math.sin(self._age * 2.2 + phase)
            color = tuple(min(255, int(c * (0.4 + 0.9 * b))) for c in _STAR_COLOR)
            pygame.draw.circle(surface, color, (int(star["x"]), int(star["y"])), star["r"] + 1)

    def _draw_lily_pads(self, surface: pygame.Surface) -> None:
        for pad, sprite in zip(self._lily_pads, self._lily_sprites):
            sway_x = math.sin(self._age * 0.6 + pad["phase"]) * pad["r"] * 0.15
            sway_y = math.cos(self._age * 0.4 + pad["phase"]) * pad["r"] * 0.06
            rect = sprite.get_rect(center=(int(pad["x"] + sway_x), int(pad["y"] + sway_y)))
            surface.blit(sprite, rect)

    def __len__(self) -> int:
        return 10
