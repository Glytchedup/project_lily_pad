"""Count-along: pressing a digit pops that many shapes one at a time."""

from __future__ import annotations

import math

import pygame

from .base import EffectContext, random_bright
from .letters import GiantLetter


def _star_points(cx: float, cy: float, r: float, points: int = 5) -> list[tuple[int, int]]:
    pts = []
    for i in range(points * 2):
        radius = r if i % 2 == 0 else r * 0.45
        ang = -math.pi / 2 + i * math.pi / points
        pts.append((int(cx + math.cos(ang) * radius), int(cy + math.sin(ang) * radius)))
    return pts


class CountAlong:
    """N shapes appear in sequence (pop each ~0.28 s), hold, fade.

    Also shows the digit itself as a smaller GiantLetter in a corner so the
    symbol and the quantity appear together.
    """

    POP_INTERVAL = 0.28
    HOLD_AFTER_LAST = 1.2
    FADE_TIME = 0.5

    def __init__(self, ctx: EffectContext, count: int) -> None:
        self.ctx = ctx
        self.count = max(1, min(10, count))
        self.age = 0.0
        rng = ctx.rng
        self.shapes: list[dict] = []
        # Lay shapes on a gentle arc across the screen.
        for i in range(self.count):
            frac = (i + 0.5) / self.count
            x = ctx.width * (0.12 + 0.76 * frac)
            y = ctx.height * (0.55 - 0.18 * math.sin(frac * math.pi))
            self.shapes.append({
                "pos": (x, y),
                "color": random_bright(rng),
                "kind": rng.choice(("circle", "star", "square")),
                "size": ctx.height * 0.07,
                "born": i * self.POP_INTERVAL,
            })
        self.digit = GiantLetter(
            ctx, str(count if count < 10 else 10),
            pos=(ctx.width * 0.5, ctx.height * 0.2), height_frac=0.28,
        )
        self.total = (self.count - 1) * self.POP_INTERVAL + self.HOLD_AFTER_LAST + self.FADE_TIME

    def update(self, dt: float) -> bool:
        self.age += dt
        self.digit.update(dt)
        return self.age < self.total

    def draw(self, surface: pygame.Surface) -> None:
        fade_start = self.total - self.FADE_TIME
        alpha = 1.0
        if self.age > fade_start:
            alpha = max(0.0, 1.0 - (self.age - fade_start) / self.FADE_TIME)
        for shape in self.shapes:
            t = self.age - shape["born"]
            if t <= 0:
                continue
            pop = min(1.0, t / 0.2)
            pop = 1.15 * pop if pop < 0.8 else 1.15 - 0.15 * ((pop - 0.8) / 0.2)
            size = shape["size"] * pop
            color = tuple(int(c * alpha) for c in shape["color"])
            x, y = shape["pos"]
            if shape["kind"] == "circle":
                pygame.draw.circle(surface, color, (int(x), int(y)), int(size))
            elif shape["kind"] == "star":
                pygame.draw.polygon(surface, color, _star_points(x, y, size * 1.2))
            else:
                s = int(size * 1.6)
                pygame.draw.rect(surface, color,
                                 (int(x - s / 2), int(y - s / 2), s, s),
                                 border_radius=max(2, s // 8))
        if alpha > 0:
            self.digit.draw(surface)

    def __len__(self) -> int:
        return self.count + 20
