"""Giant letters (and glyph text like number digits) with pop-in animation."""

from __future__ import annotations

import pygame

from .base import EffectContext, random_bright

_font_cache: dict[int, pygame.font.Font] = {}


def _font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.Font(None, size)  # bundled freesansbold
    return _font_cache[size]


class GiantLetter:
    """A huge letter pops in, wobbles gently, fades out.

    The glyph is rendered once at full size; the pop-in animates with cheap
    integer scaling only during the first ~0.3 s, then blits are direct —
    no per-frame smoothscale at full resolution (Pi frame budget).
    """

    POP_TIME = 0.3
    HOLD_TIME = 1.0
    FADE_TIME = 0.6

    def __init__(self, ctx: EffectContext, text: str,
                 pos: tuple[float, float] | None = None,
                 color: tuple[int, int, int] | None = None,
                 height_frac: float = 0.6) -> None:
        self.color = color or random_bright(ctx.rng)
        size = int(ctx.height * height_frac)
        self.glyph = _font(size).render(text, True, self.color).convert_alpha()
        self.pos = pos or (
            ctx.rng.uniform(ctx.width * 0.3, ctx.width * 0.7),
            ctx.rng.uniform(ctx.height * 0.35, ctx.height * 0.65),
        )
        self.age = 0.0
        self.total = self.POP_TIME + self.HOLD_TIME + self.FADE_TIME

    def update(self, dt: float) -> bool:
        self.age += dt
        return self.age < self.total

    def draw(self, surface: pygame.Surface) -> None:
        img = self.glyph
        if self.age < self.POP_TIME:
            # Overshoot pop: grow 0 → 1.15, settle back to 1.0
            t = self.age / self.POP_TIME
            if t < 0.7:
                scale = max(0.05, 1.15 * (t / 0.7))
            else:
                scale = 1.15 - 0.15 * ((t - 0.7) / 0.3)
            w = max(1, int(img.get_width() * scale))
            h = max(1, int(img.get_height() * scale))
            img = pygame.transform.scale(img, (w, h))
        elif self.age > self.POP_TIME + self.HOLD_TIME:
            fade = 1.0 - (self.age - self.POP_TIME - self.HOLD_TIME) / self.FADE_TIME
            img = img.copy()
            img.set_alpha(int(255 * max(0.0, fade)))
        rect = img.get_rect(center=(int(self.pos[0]), int(self.pos[1])))
        surface.blit(img, rect)

    def __len__(self) -> int:  # counts toward particle budget as a flat cost
        return 20
