"""Ambient layers: idle attract mode and the mash-storm chaos overlay."""

from __future__ import annotations

import math

import pygame

from .base import EffectContext, random_bright
from .bubbles import bubble_sprite


class AttractMode:
    """Gentle drifting glossy bubbles after 60 s idle — an invitation, not a
    show. Killed instantly by any keypress (engine removes it)."""

    def __init__(self, ctx: EffectContext, bubbles: int = 12) -> None:
        self.ctx = ctx
        rng = ctx.rng
        self.bubbles = [{
            "x": rng.uniform(0, ctx.width),
            "y": rng.uniform(0, ctx.height),
            "r": rng.uniform(20, 70),
            "phase": rng.uniform(0, math.tau),
            "speed": rng.uniform(12, 40),
            "color": random_bright(rng),
        } for _ in range(bubbles)]
        self.age = 0.0

    def update(self, dt: float) -> bool:
        self.age += dt
        for b in self.bubbles:
            b["y"] -= b["speed"] * dt
            b["x"] += math.sin(self.age * 0.7 + b["phase"]) * 18 * dt
            if b["y"] < -b["r"]:
                b["y"] = self.ctx.height + b["r"]
                b["x"] = self.ctx.rng.uniform(0, self.ctx.width)
        return True  # engine removes it on keypress

    def draw(self, surface: pygame.Surface) -> None:
        # Glossy cached sprites (shared with BubbleField), plus a soft pulsing
        # colored rim so idle mode still breathes with color.
        pulse = 0.55 + 0.45 * math.sin(self.age * 1.4)
        for b in self.bubbles:
            r = int(b["r"])
            sprite = bubble_sprite(r)
            surface.blit(sprite, sprite.get_rect(center=(int(b["x"]), int(b["y"]))))
            color = tuple(int(c * 0.35 * (0.6 + 0.4 * pulse)) for c in b["color"])
            pygame.draw.circle(surface, color, (int(b["x"]), int(b["y"])), r, 2)

    def __len__(self) -> int:
        return len(self.bubbles)


class ChaosOverlay:
    """Rainbow-chaos mode while a mash-storm is active: pulsing rainbow
    border + full-screen hue wash. The engine also spawns random bursts
    while this is live."""

    def __init__(self, ctx: EffectContext) -> None:
        self.ctx = ctx
        self.age = 0.0
        self.ending = False
        self._alpha = 0.0

    def stop(self) -> None:
        self.ending = True

    def update(self, dt: float) -> bool:
        self.age += dt
        target = 0.0 if self.ending else 1.0
        rate = 3.0 * dt
        self._alpha += max(-rate, min(rate, target - self._alpha))
        return not (self.ending and self._alpha <= 0.01)

    def draw(self, surface: pygame.Surface) -> None:
        if self._alpha <= 0.01:
            return
        w, h = surface.get_size()
        hue = (self.age * 0.6) % 1.0
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        color = (int(r * 255), int(g * 255), int(b * 255))
        thickness = int((18 + 10 * math.sin(self.age * 9)) * self._alpha)
        if thickness > 0:
            pygame.draw.rect(surface, color, (0, 0, w, h), thickness)
        # Translucent hue wash via an additive-ish overlay strip flash
        flash = (math.sin(self.age * 7) + 1) / 2
        overlay_alpha = int(46 * self._alpha * flash)
        if overlay_alpha > 2:
            wash = pygame.Surface((w, h))
            wash.fill(color)
            wash.set_alpha(overlay_alpha)
            surface.blit(wash, (0, 0))

    def __len__(self) -> int:
        return 30


class CelebrationPulse(ChaosOverlay):
    """A ChaosOverlay that stops itself after a fixed duration — the rainbow
    border pulse for milestone celebrations (VISUAL_REVIEW.md #10), so the
    party ends without the engine having to remember to call stop()."""

    def __init__(self, ctx, duration: float = 2.5) -> None:
        super().__init__(ctx)
        self.duration = duration

    def update(self, dt: float) -> bool:
        if not self.ending and self.age >= self.duration:
            self.stop()
        return super().update(dt)
