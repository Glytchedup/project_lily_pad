"""Key-hold rainbow comet (VISUAL_REVIEW.md recommendation #9).

Holding a key down spawns a persistent Comet: a bright rainbow head that
wanders the screen on a smooth sum-of-sines path (cheap pseudo-noise — no
per-pixel work, matching the budget rules in ``particles.py``'s header),
shedding a rainbow particle trail as it goes and growing slightly with hold
time. Releasing the key stops the wander/shed and fires a finale burst; the
comet then lives on (as fading trail + burst particles) until everything
has died out.
"""

from __future__ import annotations

import colorsys
import math

import pygame

from .base import EffectContext
from .particles import Particle, ParticleSystem, burst

_BIRTH_RADIUS = 10.0
_CAP_RADIUS = 26.0
_GROWTH_SECONDS = 6.0
_SPEED_MIN = 250.0
_SPEED_MAX = 350.0
_HUE_SPEED = 0.18            # full rainbow cycles per second (roughly)
_EDGE_MARGIN = 0.10          # inward steering kicks in this close to an edge
_BURST_COUNT = 40
_SHED_PER_SECOND = 130.0     # trail particles/s (dt-based, frame-rate free)
_MAX_HOLD_SECONDS = 120.0    # safety valve: auto-release if the key-up never
                             # arrives (USB unplug mid-hold strands the hold).
                             # Long enough that a toddler leaning on a key
                             # keeps their comet; stuck holds from a device
                             # drop are also cleaned up by the udev replug
                             # rule restarting the app.


class Comet:
    """A single wandering, rainbow, trail-shedding comet tied to a held key."""

    def __init__(self, ctx: EffectContext) -> None:
        self.ctx = ctx
        self.width, self.height = ctx.size

        # Start somewhere in the middle 60% of the screen (20% margin/side).
        mx, my = self.width * 0.2, self.height * 0.2
        self.x = ctx.rng.uniform(mx, self.width - mx)
        self.y = ctx.rng.uniform(my, self.height - my)

        # Sum-of-sines heading: 2-3 incommensurate frequencies + rng phases
        # give a smooth, organic wander with no per-frame noise sampling.
        self._freqs = (
            ctx.rng.uniform(0.15, 0.35),
            ctx.rng.uniform(0.35, 0.65),
            ctx.rng.uniform(0.70, 1.10),
        )
        self._phases = tuple(ctx.rng.uniform(0.0, math.tau) for _ in range(3))
        self._amps = (1.4, 0.8, 0.45)

        self.speed = ctx.rng.uniform(_SPEED_MIN, _SPEED_MAX)
        self._hue_phase = ctx.rng.random()

        self.age = 0.0
        self.released = False
        self.trail = ParticleSystem()
        self.burst: ParticleSystem | None = None
        self._shed_accum = 0.0

    # -- state -----------------------------------------------------------

    @property
    def radius(self) -> float:
        growth = min(self.age, _GROWTH_SECONDS) / _GROWTH_SECONDS
        return _BIRTH_RADIUS + growth * (_CAP_RADIUS - _BIRTH_RADIUS)

    def _head_color(self) -> tuple[int, int, int]:
        hue = (self._hue_phase + self.age * _HUE_SPEED) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        return (int(r * 255), int(g * 255), int(b * 255))

    # -- motion ------------------------------------------------------------

    def _wander(self, dt: float) -> None:
        t = self.age
        heading = sum(
            a * math.sin(f * t + p)
            for a, f, p in zip(self._amps, self._freqs, self._phases)
        )
        dx, dy = math.cos(heading), math.sin(heading)

        # Soft inward bias once within 10% of any edge, so the comet drifts
        # back toward the middle instead of pinning itself to the wall.
        mx, my = self.width * _EDGE_MARGIN, self.height * _EDGE_MARGIN
        bias_x = bias_y = 0.0
        if self.x < mx:
            bias_x = (mx - self.x) / mx
        elif self.x > self.width - mx:
            bias_x = -(self.x - (self.width - mx)) / mx
        if self.y < my:
            bias_y = (my - self.y) / my
        elif self.y > self.height - my:
            bias_y = -(self.y - (self.height - my)) / my

        dx += bias_x * 3.5
        dy += bias_y * 3.5
        norm = math.hypot(dx, dy) or 1.0
        dx, dy = dx / norm, dy / norm

        self.x += dx * self.speed * dt
        self.y += dy * self.speed * dt
        # Hard safety clamp, inset by the max head size so the head and its
        # release burst stay fully on-screen instead of pinning half-clipped
        # into an edge or corner.
        inset = min(_CAP_RADIUS * 1.6, self.width / 4, self.height / 4)
        self.x = min(max(self.x, inset), self.width - inset)
        self.y = min(max(self.y, inset), self.height - inset)

    def _shed_trail(self, dt: float) -> None:
        # dt-based so the shed rate is frames-per-second independent (a
        # per-tick count doubled the trail at 120 fps and starved it at 30).
        self._shed_accum += dt * _SHED_PER_SECOND * self.ctx.scale
        count = int(self._shed_accum)
        if count <= 0:
            return
        self._shed_accum -= count
        color = self._head_color()
        for _ in range(min(count, 12)):
            ang = self.ctx.rng.uniform(0.0, math.tau)
            spd = self.ctx.rng.uniform(20.0, 70.0)
            self.trail.particles.append(Particle(
                x=self.x, y=self.y,
                vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                life=self.ctx.rng.uniform(0.6, 0.9),
                color=color,
                size=self.ctx.rng.uniform(3.0, 6.0),
                drag=0.8,
            ))

    # -- Effect protocol ---------------------------------------------------

    def update(self, dt: float) -> bool:
        self.age += dt
        if not self.released and self.age >= _MAX_HOLD_SECONDS:
            self.release()
        if not self.released:
            self._wander(dt)
            self._shed_trail(dt)
            self.trail.update(dt)
            return True
        trail_alive = self.trail.update(dt)
        burst_alive = self.burst.update(dt) if self.burst is not None else False
        return trail_alive or burst_alive

    def draw(self, surface: pygame.Surface) -> None:
        if not self.released:
            color = self._head_color()
            halo = tuple(int(c * 0.4) for c in color)
            pos = (int(self.x), int(self.y))
            pygame.draw.circle(surface, halo, pos, int(self.radius * 1.4))
            pygame.draw.circle(surface, color, pos, int(self.radius))
        self.trail.draw(surface)
        if self.burst is not None:
            self.burst.draw(surface)

    def release(self) -> None:
        """Stop wandering/shedding and fire the finale burst. Idempotent."""
        if self.released:
            return
        self.released = True
        color = self._head_color()
        self.burst = burst(
            self.ctx, (self.x, self.y), count=_BURST_COUNT,
            colors=[color, (255, 255, 255)],
            speed=300.0, gravity=0.0, size=7.0, life=0.9,
        )

    def __len__(self) -> int:
        n = 6 + len(self.trail)  # flat head cost + live trail particles
        if self.burst is not None:
            n += len(self.burst)
        return n
