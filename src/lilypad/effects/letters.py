"""Giant letters (and glyph text like number digits) with pop-in animation.

Upgraded per VISUAL_REVIEW.md #6: thick contrasting outline, occasional
rainbow-gradient fill, a gentle bob/sway wobble during the hold phase, and
googly eyes that turn the glyph into a creature. All expensive work (glyph +
outline + gradient) happens once at spawn; per-frame cost is blits, two
circles, and — only during the short pop-in — an integer scale.
"""

from __future__ import annotations

import colorsys
import math

import pygame

from .base import EffectContext, random_bright

_font_cache: dict[int, pygame.font.Font] = {}


def _font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.Font(None, size)  # bundled freesansbold
    return _font_cache[size]


_OUTLINE_OFFSETS = [(-1, -1), (0, -1), (1, -1), (-1, 0),
                    (1, 0), (-1, 1), (0, 1), (1, 1)]


def _rainbowize(glyph: pygame.Surface) -> None:
    """Multiply a white-rendered glyph by a vertical rainbow gradient
    (~28 horizontal bands; spawn-time only)."""
    w, h = glyph.get_size()
    bands = 28
    band_h = max(1, h // bands + 1)
    strip = pygame.Surface((w, h))
    for i in range(bands + 1):
        r, g, b = colorsys.hsv_to_rgb((i / bands) * 0.92, 0.85, 1.0)
        pygame.draw.rect(strip, (int(r * 255), int(g * 255), int(b * 255)),
                         (0, i * band_h, w, band_h))
    glyph.blit(strip, (0, 0), special_flags=pygame.BLEND_RGB_MULT)


def render_glyph(text: str, size: int, color: tuple[int, int, int],
                 rng=None, rainbow: bool = False) -> pygame.Surface:
    """Fill + thick outline, rendered once. White fills get a colored outline
    so they still read; everything else gets a white one."""
    outline_color = (255, 255, 255)
    if color == (255, 255, 255):
        # BRIGHT_PALETTE contains white, so draw until we get a real color —
        # a white outline on a white fill would erase the whole effect.
        while outline_color == (255, 255, 255):
            outline_color = random_bright(rng)
    if rainbow:
        fill = _font(size).render(text, True, (255, 255, 255)).convert_alpha()
        _rainbowize(fill)
    else:
        fill = _font(size).render(text, True, color).convert_alpha()
    outline = _font(size).render(text, True, outline_color).convert_alpha()
    t = max(2, size // 36)  # outline thickness
    out = pygame.Surface((fill.get_width() + 2 * t, fill.get_height() + 2 * t),
                         pygame.SRCALPHA)
    for dx, dy in _OUTLINE_OFFSETS:
        out.blit(outline, (t + dx * t, t + dy * t))
    out.blit(fill, (t, t))
    return out


class GiantLetter:
    """A huge letter pops in, wobbles with googly eyes, fades out.

    The glyph is rendered once at full size; the pop-in animates with cheap
    integer scaling only during the first ~0.3 s, then blits are direct.
    The hold-phase wobble is a position bob/sway rather than a rotation —
    rotating a ~650 px RGBA surface every frame is the kind of cost the Pi
    frame budget exists to forbid, and the bob reads just as alive.
    """

    POP_TIME = 0.3
    HOLD_TIME = 1.0
    FADE_TIME = 0.6
    RAINBOW_CHANCE = 0.25

    def __init__(self, ctx: EffectContext, text: str,
                 pos: tuple[float, float] | None = None,
                 color: tuple[int, int, int] | None = None,
                 height_frac: float = 0.6,
                 eyes: bool = True) -> None:
        self.color = color or random_bright(ctx.rng)
        size = int(ctx.height * height_frac)
        rainbow = ctx.rng.random() < self.RAINBOW_CHANCE
        self.glyph = render_glyph(text, size, self.color, ctx.rng, rainbow)
        self.pos = pos or (
            ctx.rng.uniform(ctx.width * 0.3, ctx.width * 0.7),
            ctx.rng.uniform(ctx.height * 0.35, ctx.height * 0.65),
        )
        self.eyes = eyes
        self.eye_phase = ctx.rng.uniform(0, math.tau)
        self.age = 0.0
        self.total = self.POP_TIME + self.HOLD_TIME + self.FADE_TIME

    def update(self, dt: float) -> bool:
        self.age += dt
        return self.age < self.total

    def _wobble(self) -> tuple[int, int]:
        if self.age < self.POP_TIME:
            return (0, 0)
        t = self.age - self.POP_TIME
        h = self.glyph.get_height()
        return (int(math.sin(t * 2.1 + self.eye_phase) * h * 0.012),
                int(math.sin(t * 3.4) * h * 0.02))

    def _draw_eyes(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        """Googly eyes during the hold: white ball, wandering pupil."""
        r = max(6, rect.height // 14)
        cy = rect.top + int(rect.height * 0.34)
        wander = self.age * 2.6 + self.eye_phase
        px = int(math.cos(wander) * r * 0.35)
        py = int(math.sin(wander * 0.7) * r * 0.35)
        for side in (-1, 1):
            ex = rect.centerx + side * int(rect.width * 0.18)
            pygame.draw.circle(surface, (255, 255, 255), (ex, cy), r)
            pygame.draw.circle(surface, (25, 25, 30), (ex + px, cy + py),
                               max(3, r // 2))

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
            # The glyph is instance-owned and the phases are monotonic, so
            # set_alpha in place is safe — copying a ~1 MB surface every fade
            # frame was measured at 3.7x the cost of the plain blit.
            img.set_alpha(int(255 * max(0.0, fade)))
        ox, oy = self._wobble()
        rect = img.get_rect(center=(int(self.pos[0]) + ox, int(self.pos[1]) + oy))
        surface.blit(img, rect)
        if self.eyes and self.POP_TIME <= self.age <= self.POP_TIME + self.HOLD_TIME:
            self._draw_eyes(surface, rect)

    def __len__(self) -> int:  # counts toward particle budget as a flat cost
        return 20
