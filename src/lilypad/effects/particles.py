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
from .glow import draw_glow


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
        # Additive glow sprites (VISUAL_REVIEW.md #3): overlapping particles
        # sum toward white, so bursts read as light instead of confetti dots.
        for p in self.particles:
            fade = 1.0 - p.age / p.life
            r = max(1, int(p.size * (0.4 + 0.6 * fade)))
            color = tuple(int(c * (0.35 + 0.65 * fade)) for c in p.color)
            draw_glow(surface, color, (p.x, p.y), r)


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


def _heart_points(n: int) -> list[tuple[float, float]]:
    """Unit-ish heart outline (classic parametric curve), y-up flipped for screen."""
    pts = []
    for i in range(n):
        t = (i / n) * math.tau
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x / 17.0, -y / 17.0))
    return pts


def _star_outline_points(n: int) -> list[tuple[float, float]]:
    """Points along a 5-point star outline (interpolated between vertices)."""
    verts = []
    for i in range(10):
        r = 1.0 if i % 2 == 0 else 0.45
        ang = -math.pi / 2 + i * math.pi / 5
        verts.append((math.cos(ang) * r, math.sin(ang) * r))
    pts = []
    per_edge = max(1, n // 10)
    for i in range(10):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % 10]
        for j in range(per_edge):
            f = j / per_edge
            pts.append((ax + (bx - ax) * f, ay + (by - ay) * f))
    return pts


def _smiley_points(n: int) -> list[tuple[float, float]]:
    """Face circle + two eyes + smile arc."""
    pts = []
    face = int(n * 0.55)
    for i in range(face):
        t = (i / face) * math.tau
        pts.append((math.cos(t), math.sin(t)))
    per_eye = int(n * 0.1)
    for ex in (-0.38, 0.38):
        for i in range(per_eye):
            t = (i / per_eye) * math.tau
            pts.append((ex + math.cos(t) * 0.1, -0.3 + math.sin(t) * 0.12))
    smile = n - face - 2 * per_eye
    for i in range(smile):
        t = math.pi * (0.15 + 0.7 * i / max(1, smile - 1))
        pts.append((math.cos(t) * 0.55, 0.1 + math.sin(t) * 0.5))
    return pts


_SHAPES = {
    "heart": _heart_points,
    "star": _star_outline_points,
    "smiley": _smiley_points,
}


def shaped_burst(ctx: EffectContext, pos: tuple[float, float], shape: str,
                 colors: list[tuple[int, int, int]] | None = None,
                 count: int = 90, spread: float = 260.0,
                 life: float = 1.5) -> ParticleSystem:
    """Explosion whose particles fly outward into a picture (heart/star/smiley):
    velocity is proportional to each template point, so with heavy drag the
    shape forms mid-air and lingers as it falls."""
    sys_ = ParticleSystem()
    n = max(12, int(count * ctx.scale))
    points = _SHAPES.get(shape, _star_outline_points)(n)
    palette = colors or BRIGHT_PALETTE
    color = ctx.rng.choice(palette)
    for px, py in points:
        jitter = ctx.rng.uniform(0.92, 1.08)
        sys_.particles.append(Particle(
            x=pos[0], y=pos[1],
            vx=px * spread * jitter, vy=py * spread * jitter,
            life=ctx.rng.uniform(0.85, 1.0) * life,
            color=color if ctx.rng.random() < 0.8 else (255, 255, 255),
            size=ctx.rng.uniform(4.5, 6.5),
            gravity=60.0, drag=2.6,
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
                 count: int = 3, life: float = 0.9,
                 max_r: float | None = None) -> None:
        self.pos = pos
        self.color = color or random_bright(ctx.rng)
        self.count = count
        self.life = life
        self.age = 0.0
        self.max_r = max_r if max_r is not None else max(ctx.width, ctx.height) * 0.6

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
    """Rockets that climb on glitter trails, then explode — half the time as
    a sphere, half the time drawing a picture (heart/star/smiley), with a
    white crackle pass partway through each burst (VISUAL_REVIEW.md #5)."""

    SHAPED_CHANCE = 0.5
    CRACKLE_AT = 0.5          # seconds after a burst is born
    CRACKLE_SPARKS = 10       # sampled particles that pop white glitter

    @dataclass
    class _Rocket:
        x: float
        y: float
        vy: float
        fuse: float
        color: tuple[int, int, int]
        age: float = 0.0
        exploded: bool = False

    @dataclass
    class _Burst:
        sys: ParticleSystem
        age: float = 0.0
        crackled: bool = False

    def __init__(self, ctx: EffectContext, rockets: int = 3) -> None:
        self.ctx = ctx
        self.rockets: list[Fireworks._Rocket] = []
        self.bursts: list[Fireworks._Burst] = []
        self.trail = ParticleSystem()
        for i in range(max(1, rockets)):
            self.rockets.append(self._Rocket(
                x=ctx.rng.uniform(ctx.width * 0.2, ctx.width * 0.8),
                y=ctx.height + 10,
                vy=-ctx.rng.uniform(0.9, 1.25) * ctx.height * 0.85,
                fuse=ctx.rng.uniform(0.55, 0.95) + i * 0.18,
                color=random_bright(ctx.rng),
            ))

    def _explode(self, r: "Fireworks._Rocket") -> ParticleSystem:
        if self.ctx.rng.random() < self.SHAPED_CHANCE:
            shape = self.ctx.rng.choice(("heart", "star", "smiley"))
            return shaped_burst(self.ctx, (r.x, r.y), shape,
                                colors=[r.color], count=90)
        return burst(self.ctx, (r.x, r.y), count=90,
                     colors=[r.color, (255, 255, 255)],
                     speed=520, gravity=300, size=6, life=1.4)

    def _crackle(self, b: "Fireworks._Burst") -> None:
        """White glitter micro-pops at sampled live burst particles."""
        rng = self.ctx.rng
        live = b.sys.particles
        for p in rng.sample(live, min(self.CRACKLE_SPARKS, len(live))):
            for _ in range(3):
                ang = rng.uniform(0, math.tau)
                spd = rng.uniform(40, 130)
                b.sys.particles.append(Particle(
                    x=p.x, y=p.y,
                    vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                    life=rng.uniform(0.2, 0.4),
                    color=(255, 255, 255), size=3.0, gravity=120.0,
                ))

    def update(self, dt: float) -> bool:
        rng = self.ctx.rng
        for r in self.rockets:
            if r.exploded:
                continue
            r.age += dt
            r.y += r.vy * dt
            r.vy += 300 * dt
            # Glitter trail while climbing (scaled with the degradation ladder).
            for _ in range(max(1, round(2 * self.ctx.scale))):
                self.trail.particles.append(Particle(
                    x=r.x + rng.uniform(-3, 3), y=r.y + rng.uniform(0, 10),
                    vx=rng.uniform(-25, 25), vy=rng.uniform(20, 80),
                    life=rng.uniform(0.25, 0.5),
                    color=(255, 220, 140), size=3.0,
                ))
            if r.age >= r.fuse:
                r.exploded = True
                self.bursts.append(self._Burst(self._explode(r)))
        for b in self.bursts:
            b.age += dt
            if not b.crackled and b.age >= self.CRACKLE_AT:
                b.crackled = True
                self._crackle(b)
        self.trail.update(dt)
        self.bursts = [b for b in self.bursts if b.sys.update(dt)]
        return (bool(self.bursts) or len(self.trail) > 0
                or any(not r.exploded for r in self.rockets))

    def draw(self, surface: pygame.Surface) -> None:
        self.trail.draw(surface)
        for r in self.rockets:
            if not r.exploded:
                pygame.draw.circle(surface, (255, 240, 200), (int(r.x), int(r.y)), 5)
                pygame.draw.line(surface, (255, 160, 60),
                                 (int(r.x), int(r.y) + 6), (int(r.x), int(r.y) + 22), 3)
        for b in self.bursts:
            b.sys.draw(surface)

    def __len__(self) -> int:
        return (sum(len(b.sys) for b in self.bursts) + len(self.rockets)
                + len(self.trail))


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
