"""Particle primitives. Most named effects are parametrizations of these.

Everything is plain pygame.draw circles/polys — no per-pixel Python loops,
so a Pi GPU-composited 1080p frame stays inside the 60 fps budget with the
default particle caps (engine degrades caps if not).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from .base import BRIGHT_PALETTE, EffectContext, random_bright


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: tuple[int, int, int]
    size: float
    gravity: float = 0.0
    drag: float = 0.0
    age: float = 0.0

    def step(self, dt: float) -> bool:
        self.age += dt
        if self.age >= self.life:
            return False
        if self.drag:
            damp = max(0.0, 1.0 - self.drag * dt)
            self.vx *= damp
            self.vy *= damp
        self.vy += self.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        return True


class ParticleSystem:
    """One effect instance owning a list of particles."""

    def __init__(self) -> None:
        self.particles: list[Particle] = []

    def __len__(self) -> int:
        return len(self.particles)

    def update(self, dt: float) -> bool:
        self.particles = [p for p in self.particles if p.step(dt)]
        return bool(self.particles)

    def draw(self, surface: pygame.Surface) -> None:
        for p in self.particles:
            fade = 1.0 - p.age / p.life
            r = max(1, int(p.size * (0.4 + 0.6 * fade)))
            color = tuple(int(c * (0.35 + 0.65 * fade)) for c in p.color)
            pygame.draw.circle(surface, color, (int(p.x), int(p.y)), r)


def burst(ctx: EffectContext, pos: tuple[float, float], count: int = 60,
          colors: list[tuple[int, int, int]] | None = None,
          speed: float = 420.0, gravity: float = 380.0,
          size: float = 7.0, life: float = 1.2) -> ParticleSystem:
    """Radial explosion — the workhorse."""
    sys_ = ParticleSystem()
    n = max(4, int(count * ctx.scale))
    palette = colors or BRIGHT_PALETTE
    for _ in range(n):
        ang = ctx.rng.uniform(0, math.tau)
        spd = ctx.rng.uniform(0.25, 1.0) * speed
        sys_.particles.append(Particle(
            x=pos[0], y=pos[1],
            vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
            life=ctx.rng.uniform(0.6, 1.0) * life,
            color=ctx.rng.choice(palette),
            size=ctx.rng.uniform(0.6, 1.3) * size,
            gravity=gravity, drag=1.2,
        ))
    return sys_


def confetti_rain(ctx: EffectContext, count: int = 140) -> ParticleSystem:
    """Full-width falling confetti (spacebar)."""
    sys_ = ParticleSystem()
    n = max(8, int(count * ctx.scale))
    for _ in range(n):
        sys_.particles.append(Particle(
            x=ctx.rng.uniform(0, ctx.width), y=ctx.rng.uniform(-ctx.height * 0.3, 0),
            vx=ctx.rng.uniform(-40, 40), vy=ctx.rng.uniform(160, 420),
            life=ctx.rng.uniform(1.2, 2.4),
            color=random_bright(ctx.rng),
            size=ctx.rng.uniform(4, 9),
            gravity=140.0,
        ))
    return sys_


def rising_balloons(ctx: EffectContext, count: int = 10) -> "Balloons":
    return Balloons(ctx, count)


class Balloons:
    """Gentle rising balloons with strings (F-keys)."""

    def __init__(self, ctx: EffectContext, count: int) -> None:
        self._h = ctx.height
        self.parts: list[Particle] = []
        for _ in range(max(3, int(count * ctx.scale))):
            self.parts.append(Particle(
                x=ctx.rng.uniform(ctx.width * 0.1, ctx.width * 0.9),
                y=ctx.height + ctx.rng.uniform(0, ctx.height * 0.4),
                vx=ctx.rng.uniform(-25, 25), vy=-ctx.rng.uniform(120, 240),
                life=6.0, color=random_bright(ctx.rng),
                size=ctx.rng.uniform(26, 44),
            ))

    def update(self, dt: float) -> bool:
        alive: list[Particle] = []
        for p in self.parts:
            p.step(dt)
            p.x += math.sin(p.age * 2.2) * 20 * dt   # sway
            if p.y + p.size > -80 and p.age < p.life:
                alive.append(p)
        self.parts = alive
        return bool(alive)

    def draw(self, surface: pygame.Surface) -> None:
        for p in self.parts:
            x, y, r = int(p.x), int(p.y), int(p.size)
            pygame.draw.line(surface, (200, 200, 200), (x, y + r), (x, y + r + 40), 2)
            pygame.draw.ellipse(surface, p.color, (x - r, y - int(r * 1.15), r * 2, int(r * 2.3)))
            hl = max(2, r // 4)
            pygame.draw.circle(surface, (255, 255, 255), (x - r // 3, y - r // 2), hl)

    def __len__(self) -> int:
        return len(self.parts)


class Rings:
    """Expanding concentric rings (drum / media keys, chord flash)."""

    def __init__(self, ctx: EffectContext, pos: tuple[float, float],
                 color: tuple[int, int, int] | None = None,
                 count: int = 3, life: float = 0.9) -> None:
        self.pos = pos
        self.color = color or random_bright(ctx.rng)
        self.count = count
        self.life = life
        self.age = 0.0
        self.max_r = max(ctx.width, ctx.height) * 0.6

    def update(self, dt: float) -> bool:
        self.age += dt
        return self.age < self.life

    def draw(self, surface: pygame.Surface) -> None:
        t = self.age / self.life
        for i in range(self.count):
            rt = t - i * 0.12
            if not 0.0 < rt < 1.0:
                continue
            radius = int(rt * self.max_r)
            width = max(2, int(14 * (1 - rt)))
            color = tuple(int(c * (1 - rt)) for c in self.color)
            if radius > width:
                pygame.draw.circle(surface, color,
                                   (int(self.pos[0]), int(self.pos[1])), radius, width)

    def __len__(self) -> int:
        return self.count


class Fireworks:
    """Rockets that climb then explode (Enter)."""

    @dataclass
    class _Rocket:
        x: float
        y: float
        vy: float
        fuse: float
        color: tuple[int, int, int]
        age: float = 0.0
        exploded: bool = False

    def __init__(self, ctx: EffectContext, rockets: int = 3) -> None:
        self.ctx = ctx
        self.rockets: list[Fireworks._Rocket] = []
        self.bursts: list[ParticleSystem] = []
        for i in range(max(1, rockets)):
            self.rockets.append(self._Rocket(
                x=ctx.rng.uniform(ctx.width * 0.2, ctx.width * 0.8),
                y=ctx.height + 10,
                vy=-ctx.rng.uniform(0.9, 1.25) * ctx.height * 0.85,
                fuse=ctx.rng.uniform(0.55, 0.95) + i * 0.18,
                color=random_bright(ctx.rng),
            ))

    def update(self, dt: float) -> bool:
        for r in self.rockets:
            if r.exploded:
                continue
            r.age += dt
            r.y += r.vy * dt
            r.vy += 300 * dt
            if r.age >= r.fuse:
                r.exploded = True
                self.bursts.append(burst(
                    self.ctx, (r.x, r.y), count=90,
                    colors=[r.color, (255, 255, 255)],
                    speed=520, gravity=300, size=6, life=1.4,
                ))
        self.bursts = [b for b in self.bursts if b.update(dt)]
        return bool(self.bursts) or any(not r.exploded for r in self.rockets)

    def draw(self, surface: pygame.Surface) -> None:
        for r in self.rockets:
            if not r.exploded:
                pygame.draw.circle(surface, (255, 240, 200), (int(r.x), int(r.y)), 5)
                pygame.draw.line(surface, (255, 160, 60),
                                 (int(r.x), int(r.y) + 6), (int(r.x), int(r.y) + 22), 3)
        for b in self.bursts:
            b.draw(surface)

    def __len__(self) -> int:
        return sum(len(b) for b in self.bursts) + len(self.rockets)


class Vacuum:
    """Particles sucked into a point then a pop (Backspace/Delete)."""

    def __init__(self, ctx: EffectContext, pos: tuple[float, float], count: int = 70) -> None:
        self.ctx = ctx
        self.pos = pos
        self.sys = ParticleSystem()
        self.age = 0.0
        self.popped = False
        for _ in range(max(6, int(count * ctx.scale))):
            ang = ctx.rng.uniform(0, math.tau)
            dist = ctx.rng.uniform(120, 420)
            x = pos[0] + math.cos(ang) * dist
            y = pos[1] + math.sin(ang) * dist
            self.sys.particles.append(Particle(
                x=x, y=y,
                vx=(pos[0] - x) * 2.2, vy=(pos[1] - y) * 2.2,
                life=0.55, color=random_bright(ctx.rng), size=6,
            ))

    def update(self, dt: float) -> bool:
        self.age += dt
        alive = self.sys.update(dt)
        if not alive and not self.popped:
            self.popped = True
            self.sys = burst(self.ctx, self.pos, count=40, speed=300, life=0.8)
            return True
        return alive

    def draw(self, surface: pygame.Surface) -> None:
        self.sys.draw(surface)

    def __len__(self) -> int:
        return len(self.sys)


class SpiralBurst:
    """Particles spiraling outward (Alt/Esc swirls)."""

    def __init__(self, ctx: EffectContext, pos: tuple[float, float],
                 count: int = 50, clockwise: bool = True) -> None:
        self.sys = ParticleSystem()
        spin = 3.0 if clockwise else -3.0
        n = max(6, int(count * ctx.scale))
        for i in range(n):
            ang = (i / n) * math.tau
            spd = ctx.rng.uniform(140, 260)
            self.sys.particles.append(Particle(
                x=pos[0], y=pos[1],
                vx=math.cos(ang) * spd - math.sin(ang) * spd * spin * 0.4,
                vy=math.sin(ang) * spd + math.cos(ang) * spd * spin * 0.4,
                life=ctx.rng.uniform(0.8, 1.3),
                color=random_bright(ctx.rng), size=6, drag=0.6,
            ))

    def update(self, dt: float) -> bool:
        return self.sys.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        self.sys.draw(surface)

    def __len__(self) -> int:
        return len(self.sys)
