"""Pip the frog — the persistent critter that arrow keys shove around.

Original art drawn from pygame primitives (circles + arcs): a green frog
with big eyes that squashes when it bounces off walls. Lily pad theme, no
licensed characters.
"""

from __future__ import annotations

import math

import pygame

BODY = (76, 187, 23)
BODY_DARK = (56, 142, 60)
BELLY = (200, 230, 160)
EYE_WHITE = (255, 255, 255)
PUPIL = (30, 30, 30)


class Frog:
    """Persistent — update() always returns True; the engine owns exactly one."""

    def __init__(self, size: tuple[int, int]) -> None:
        self.w, self.h = size
        self.r = max(30, int(self.h * 0.06))
        self.x = self.w * 0.5
        self.y = self.h * 0.82
        self.vx = 0.0
        self.vy = 0.0
        self.squash = 0.0        # 0..1, decays; squashes the draw
        self.age = 0.0
        self.hop_impulse = self.h * 0.9
        self.just_bounced = False    # set each update; engine spawns ripples
        self._excited_until = 0.0    # celebration joy-hops while age < this

    def shove(self, direction: tuple[int, int]) -> None:
        dx, dy = direction
        self.vx += dx * self.hop_impulse
        self.vy += dy * self.hop_impulse
        # A hop always gets a little lift so left/right feels like jumping.
        if dy == 0:
            self.vy -= self.hop_impulse * 0.25

    def celebrate(self, seconds: float = 3.0) -> None:
        """Milestone joy: keep hopping on its own for a few seconds."""
        self._excited_until = self.age + seconds

    def update(self, dt: float) -> bool:
        self.age += dt
        self.squash = max(0.0, self.squash - dt * 3)
        # Gravity + drag
        self.vy += self.h * 1.4 * dt
        self.vx *= max(0.0, 1.0 - 1.2 * dt)
        self.x += self.vx * dt
        self.y += self.vy * dt
        r = self.r
        bounced = False
        if self.x < r:
            self.x, self.vx, bounced = r, abs(self.vx) * 0.85, True
        elif self.x > self.w - r:
            self.x, self.vx, bounced = self.w - r, -abs(self.vx) * 0.85, True
        if self.y < r:
            self.y, self.vy, bounced = r, abs(self.vy) * 0.85, True
        elif self.y > self.h - r:
            # A resting frog re-enters the floor by a sub-pixel every frame
            # (gravity), so only a real impact counts as a bounce — otherwise
            # he'd stay squashed forever and rain ripples while sitting still.
            impact = abs(self.vy)
            self.y = self.h - r
            if impact < 40:
                self.vy = 0.0
            else:
                self.vy = -impact * 0.7
                bounced = True
            # Joy-hop: while excited and touching the floor, launch again.
            if self.age < self._excited_until:
                self.vy = -self.hop_impulse * 0.8
                self.vx += (1 if (int(self.age * 7) % 2) else -1) * self.hop_impulse * 0.3
        if bounced:
            self.squash = 1.0
        self.just_bounced = bounced
        return True

    def draw(self, surface: pygame.Surface) -> None:
        r = self.r
        sq = 1.0 - 0.25 * self.squash
        rw, rh = int(r * (2 - sq)), int(r * sq * 1.6)
        x, y = int(self.x), int(self.y)
        # Body
        body = pygame.Rect(0, 0, rw * 2, rh * 2)
        body.center = (x, y)
        pygame.draw.ellipse(surface, BODY, body)
        pygame.draw.ellipse(surface, BODY_DARK, body, max(2, r // 10))
        # Belly
        belly = pygame.Rect(0, 0, int(rw * 1.2), int(rh * 1.1))
        belly.center = (x, y + rh // 3)
        pygame.draw.ellipse(surface, BELLY, belly)
        # Eyes on top, with a subtle idle blink
        eye_r = max(6, r // 2)
        blink = 0.15 if (self.age % 4.0) > 3.85 else 1.0
        for side in (-1, 1):
            ex = x + side * int(rw * 0.55)
            ey = y - rh
            pygame.draw.circle(surface, BODY, (ex, ey), eye_r + 3)
            pygame.draw.circle(surface, EYE_WHITE, (ex, ey), eye_r)
            pupil_h = max(2, int(eye_r * 0.6 * blink))
            pygame.draw.ellipse(
                surface, PUPIL,
                (ex - eye_r // 3, ey - pupil_h // 2, max(3, eye_r // 3 * 2), pupil_h),
            )
        # Smile
        mouth = pygame.Rect(0, 0, int(rw * 1.1), max(6, rh // 2))
        mouth.center = (x, y + rh // 4)
        pygame.draw.arc(surface, PUPIL, mouth, math.pi * 1.15, math.pi * 1.85, 3)

    def __len__(self) -> int:
        return 8
