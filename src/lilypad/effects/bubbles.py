"""Glossy interactive bubbles that rise, sway, and pop into droplets.

Implements VISUAL_REVIEW.md recommendation #1: translucent glossy bubble
sprites, cached per radius bucket on ``SRCALPHA`` surfaces so nothing is
rebuilt per frame, rising from the bottom edge with a gentle sway. Any
caller (a new effect landing nearby, a direct keypress) can pop bubbles via
``pop_near`` — pops spray a small internal shower of droplet particles so
the effect looks juicy even if the caller ignores the returned positions.
"""

from __future__ import annotations

import math

import pygame

from .base import EffectContext
from .particles import Particle, ParticleSystem

_BUCKET = 4  # px — radius bucketing step, keeps the sprite cache tiny
_FADE_TIME = 0.5  # seconds of alpha fade before a bubble's natural death

_sprite_cache: dict[int, pygame.Surface] = {}

# Light, glassy blues/whites — a droplet/bubble color is picked per bubble
# at spawn time (distinct from the saturated BRIGHT_PALETTE used elsewhere).
_DROPLET_COLORS: list[tuple[int, int, int]] = [
    (173, 216, 230),
    (200, 235, 255),
    (135, 206, 250),
    (224, 247, 255),
    (255, 255, 255),
]


def bubble_sprite(radius: int) -> pygame.Surface:
    """Cached glossy translucent bubble sprite, bucketed to steps of 4 px.

    Radii are bucketed *inside* this function (not by the caller) so the
    cache stays small regardless of how many distinct spawn radii exist.
    The caller blits the returned sprite centered on the bubble's real
    position; the couple-pixel mismatch between requested and bucketed
    radius is invisible on screen.
    """
    bucket = max(_BUCKET, (int(radius) // _BUCKET) * _BUCKET)
    cached = _sprite_cache.get(bucket)
    if cached is not None:
        return cached

    size = bucket * 2 + 4  # small margin so the rim isn't clipped
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    center = size // 2

    # Faint bluish-white body fill.
    pygame.draw.circle(surf, (200, 230, 255, 40), (center, center), bucket)
    # Brighter rim.
    rim_width = 3 if bucket >= 12 else 2
    pygame.draw.circle(surf, (230, 245, 255, 165), (center, center), bucket, rim_width)
    # Off-center specular highlight (upper-left).
    hl_r = max(2, bucket // 4)
    pygame.draw.circle(surf, (255, 255, 255, 210),
                        (center - bucket // 2, center - bucket // 2), hl_r)
    # Tiny secondary glint, above/right of the main highlight.
    glint_r = max(1, bucket // 8)
    pygame.draw.circle(surf, (255, 255, 255, 170),
                        (center - bucket // 4, center - int(bucket * 0.7)), glint_r)

    surf = surf.convert_alpha()
    _sprite_cache[bucket] = surf
    return surf


class _Bubble:
    """A single rising bubble. Plain attribute bag, owned by BubbleField."""

    __slots__ = ("x", "y", "vy", "radius", "sway_phase", "sway_amp", "life", "age", "color")

    def __init__(self, x: float, y: float, vy: float, radius: float,
                 sway_phase: float, sway_amp: float, life: float,
                 color: tuple[int, int, int]) -> None:
        self.x = x
        self.y = y
        self.vy = vy
        self.radius = radius
        self.sway_phase = sway_phase
        self.sway_amp = sway_amp
        self.life = life
        self.age = 0.0
        self.color = color


class BubbleField:
    """A flotilla of glossy bubbles that rise, sway, and can be popped.

    Bubbles die by floating above the top edge, by running past their
    lifespan (fading over their last 0.5 s), or by being popped via
    ``pop_near``. Popped bubbles always spawn a small internal spray of
    droplet particles regardless of whether the caller uses the returned
    positions.
    """

    def __init__(self, ctx: EffectContext, count: int = 8) -> None:
        self.ctx = ctx
        self.bubbles: list[_Bubble] = []
        self.droplets = ParticleSystem()
        for _ in range(max(3, int(count * ctx.scale))):
            self._spawn()

    def _spawn(self) -> None:
        ctx = self.ctx
        radius = ctx.rng.uniform(18, 48)
        self.bubbles.append(_Bubble(
            x=ctx.rng.uniform(radius, max(radius, ctx.width - radius)),
            y=ctx.height + radius + ctx.rng.uniform(0, 40),
            vy=-ctx.rng.uniform(60, 140),
            radius=radius,
            sway_phase=ctx.rng.uniform(0, math.tau),
            sway_amp=ctx.rng.uniform(15, 40),
            life=ctx.rng.uniform(8.0, 14.0),
            color=ctx.rng.choice(_DROPLET_COLORS),
        ))

    def update(self, dt: float) -> bool:
        alive: list[_Bubble] = []
        for b in self.bubbles:
            b.age += dt
            b.y += b.vy * dt
            b.x += math.sin(b.age * 1.3 + b.sway_phase) * b.sway_amp * dt
            if b.y + b.radius < 0:
                continue  # floated above the top edge
            if b.age >= b.life:
                continue  # outlived its lifespan
            alive.append(b)
        self.bubbles = alive
        self.droplets.update(dt)
        return bool(self.bubbles) or bool(len(self.droplets))

    def draw(self, surface: pygame.Surface) -> None:
        for b in self.bubbles:
            sprite = bubble_sprite(int(b.radius))
            remaining = b.life - b.age
            if remaining < _FADE_TIME:
                alpha = max(0, int(255 * (remaining / _FADE_TIME)))
                sprite = sprite.copy()
                sprite.set_alpha(alpha)
            rect = sprite.get_rect(center=(int(b.x), int(b.y)))
            surface.blit(sprite, rect)
        self.droplets.draw(surface)

    def pop_near(self, pos: tuple[float, float],
                 radius: float) -> list[tuple[float, float, tuple[int, int, int]]]:
        """Pop every bubble within (radius + bubble radius) of pos.

        Removes the popped bubbles, sprays each into a small internal
        droplet burst, and returns their (x, y, color) so the caller can
        optionally spawn its own effects (e.g. a bigger droplet burst) too.
        """
        px, py = pos
        popped: list[tuple[float, float, tuple[int, int, int]]] = []
        remaining: list[_Bubble] = []
        for b in self.bubbles:
            if math.hypot(b.x - px, b.y - py) <= radius + b.radius:
                popped.append((b.x, b.y, b.color))
                self._spray(b)
            else:
                remaining.append(b)
        self.bubbles = remaining
        return popped

    def _spray(self, b: _Bubble) -> None:
        ctx = self.ctx
        for _ in range(ctx.rng.randint(6, 8)):
            ang = ctx.rng.uniform(0, math.tau)
            spd = ctx.rng.uniform(60, 180)
            self.droplets.particles.append(Particle(
                x=b.x, y=b.y,
                vx=math.cos(ang) * spd, vy=math.sin(ang) * spd - 40,
                life=ctx.rng.uniform(0.3, 0.6),
                color=b.color,
                size=ctx.rng.uniform(2, 4),
                gravity=260.0, drag=0.8,
            ))

    def __len__(self) -> int:
        return len(self.bubbles) + len(self.droplets)
