"""Effect engine: owns live effects, the frog, idle/chaos state, and the
frame budget with graceful degradation."""

from __future__ import annotations

import random
import time

import pygame

from ..input.mapper import Action
from .ambient import AttractMode, ChaosOverlay
from .base import Effect, EffectContext
from .critter import Frog
from .particles import burst
from .registry import effects_for

BACKGROUND = (6, 8, 12)  # near-black; pure black feels "off", this glows


class EffectEngine:
    def __init__(self, size: tuple[int, int], max_particles: int = 900,
                 idle_timeout: float = 60.0, fps: int = 60,
                 rng: random.Random | None = None) -> None:
        self.size = size
        self.max_particles = max_particles
        self.idle_timeout = idle_timeout
        self.frame_budget = 1.0 / max(1, fps)
        self.ctx = EffectContext(size=size, rng=rng or random.Random())
        self.effects: list[Effect] = []
        self.frog = Frog(size)
        self.chaos: ChaosOverlay | None = None
        self.attract: AttractMode | None = None
        self.last_action_time = time.monotonic()
        self._frame_ema = self.frame_budget
        self._chaos_spawn_accum = 0.0

    # ------------------------------------------------------------------ input

    def spawn(self, action: Action, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.last_action_time = now
        if self.attract is not None:      # any key kills attract mode instantly
            self.attract = None

        if action.kind == "arrow":
            self.frog.shove(action.direction)
            self.effects.append(burst(
                self.ctx, (self.frog.x, self.frog.y), count=18, speed=220, life=0.6,
            ))
            return
        if action.kind == "mash_start":
            if self.chaos is None:
                self.chaos = ChaosOverlay(self.ctx)
            else:
                self.chaos.ending = False
            return
        if action.kind == "mash_end":
            if self.chaos is not None:
                self.chaos.stop()
            return

        if self.particle_count() < self.max_particles * 1.5:
            self.effects.extend(effects_for(self.ctx, action))

    # ------------------------------------------------------------------ frame

    def particle_count(self) -> int:
        return sum(len(e) for e in self.effects if hasattr(e, "__len__"))

    def update(self, dt: float, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.frog.update(dt)
        self.effects = [e for e in self.effects if e.update(dt)]

        if self.chaos is not None:
            if not self.chaos.update(dt):
                self.chaos = None
            else:
                # Chaos mode keeps popping random bursts on its own.
                self._chaos_spawn_accum += dt
                if self._chaos_spawn_accum >= 0.15 and not self.chaos.ending:
                    self._chaos_spawn_accum = 0.0
                    if self.particle_count() < self.max_particles:
                        self.effects.append(burst(
                            self.ctx, self.ctx.random_pos(0.05),
                            count=35, speed=380,
                        ))

        if (self.attract is None and self.chaos is None
                and now - self.last_action_time >= self.idle_timeout):
            self.attract = AttractMode(self.ctx)
        if self.attract is not None:
            self.attract.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BACKGROUND)
        if self.attract is not None:
            self.attract.draw(surface)
        for effect in self.effects:
            effect.draw(surface)
        self.frog.draw(surface)
        if self.chaos is not None:
            self.chaos.draw(surface)

    # ----------------------------------------------------- graceful degrade

    def note_frame_time(self, seconds: float) -> None:
        """Feed measured frame time; shrink particle scale when over budget,
        recover slowly when comfortably under."""
        self._frame_ema = 0.9 * self._frame_ema + 0.1 * seconds
        if self._frame_ema > self.frame_budget * 1.05:
            self.ctx.scale = max(0.25, self.ctx.scale * 0.9)
        elif self._frame_ema < self.frame_budget * 0.75:
            self.ctx.scale = min(1.0, self.ctx.scale * 1.02)
