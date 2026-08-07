"""Count-along: pressing a digit pops that many *things* one at a time.

Upgraded per VISUAL_REVIEW.md #7: instead of abstract circles/stars/squares,
each press counts real objects from a toddler's world (ducks, apples, frogs,
flowers, stars — all one kind per press, because "three ducks" teaches and
"a duck, a star, a square" doesn't), and finishes with a left-to-right
mini-burst fanfare across the row.
"""

from __future__ import annotations

import math

import pygame

from .animals import MINI_KINDS, mini_sprite
from .base import EffectContext
from .letters import GiantLetter
from .particles import ParticleSystem, burst


class CountAlong:
    """N objects appear in sequence (pop each ~0.28 s), hold, fanfare, fade.

    Also shows the digit itself as a smaller GiantLetter up top so the
    symbol and the quantity appear together.
    """

    POP_INTERVAL = 0.28
    HOLD_AFTER_LAST = 1.2
    FADE_TIME = 0.5
    FANFARE_INTERVAL = 0.1

    def __init__(self, ctx: EffectContext, count: int) -> None:
        self.ctx = ctx
        self.count = max(1, min(10, count))
        self.age = 0.0
        rng = ctx.rng
        self.kind = rng.choice(MINI_KINDS)
        self.sprite = mini_sprite(self.kind, int(ctx.height * 0.14))
        self.fanfare = ParticleSystem()
        self._fanfared = 0  # objects that have had their fanfare burst
        self.spots: list[dict] = []
        # Lay objects on a gentle arc across the screen.
        for i in range(self.count):
            frac = (i + 0.5) / self.count
            x = ctx.width * (0.12 + 0.76 * frac)
            y = ctx.height * (0.55 - 0.18 * math.sin(frac * math.pi))
            self.spots.append({"pos": (x, y), "born": i * self.POP_INTERVAL})
        self.last_born = (self.count - 1) * self.POP_INTERVAL
        self.total = self.last_born + self.HOLD_AFTER_LAST + self.FADE_TIME
        # Stretch the digit's hold so symbol and quantity stay up TOGETHER:
        # with the default 1 s hold the digit was gone before the 8th, 9th
        # and 10th objects had even appeared.
        self.digit = GiantLetter(
            ctx, str(self.count),
            pos=(ctx.width * 0.5, ctx.height * 0.2), height_frac=0.28,
            eyes=False,
            hold_time=self.total - GiantLetter.POP_TIME - GiantLetter.FADE_TIME,
        )

    def update(self, dt: float) -> bool:
        self.age += dt
        self.digit.update(dt)
        # Fanfare: once the last object has landed, sweep mini-bursts
        # left-to-right across the row.
        fanfare_start = self.last_born + 0.35
        while (self._fanfared < self.count
               and self.age >= fanfare_start + self._fanfared * self.FANFARE_INTERVAL):
            x, y = self.spots[self._fanfared]["pos"]
            # Burst above the object (not on its face) and big enough to read
            # as a per-object "one! two! three!" beat.
            small = burst(self.ctx, (x, y - self.ctx.height * 0.06),
                          count=18, speed=280, size=6, life=0.7, gravity=160)
            self.fanfare.particles.extend(small.particles)
            self._fanfared += 1
        self.fanfare.update(dt)
        return self.age < self.total or len(self.fanfare) > 0

    def draw(self, surface: pygame.Surface) -> None:
        fade_start = self.total - self.FADE_TIME
        alpha = 1.0
        if self.age > fade_start:
            alpha = max(0.0, 1.0 - (self.age - fade_start) / self.FADE_TIME)
        for spot in self.spots:
            t = self.age - spot["born"]
            if t <= 0:
                continue
            # Continuous overshoot: rise to 1.15 by t=0.8, settle back to 1.0
            # (the piecewise form must meet at the branch point or the sprite
            # visibly snaps a whole size step in one frame).
            pop = min(1.0, t / 0.2)
            pop = 1.15 * (pop / 0.8) if pop < 0.8 else 1.15 - 0.15 * ((pop - 0.8) / 0.2)
            img = self.sprite
            if pop < 0.999 or pop > 1.001:
                w = max(1, int(img.get_width() * pop))
                h = max(1, int(img.get_height() * pop))
                img = pygame.transform.scale(img, (w, h))
            if alpha < 1.0:
                # Fade only ever runs long after every pop has settled, so
                # img is always the SHARED cached sprite here: set alpha just
                # around the blit and restore it (cheaper than a private copy
                # per fade frame).
                img.set_alpha(int(255 * alpha))
                x, y = spot["pos"]
                surface.blit(img, img.get_rect(center=(int(x), int(y))))
                # Restore with 255, NOT None: set_alpha(None) disables ALL
                # alpha blending including per-pixel — it permanently poisons
                # the shared cached sprite, which then blits its transparent
                # pixels as solid black for every later count-along.
                img.set_alpha(255)
            else:
                x, y = spot["pos"]
                surface.blit(img, img.get_rect(center=(int(x), int(y))))
        self.fanfare.draw(surface)
        if alpha > 0:
            self.digit.draw(surface)

    def __len__(self) -> int:
        return self.count + 20 + len(self.fanfare)
