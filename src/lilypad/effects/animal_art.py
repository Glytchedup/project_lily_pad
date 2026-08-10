"""Drawing the cast: pygame primitives in, cached sprites out.

Two drawing systems live here, and the split is deliberate:

* The four **original farm animals** (cow, duck, pig, sheep) keep their
  hand-drawn, front-on art. They were tuned by eye, they ship, and rewriting
  them into the generic system would risk making them worse to no benefit.
* Everyone else is drawn **side-on facing right** by one data-driven builder
  fed from :mod:`lilypad.effects.animal_specs`. Twenty-six bespoke drawing
  functions would be a thousand lines nobody could keep consistent; one
  builder with a spec row per creature stays legible and gives the whole cast
  a single house style.

All art is original — ellipses, circles, polygons and arcs — in the same
chunky, big-eyed, high-contrast spirit as Pip in ``critter.py``. No licensed
characters, no image assets on disk.

**Performance rule** (same as ``particles.py``): every sprite is drawn exactly
once into a cached ``SRCALPHA`` surface, keyed by (name, height, pose). Sprite
construction may therefore be as expensive as it likes — masks, per-pixel
blends, scaling — because it happens once. Per-frame work is a single blit
plus integer offset math: no per-frame surface allocation, no rotation, no
scaling.
"""

from __future__ import annotations

import math

import pygame

from .animal_specs import SPECS, AnimalSpec

# ---------------------------------------------------------------------------
# Palette — flat, saturated, and readable from across a living room.
# ---------------------------------------------------------------------------
OUTLINE = (38, 34, 40)
EYE_WHITE = (255, 255, 255)
PUPIL = (30, 30, 34)

COW_WHITE = (250, 250, 248)
COW_BLACK = (46, 44, 48)
COW_HORN = (240, 226, 186)
MUZZLE_PINK = (247, 168, 184)
MUZZLE_DARK = (198, 108, 128)

DUCK_YELLOW = (255, 214, 10)
DUCK_YELLOW_DARK = (232, 176, 12)
DUCK_ORANGE = (255, 149, 0)
DUCK_ORANGE_DARK = (214, 112, 8)

PIG_PINK = (247, 158, 178)
PIG_PINK_DARK = (222, 118, 146)
PIG_SNOUT = (255, 186, 202)

WOOL = (250, 246, 234)
WOOL_SHADE = (226, 220, 202)
SHEEP_GREY = (86, 84, 92)
SHEEP_GREY_LIGHT = (122, 120, 130)

APPLE_RED = (226, 42, 48)
APPLE_DARK = (168, 26, 34)
LEAF_GREEN = (52, 199, 89)
STEM_BROWN = (122, 84, 48)
FROG_GREEN = (76, 187, 23)
FROG_GREEN_DARK = (56, 142, 60)
PETAL_PINK = (255, 105, 180)
PETAL_CENTER = (255, 214, 10)
STAR_YELLOW = (255, 214, 10)
STAR_EDGE = (255, 149, 0)

BONE_WHITE = (246, 246, 240)
RAINBOW = ((255, 59, 48), (255, 149, 0), (255, 214, 10),
           (52, 199, 89), (10, 132, 255), (191, 90, 242))

#: Small countable objects for the count-along effect.
MINI_KINDS: tuple[str, ...] = ("duck", "apple", "frog", "flower", "star",
                               "stegosaurus", "triceratops")

#: ``squash`` is derived from ``idle`` by a one-off scale (see ``animal_sprite``)
#: and is used by the hop/landing animations.
POSES: tuple[str, ...] = ("idle", "blink", "squash")

# Body width as a multiple of the requested height, for the bespoke four.
_BESPOKE_ASPECT: dict[str, float] = {
    "cow": 1.15, "duck": 1.05, "pig": 1.15, "sheep": 1.20,
}

# Cache keys are (name, height, pose) / (kind, size) / (name, height, pose)
# for the flipped variants. In normal use the heights come from a handful of
# screen-derived values, so the dicts top out at a few hundred small surfaces
# for the life of the process. No eviction policy is needed — an LRU here
# would cost more than it saves.
_animal_cache: dict[tuple[str, int, str], pygame.Surface] = {}
_flip_cache: dict[tuple[str, int, str], pygame.Surface] = {}
_mini_cache: dict[tuple[str, int], pygame.Surface] = {}


# ---------------------------------------------------------------------------
# Tiny drawing helpers
# ---------------------------------------------------------------------------
def _ellipse(surf: pygame.Surface, color: tuple[int, int, int],
             cx: float, cy: float, w: float, h: float, width: int = 0) -> None:
    rect = pygame.Rect(0, 0, max(2, int(w)), max(2, int(h)))
    rect.center = (int(cx), int(cy))
    pygame.draw.ellipse(surf, color, rect, width)


def _arc(surf: pygame.Surface, color: tuple[int, int, int],
         cx: float, cy: float, w: float, h: float,
         start: float, stop: float, width: int) -> None:
    rect = pygame.Rect(0, 0, max(2, int(w)), max(2, int(h)))
    rect.center = (int(cx), int(cy))
    pygame.draw.arc(surf, color, rect, start, stop, max(1, int(width)))


def _poly(surf: pygame.Surface, color: tuple[int, int, int],
          points: list[tuple[float, float]], outline: bool = True,
          edge: int = 2) -> None:
    pts = [(int(x), int(y)) for x, y in points]
    pygame.draw.polygon(surf, color, pts)
    if outline:
        pygame.draw.polygon(surf, OUTLINE, pts, max(1, edge))


def _mix(a: tuple[int, int, int], b: tuple[int, int, int],
         t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def _eyes(surf: pygame.Surface, centers: list[tuple[float, float]],
          r: float, pose: str) -> None:
    """Big friendly eyes; ``blink`` swaps them for happy closed arcs."""
    r = max(3, int(r))
    line = max(2, r // 3)
    for cx, cy in centers:
        if pose == "blink":
            # Upward-curving arc = squinted, smiling eye.
            _arc(surf, PUPIL, cx, cy, r * 2.2, r * 1.8,
                 math.pi * 0.12, math.pi * 0.88, line)
        else:
            pygame.draw.circle(surf, EYE_WHITE, (int(cx), int(cy)), r)
            pygame.draw.circle(surf, OUTLINE, (int(cx), int(cy)), r, max(1, r // 6))
            pygame.draw.circle(surf, PUPIL, (int(cx), int(cy)), max(2, int(r * 0.55)))
            pygame.draw.circle(surf, EYE_WHITE,
                               (int(cx - r * 0.25), int(cy - r * 0.32)),
                               max(1, int(r * 0.22)))


def _leg(surf: pygame.Surface, color: tuple[int, int, int],
         x: float, top: float, w: float, h: float,
         hoof: tuple[int, int, int] | None = None) -> None:
    w_i, h_i = max(3, int(w)), max(4, int(h))
    rect = pygame.Rect(int(x - w_i / 2), int(top), w_i, h_i)
    pygame.draw.rect(surf, color, rect, border_radius=max(2, w_i // 3))
    if hoof is not None:
        foot = pygame.Rect(rect.left, rect.bottom - max(3, h_i // 4), w_i, max(3, h_i // 4))
        pygame.draw.rect(surf, hoof, foot, border_radius=max(2, w_i // 3))


def _star_points(cx: float, cy: float, r: float, points: int = 5) -> list[tuple[int, int]]:
    """Local copy of the star math (numbers.py has its own — no cross-import)."""
    pts: list[tuple[int, int]] = []
    for i in range(points * 2):
        radius = r if i % 2 == 0 else r * 0.45
        ang = -math.pi / 2 + i * math.pi / points
        pts.append((int(cx + math.cos(ang) * radius), int(cy + math.sin(ang) * radius)))
    return pts


def _new_surface(w: int, h: int) -> pygame.Surface:
    return pygame.Surface((max(2, int(w)), max(2, int(h))), pygame.SRCALPHA)


def _finish(surf: pygame.Surface) -> pygame.Surface:
    """convert_alpha() once the display exists — otherwise blits are ~10x slower."""
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        return surf.convert_alpha()
    return surf


def _clip_to_ellipse(layer: pygame.Surface, cx: float, cy: float,
                     w: float, h: float) -> pygame.Surface:
    """Erase everything outside an ellipse.

    Used to keep coat patterns inside the body silhouette. ``BLEND_RGBA_MULT``
    multiplies alpha too, so pixels outside the white mask shape drop to fully
    transparent. Costly per call and entirely fine: this runs at cache-fill
    time, never per frame.
    """
    mask = _new_surface(layer.get_width(), layer.get_height())
    _ellipse(mask, (255, 255, 255), cx, cy, w, h)
    layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return layer


# ---------------------------------------------------------------------------
# The four originals — front-on, hand-drawn, unchanged
# ---------------------------------------------------------------------------
def _draw_cow(surf: pygame.Surface, w: int, h: int, pose: str) -> None:
    cx = w * 0.5
    edge = max(2, int(h * 0.012))
    # Legs first so they tuck under the body.
    for fx in (0.26, 0.42, 0.58, 0.74):
        _leg(surf, COW_WHITE, w * fx, h * 0.78, w * 0.09, h * 0.22, hoof=COW_BLACK)
    # Body
    _ellipse(surf, COW_WHITE, cx, h * 0.66, w * 0.88, h * 0.52)
    _ellipse(surf, COW_BLACK, w * 0.31, h * 0.60, w * 0.26, h * 0.22)
    _ellipse(surf, COW_BLACK, w * 0.70, h * 0.73, w * 0.28, h * 0.19)
    _ellipse(surf, OUTLINE, cx, h * 0.66, w * 0.88, h * 0.52, edge)
    # Udder-free belly highlight keeps the silhouette readable on dark scenes.
    _ellipse(surf, (255, 255, 255), cx, h * 0.74, w * 0.30, h * 0.14)
    # Horns (behind the head)
    for fx in (0.35, 0.65):
        _ellipse(surf, COW_HORN, w * fx, h * 0.09, w * 0.11, h * 0.10)
        _ellipse(surf, OUTLINE, w * fx, h * 0.09, w * 0.11, h * 0.10, max(1, edge // 2))
    # Ears
    for fx in (0.17, 0.83):
        _ellipse(surf, COW_WHITE, w * fx, h * 0.28, w * 0.22, h * 0.13)
        _ellipse(surf, OUTLINE, w * fx, h * 0.28, w * 0.22, h * 0.13, max(1, edge // 2))
    # Head
    _ellipse(surf, COW_WHITE, cx, h * 0.30, w * 0.62, h * 0.45)
    _ellipse(surf, COW_BLACK, w * 0.31, h * 0.17, w * 0.20, h * 0.14)
    _ellipse(surf, OUTLINE, cx, h * 0.30, w * 0.62, h * 0.45, edge)
    # Muzzle
    _ellipse(surf, MUZZLE_PINK, cx, h * 0.41, w * 0.40, h * 0.21)
    _ellipse(surf, OUTLINE, cx, h * 0.41, w * 0.40, h * 0.21, max(1, edge // 2))
    for side in (-1, 1):
        _ellipse(surf, MUZZLE_DARK, cx + side * w * 0.075, h * 0.385, w * 0.06, h * 0.05)
    _arc(surf, MUZZLE_DARK, cx, h * 0.445, w * 0.20, h * 0.07,
         math.pi * 1.1, math.pi * 1.9, max(2, edge // 2))
    _eyes(surf, [(cx - w * 0.14, h * 0.27), (cx + w * 0.14, h * 0.27)], h * 0.052, pose)


def _draw_duck(surf: pygame.Surface, w: int, h: int, pose: str) -> None:
    edge = max(2, int(h * 0.012))
    # Feet
    for fx in (0.36, 0.58):
        pygame.draw.polygon(surf, DUCK_ORANGE, [
            (int(w * fx), int(h * 0.86)),
            (int(w * (fx + 0.14)), int(h * 0.98)),
            (int(w * (fx - 0.08)), int(h * 0.98)),
        ])
    # Tail — a short perky wedge, not a spike.
    pygame.draw.polygon(surf, DUCK_YELLOW_DARK, [
        (int(w * 0.20), int(h * 0.54)),
        (int(w * 0.06), int(h * 0.50)),
        (int(w * 0.21), int(h * 0.70)),
    ])
    # Body
    _ellipse(surf, DUCK_YELLOW, w * 0.50, h * 0.66, w * 0.82, h * 0.54)
    _ellipse(surf, OUTLINE, w * 0.50, h * 0.66, w * 0.82, h * 0.54, edge)
    # Wing hint
    _ellipse(surf, DUCK_YELLOW_DARK, w * 0.56, h * 0.66, w * 0.38, h * 0.28)
    _arc(surf, OUTLINE, w * 0.56, h * 0.66, w * 0.38, h * 0.28,
         math.pi * 0.05, math.pi * 1.05, max(1, edge // 2))
    # Head
    _ellipse(surf, DUCK_YELLOW, w * 0.42, h * 0.26, w * 0.42, h * 0.40)
    _ellipse(surf, OUTLINE, w * 0.42, h * 0.26, w * 0.42, h * 0.40, edge)
    # Flat bill pointing right — rounded tip, split by a darker seam.
    _ellipse(surf, DUCK_ORANGE, w * 0.70, h * 0.29, w * 0.44, h * 0.15)
    _ellipse(surf, OUTLINE, w * 0.70, h * 0.29, w * 0.44, h * 0.15, max(1, edge // 2))
    pygame.draw.line(surf, DUCK_ORANGE_DARK,
                     (int(w * 0.56), int(h * 0.295)), (int(w * 0.88), int(h * 0.295)),
                     max(2, edge // 2))
    _eyes(surf, [(w * 0.44, h * 0.22)], h * 0.055, pose)


def _draw_pig(surf: pygame.Surface, w: int, h: int, pose: str) -> None:
    cx = w * 0.5
    edge = max(2, int(h * 0.012))
    for fx in (0.27, 0.43, 0.57, 0.73):
        _leg(surf, PIG_PINK_DARK, w * fx, h * 0.80, w * 0.09, h * 0.20)
    # Curly tail hint
    _arc(surf, PIG_PINK_DARK, w * 0.93, h * 0.56, w * 0.14, h * 0.14,
         -math.pi * 0.5, math.pi * 0.9, max(2, edge))
    _arc(surf, PIG_PINK_DARK, w * 0.96, h * 0.65, w * 0.11, h * 0.12,
         math.pi * 0.4, math.pi * 1.7, max(2, edge))
    # Body
    _ellipse(surf, PIG_PINK, cx, h * 0.68, w * 0.86, h * 0.50)
    _ellipse(surf, OUTLINE, cx, h * 0.68, w * 0.86, h * 0.50, edge)
    # Floppy ears — attached under the head, drooping down and out.
    for side in (-1, 1):
        pygame.draw.polygon(surf, PIG_PINK_DARK, [
            (int(cx + side * w * 0.10), int(h * 0.17)),
            (int(cx + side * w * 0.36), int(h * 0.12)),
            (int(cx + side * w * 0.31), int(h * 0.42)),
        ])
    # Head
    _ellipse(surf, PIG_PINK, cx, h * 0.33, w * 0.62, h * 0.44)
    _ellipse(surf, OUTLINE, cx, h * 0.33, w * 0.62, h * 0.44, edge)
    # Big round snout
    _ellipse(surf, PIG_SNOUT, cx, h * 0.44, w * 0.32, h * 0.23)
    _ellipse(surf, OUTLINE, cx, h * 0.44, w * 0.32, h * 0.23, max(1, edge // 2))
    for side in (-1, 1):
        _ellipse(surf, PIG_PINK_DARK, cx + side * w * 0.058, h * 0.44, w * 0.055, h * 0.08)
    _eyes(surf, [(cx - w * 0.13, h * 0.29), (cx + w * 0.13, h * 0.29)], h * 0.048, pose)


def _draw_sheep(surf: pygame.Surface, w: int, h: int, pose: str) -> None:
    cx = w * 0.5
    edge = max(2, int(h * 0.012))
    for fx in (0.30, 0.44, 0.56, 0.70):
        _leg(surf, SHEEP_GREY, w * fx, h * 0.78, w * 0.075, h * 0.22)
    # Wool = overlapping circle bumps around an ellipse path, shaded then lit.
    bump = max(6, int(h * 0.115))
    for i in range(11):
        ang = math.tau * i / 11
        bx = cx + math.cos(ang) * w * 0.34
        by = h * 0.62 + math.sin(ang) * h * 0.19
        pygame.draw.circle(surf, WOOL_SHADE, (int(bx), int(by + h * 0.018)), bump)
    for i in range(11):
        ang = math.tau * i / 11
        bx = cx + math.cos(ang) * w * 0.34
        by = h * 0.62 + math.sin(ang) * h * 0.19
        pygame.draw.circle(surf, WOOL, (int(bx), int(by)), bump)
    _ellipse(surf, WOOL, cx, h * 0.62, w * 0.68, h * 0.38)
    # Ears
    for side in (-1, 1):
        _ellipse(surf, SHEEP_GREY, cx + side * w * 0.24, h * 0.27, w * 0.20, h * 0.10)
        _ellipse(surf, OUTLINE, cx + side * w * 0.24, h * 0.27, w * 0.20, h * 0.10,
                 max(1, edge // 2))
    # Face
    _ellipse(surf, SHEEP_GREY, cx, h * 0.30, w * 0.38, h * 0.34)
    _ellipse(surf, OUTLINE, cx, h * 0.30, w * 0.38, h * 0.34, edge)
    _ellipse(surf, SHEEP_GREY_LIGHT, cx, h * 0.39, w * 0.16, h * 0.10)
    _arc(surf, PUPIL, cx, h * 0.40, w * 0.12, h * 0.07,
         math.pi * 1.1, math.pi * 1.9, max(2, edge // 2))
    # Wool tuft on the head
    tuft = max(5, int(h * 0.068))
    for dx, dy in ((-0.10, 0.16), (0.0, 0.12), (0.10, 0.16)):
        pygame.draw.circle(surf, WOOL, (int(cx + w * dx), int(h * dy)), tuft)
    _eyes(surf, [(cx - w * 0.085, h * 0.29), (cx + w * 0.085, h * 0.29)], h * 0.042, pose)


_BESPOKE_DRAWERS = {
    "cow": _draw_cow,
    "duck": _draw_duck,
    "pig": _draw_pig,
    "sheep": _draw_sheep,
}


# ---------------------------------------------------------------------------
# The generic side-on builder
# ---------------------------------------------------------------------------
class _Geo:
    """Where the parts of one animal ended up, so features can attach."""

    __slots__ = ("w", "h", "edge", "bx", "by", "bw", "bh",
                 "hx", "hy", "hw", "hh", "ground")

    def __init__(self, w: int, h: int, edge: int) -> None:
        self.w, self.h, self.edge = w, h, edge
        self.bx = self.by = self.bw = self.bh = 0.0
        self.hx = self.hy = self.hw = self.hh = 0.0
        self.ground = h * 0.98


def _pattern_layer(spec: AnimalSpec, g: _Geo) -> pygame.Surface | None:
    """Coat markings, clipped to the body ellipse."""
    if spec.pattern == "none":
        return None
    layer = _new_surface(g.w, g.h)
    left, right = g.bx - g.bw / 2, g.bx + g.bw / 2
    top, bottom = g.by - g.bh / 2, g.by + g.bh / 2
    if spec.pattern == "stripes":
        step = g.bw / 7.0
        x = left + step * 0.4
        while x < right:
            pygame.draw.rect(layer, spec.accent,
                             pygame.Rect(int(x), int(top - 4),
                                         max(2, int(step * 0.38)),
                                         int(g.bh + 8)))
            x += step
    elif spec.pattern == "spots":
        for i in range(6):
            px = left + g.bw * (0.12 + 0.16 * i)
            py = top + g.bh * (0.30 if i % 2 else 0.62)
            _ellipse(layer, spec.accent, px, py, g.bw * 0.13, g.bh * 0.22)
    elif spec.pattern == "patch":
        # Giraffe-style irregular blocks.
        for i in range(8):
            px = left + g.bw * (0.10 + 0.12 * i)
            py = top + g.bh * (0.26 + 0.34 * (i % 3))
            _poly(layer, spec.accent, [
                (px, py), (px + g.bw * 0.10, py - g.bh * 0.06),
                (px + g.bw * 0.12, py + g.bh * 0.16),
                (px - g.bw * 0.01, py + g.bh * 0.20),
            ], outline=False)
    elif spec.pattern == "speckle":
        for i in range(14):
            px = left + g.bw * (0.08 + 0.062 * i)
            py = top + g.bh * (0.22 + 0.19 * (i % 4))
            pygame.draw.circle(layer, spec.accent, (int(px), int(py)),
                               max(2, int(g.bh * 0.045)))
    elif spec.pattern == "shaggy":
        for i in range(9):
            px = left + g.bw * (0.06 + 0.11 * i)
            _poly(layer, spec.shade, [
                (px, bottom - g.bh * 0.30),
                (px + g.bw * 0.07, bottom - g.bh * 0.30),
                (px + g.bw * 0.035, bottom + g.bh * 0.10),
            ], outline=False)
    return _clip_to_ellipse(layer, g.bx, g.by, g.bw, g.bh)


def _draw_ears(surf: pygame.Surface, spec: AnimalSpec, g: _Geo, near: bool) -> None:
    """Ears. The far ear is drawn behind the head in the shade color."""
    if spec.ears == "none":
        return
    color = spec.body if near else spec.shade
    edge = max(1, g.edge // 2)
    # Near ear sits forward and lower; the far one peeks behind.
    ex = g.hx - g.hw * (0.10 if near else 0.52)
    ey = g.hy - g.hh * (0.36 if near else 0.42)
    if spec.ears == "round":
        r = g.hh * (0.44 if near else 0.38)
        pygame.draw.circle(surf, color, (int(ex), int(ey)), int(r))
        pygame.draw.circle(surf, OUTLINE, (int(ex), int(ey)), int(r), edge)
        if near and "fluffyears" in spec.features:
            for i in range(6):
                ang = math.tau * i / 6
                pygame.draw.circle(surf, color,
                                   (int(ex + math.cos(ang) * r * 0.9),
                                    int(ey + math.sin(ang) * r * 0.9)),
                                   max(2, int(r * 0.42)))
    elif spec.ears == "pointy":
        s = g.hh * 0.46
        _poly(surf, color, [(ex - s * 0.42, ey + s * 0.30),
                            (ex + s * 0.30, ey + s * 0.34),
                            (ex - s * 0.05, ey - s * 0.95)], edge=edge)
    elif spec.ears == "long":
        lw, lh = g.hw * 0.30, g.hh * 1.25
        for k, off in enumerate((-0.30, 0.06) if near else (-0.46,)):
            _ellipse(surf, color, ex + g.hw * off, ey - lh * 0.34, lw, lh)
            _ellipse(surf, OUTLINE, ex + g.hw * off, ey - lh * 0.34, lw, lh, edge)
            if near:
                _ellipse(surf, spec.accent, ex + g.hw * off, ey - lh * 0.34,
                         lw * 0.45, lh * 0.66)
    elif spec.ears == "floppy":
        _poly(surf, color, [(ex, ey - g.hh * 0.18),
                            (ex + g.hw * 0.42, ey - g.hh * 0.30),
                            (ex + g.hw * 0.30, ey + g.hh * 0.44)], edge=edge)
    elif spec.ears == "fan":      # elephant
        _ellipse(surf, color, g.hx - g.hw * 0.34, g.hy + g.hh * 0.05,
                 g.hw * 1.15, g.hh * 1.45)
        _ellipse(surf, OUTLINE, g.hx - g.hw * 0.34, g.hy + g.hh * 0.05,
                 g.hw * 1.15, g.hh * 1.45, edge)
    elif spec.ears == "tuft":     # owl
        for side in (-1, 1):
            tx = g.hx + side * g.hw * 0.34
            _poly(surf, color, [(tx - g.hw * 0.10, g.hy - g.hh * 0.34),
                                (tx + g.hw * 0.12, g.hy - g.hh * 0.30),
                                (tx + side * g.hw * 0.06, g.hy - g.hh * 0.78)],
                  edge=edge)
    elif spec.ears == "tiny":
        r = g.hh * 0.16
        pygame.draw.circle(surf, color, (int(ex), int(ey)), max(3, int(r)))
        pygame.draw.circle(surf, OUTLINE, (int(ex), int(ey)), max(3, int(r)), edge)


def _draw_muzzle(surf: pygame.Surface, spec: AnimalSpec, g: _Geo) -> None:
    """Whatever sticks out of the front of the head."""
    edge = max(1, g.edge // 2)
    fx = g.hx + g.hw * 0.42          # front of the head
    fy = g.hy + g.hh * 0.16
    if spec.muzzle == "snout":
        _ellipse(surf, spec.shade, fx, fy, g.hw * 0.52, g.hh * 0.40)
        _ellipse(surf, OUTLINE, fx, fy, g.hw * 0.52, g.hh * 0.40, edge)
        pygame.draw.circle(surf, OUTLINE, (int(fx + g.hw * 0.16), int(fy - g.hh * 0.06)),
                           max(2, int(g.hh * 0.055)))
    elif spec.muzzle == "round":
        _ellipse(surf, spec.accent, fx - g.hw * 0.04, fy + g.hh * 0.04,
                 g.hw * 0.56, g.hh * 0.46)
        _ellipse(surf, OUTLINE, fx - g.hw * 0.04, fy + g.hh * 0.04,
                 g.hw * 0.56, g.hh * 0.46, edge)
        nose_r = g.hh * (0.16 if "bignose" in spec.features else 0.09)
        _ellipse(surf, OUTLINE, fx + g.hw * 0.10, fy - g.hh * 0.04,
                 nose_r * 2.0, nose_r * 1.5)
    elif spec.muzzle == "long":
        _ellipse(surf, spec.body, fx + g.hw * 0.22, fy + g.hh * 0.10,
                 g.hw * 0.86, g.hh * 0.44)
        _ellipse(surf, OUTLINE, fx + g.hw * 0.22, fy + g.hh * 0.10,
                 g.hw * 0.86, g.hh * 0.44, edge)
        pygame.draw.circle(surf, OUTLINE,
                           (int(fx + g.hw * 0.56), int(fy + g.hh * 0.04)),
                           max(2, int(g.hh * 0.065)))
    elif spec.muzzle in ("jaws", "beakjaw"):
        # Big open mouth: upper jaw, dark gap, lower jaw.
        jw, jh = g.hw * 1.05, g.hh * 0.34
        top_y = fy - g.hh * 0.06
        _ellipse(surf, spec.body, fx + jw * 0.28, top_y, jw, jh)
        _ellipse(surf, OUTLINE, fx + jw * 0.28, top_y, jw, jh, edge)
        _ellipse(surf, (58, 30, 34), fx + jw * 0.22, top_y + jh * 0.62,
                 jw * 0.86, jh * 0.62)
        _ellipse(surf, spec.shade, fx + jw * 0.24, top_y + jh * 0.96,
                 jw * 0.90, jh * 0.60)
        _ellipse(surf, OUTLINE, fx + jw * 0.24, top_y + jh * 0.96,
                 jw * 0.90, jh * 0.60, edge)
        if spec.muzzle == "beakjaw":   # triceratops parrot beak
            _poly(surf, spec.accent, [
                (fx + jw * 0.70, top_y - jh * 0.10),
                (fx + jw * 0.98, top_y + jh * 0.46),
                (fx + jw * 0.62, top_y + jh * 0.40),
            ], edge=edge)
    elif spec.muzzle == "beak":
        _poly(surf, spec.accent, [
            (fx - g.hw * 0.06, fy - g.hh * 0.16),
            (fx + g.hw * 0.72, fy + g.hh * 0.08),
            (fx - g.hw * 0.04, fy + g.hh * 0.28),
        ], edge=edge)
    elif spec.muzzle == "trunk":
        # A tapering chain of circles curls down and forward.
        n = 9
        for i in range(n):
            t = i / (n - 1)
            tx = fx + g.hw * (0.10 + 0.52 * math.sin(t * 1.35))
            ty = fy + g.hh * (0.10 + 1.30 * t)
            r = g.hh * (0.20 - 0.11 * t)
            pygame.draw.circle(surf, spec.body, (int(tx), int(ty)), max(3, int(r)))
        for i in range(n):
            t = i / (n - 1)
            tx = fx + g.hw * (0.10 + 0.52 * math.sin(t * 1.35))
            ty = fy + g.hh * (0.10 + 1.30 * t)
            r = g.hh * (0.20 - 0.11 * t)
            pygame.draw.circle(surf, OUTLINE, (int(tx), int(ty)), max(3, int(r)), edge)
            pygame.draw.circle(surf, spec.body, (int(tx), int(ty)),
                               max(2, int(r) - edge))


def _draw_tail(surf: pygame.Surface, spec: AnimalSpec, g: _Geo) -> None:
    edge = max(1, g.edge // 2)
    ax = g.bx - g.bw * 0.46          # tail root, back of the body
    ay = g.by - g.bh * 0.16
    # A long tail on a chunky body wants more room than the sprite has, and
    # anything drawn past x=0 is silently cut off. Clamp the tip instead: a
    # slightly shorter tail reads fine, a sliced-off one looks broken.
    # ``pad`` is for shapes drawn *centred* on the returned point — half their
    # own width has to stay inside too.
    def tip(x: float, pad: float = 0.0) -> float:
        return max(g.w * 0.015 + pad, x)
    if spec.tail in ("none",):
        return
    if spec.tail == "short":
        _ellipse(surf, spec.shade, ax - g.bw * 0.05, ay, g.bw * 0.14, g.bh * 0.20)
    elif spec.tail == "puff":
        # Rooted in the body, not floating behind it: the near edge of the
        # puff sits inside the body ellipse.
        r = g.bh * 0.42
        px = ax + r * 0.30
        _ellipse(surf, spec.accent, px, ay + g.bh * 0.06, r * 2.1, r * 1.9)
        _ellipse(surf, OUTLINE, px, ay + g.bh * 0.06, r * 2.1, r * 1.9, edge)
    elif spec.tail == "tuft":
        pygame.draw.line(surf, spec.shade, (int(ax), int(ay - g.bh * 0.10)),
                         (int(tip(ax - g.bw * 0.16 + g.bw * 0.06)),
                          int(ay + g.bh * 0.55)),
                         max(3, g.edge))
        _ellipse(surf, spec.accent, tip(ax - g.bw * 0.11, g.bw * 0.06),
                 ay + g.bh * 0.62, g.bw * 0.11, g.bh * 0.24)
    elif spec.tail == "long":
        pts = [(ax, ay - g.bh * 0.14)]
        for i in range(1, 7):
            t = i / 6
            pts.append((tip(ax - g.bw * 0.46 * t),
                        ay + g.bh * (0.55 * t + 0.30 * math.sin(t * 2.6))))
        pygame.draw.lines(surf, spec.shade, False,
                          [(int(x), int(y)) for x, y in pts], max(4, g.edge * 2))
    elif spec.tail == "rainbow":
        for k, color in enumerate(RAINBOW):
            off = (k - 2.5) * g.bh * 0.055
            pts = [(int(tip(ax - g.bw * 0.40 * (i / 5))),
                    int(ay + off + g.bh * (0.62 * (i / 5) ** 1.4)))
                   for i in range(6)]
            pygame.draw.lines(surf, color, False, pts, max(3, g.edge))
    elif spec.tail in ("thick", "spiked"):
        tip_x = tip(ax - g.bw * 0.62)
        _poly(surf, spec.body, [
            (ax + g.bw * 0.06, ay - g.bh * 0.30),
            (tip_x, ay + g.bh * 0.28),
            (tip_x, ay + g.bh * 0.44),
            (ax + g.bw * 0.06, ay + g.bh * 0.34),
        ], edge=edge)
        if spec.tail == "spiked":
            for sx, sy in ((tip_x + g.bw * 0.18, ay + g.bh * 0.16),
                           (tip_x + g.bw * 0.26, ay + g.bh * 0.02)):
                _poly(surf, spec.accent, [
                    (sx, sy), (tip(sx - g.bw * 0.16), sy - g.bh * 0.30),
                    (sx + g.bw * 0.03, sy - g.bh * 0.06),
                ], edge=edge)
    elif spec.tail == "curl":
        # Starts inside the body and curls up and over behind it.
        _arc(surf, spec.shade, ax - g.bw * 0.02, ay - g.bh * 0.24,
             g.bw * 0.40, g.bh * 0.80, math.pi * 0.10, math.pi * 1.55,
             max(4, g.edge * 2))
    elif spec.tail == "fluke":
        _poly(surf, spec.body, [
            (ax + g.bw * 0.10, ay + g.bh * 0.06),
            (tip(ax - g.bw * 0.24), ay - g.bh * 0.46),
            (tip(ax - g.bw * 0.10), ay + g.bh * 0.06),
            (tip(ax - g.bw * 0.24), ay + g.bh * 0.54),
        ], edge=edge)
    elif spec.tail == "fantail":
        _poly(surf, spec.shade, [
            (ax + g.bw * 0.08, ay),
            (tip(ax - g.bw * 0.26), ay - g.bh * 0.42),
            (tip(ax - g.bw * 0.20), ay),
            (tip(ax - g.bw * 0.26), ay + g.bh * 0.42),
        ], edge=edge)


def _draw_features(surf: pygame.Surface, spec: AnimalSpec, g: _Geo,
                   pose: str) -> None:
    """Everything spec-specific that isn't ears / muzzle / tail / pattern."""
    edge = max(1, g.edge // 2)
    f = spec.features

    if "ruff" in f:            # lion: a full ring of fur around the head
        n = 12
        for i in range(n):
            ang = math.tau * i / n
            pygame.draw.circle(
                surf, spec.accent,
                (int(g.hx + math.cos(ang) * g.hw * 0.92),
                 int(g.hy + math.sin(ang) * g.hh * 0.68)),
                max(4, int(g.hh * 0.34)))
        _ellipse(surf, spec.shade, g.hx, g.hy, g.hw * 1.9, g.hh * 1.45)

    if "mane" in f or "rainbowmane" in f:
        colors = RAINBOW if "rainbowmane" in f else (spec.shade,)
        n = 7
        for i in range(n):
            t = i / (n - 1)
            mx = g.hx - g.hw * (0.30 + 0.30 * t) - (g.hx - g.bx) * 0.34 * t
            my = g.hy - g.hh * 0.30 + (g.by - g.hy) * 0.62 * t
            color = colors[i % len(colors)]
            pygame.draw.circle(surf, color, (int(mx), int(my)),
                               max(3, int(g.hh * (0.30 - 0.06 * t))))

    if "horns" in f:
        for k, off in enumerate((-0.22, 0.16)):
            hx = g.hx + g.hw * off
            _arc(surf, spec.accent, hx, g.hy - g.hh * 0.44,
                 g.hw * 0.56, g.hh * 0.52,
                 math.pi * (0.15 if k else 0.45), math.pi * (0.95 if k else 1.25),
                 max(3, g.edge))
    if "ossicones" in f:
        for off in (-0.16, 0.16):
            hx = g.hx + g.hw * off
            pygame.draw.line(surf, spec.shade, (int(hx), int(g.hy - g.hh * 0.28)),
                             (int(hx), int(g.hy - g.hh * 0.68)), max(3, g.edge))
            pygame.draw.circle(surf, spec.accent, (int(hx), int(g.hy - g.hh * 0.72)),
                               max(3, int(g.hh * 0.13)))
    if "horn" in f:            # unicorn: a spiral cone
        tip = (g.hx + g.hw * 0.18, g.hy - g.hh * 1.05)
        _poly(surf, spec.accent, [
            (g.hx - g.hw * 0.08, g.hy - g.hh * 0.34),
            (g.hx + g.hw * 0.14, g.hy - g.hh * 0.30), tip,
        ], edge=edge)
        for i in range(3):
            t = 0.24 + 0.22 * i
            pygame.draw.line(
                surf, spec.shade,
                (int(g.hx - g.hw * 0.08 + (tip[0] - g.hx + g.hw * 0.08) * t),
                 int(g.hy - g.hh * 0.34 + (tip[1] - g.hy + g.hh * 0.34) * t)),
                (int(g.hx + g.hw * 0.14 + (tip[0] - g.hx - g.hw * 0.14) * t),
                 int(g.hy - g.hh * 0.30 + (tip[1] - g.hy + g.hh * 0.30) * t)),
                max(1, edge))
    if "tusks" in f:           # elephant
        for dy in (0.0, 0.10):
            _arc(surf, (244, 240, 226), g.hx + g.hw * 0.46,
                 g.hy + g.hh * (0.52 + dy), g.hw * 0.66, g.hh * 0.70,
                 math.pi * 1.15, math.pi * 1.85, max(3, g.edge))
    if "threehorns" in f:      # triceratops
        for off, up in ((-0.02, 0.92), (0.30, 0.86)):
            bx = g.hx + g.hw * off
            _poly(surf, (244, 240, 226), [
                (bx - g.hw * 0.10, g.hy - g.hh * 0.22),
                (bx + g.hw * 0.10, g.hy - g.hh * 0.18),
                (bx + g.hw * 0.16, g.hy - g.hh * up),
            ], edge=edge)
        _poly(surf, (244, 240, 226), [
            (g.hx + g.hw * 0.52, g.hy + g.hh * 0.26),
            (g.hx + g.hw * 0.62, g.hy + g.hh * 0.06),
            (g.hx + g.hw * 0.78, g.hy + g.hh * 0.20),
        ], edge=edge)
    if "teeth" in f:
        # A row of little white triangles along the upper jaw.
        jx = g.hx + g.hw * 0.42
        for i in range(5):
            tx = jx + g.hw * (0.06 + 0.20 * i)
            ty = g.hy + g.hh * 0.26
            _poly(surf, (255, 255, 255), [
                (tx, ty), (tx + g.hw * 0.11, ty),
                (tx + g.hw * 0.055, ty + g.hh * 0.20),
            ], outline=False)
    if "plates" in f:          # stegosaurus
        n = 6
        for i in range(n):
            t = i / (n - 1)
            px = g.bx + g.bw * (0.40 - 0.80 * t)
            py = g.by - g.bh * 0.48 - g.bh * 0.05 * math.sin(t * math.pi)
            size = g.bh * (0.30 + 0.22 * math.sin(t * math.pi))
            _poly(surf, spec.accent, [
                (px - size * 0.55, py + size * 0.20),
                (px, py - size),
                (px + size * 0.55, py + size * 0.20),
            ], edge=edge)
    if "spikes" in f or "scutes" in f:
        n = 8
        spike = "spikes" in f
        for i in range(n):
            t = i / (n - 1)
            px = g.bx + g.bw * (0.42 - 0.84 * t)
            py = g.by - g.bh * 0.47
            size = g.bh * (0.16 if spike else 0.11)
            _poly(surf, spec.shade if not spike else spec.accent, [
                (px - size, py + size * 0.4), (px, py - size),
                (px + size, py + size * 0.4),
            ], outline=False)
    if "frill" in f:           # triceratops
        _ellipse(surf, spec.shade, g.hx - g.hw * 0.34, g.hy - g.hh * 0.10,
                 g.hw * 1.30, g.hh * 1.70)
        _ellipse(surf, OUTLINE, g.hx - g.hw * 0.34, g.hy - g.hh * 0.10,
                 g.hw * 1.30, g.hh * 1.70, edge)
        for i in range(4):
            ang = math.pi * (0.66 + 0.22 * i)
            pygame.draw.circle(
                surf, spec.accent,
                (int(g.hx - g.hw * 0.34 + math.cos(ang) * g.hw * 0.62),
                 int(g.hy - g.hh * 0.10 + math.sin(ang) * g.hh * 0.84)),
                max(3, int(g.hh * 0.20)))
    if "crest" in f:
        _poly(surf, spec.accent, [
            (g.hx - g.hw * 0.30, g.hy - g.hh * 0.24),
            (g.hx + g.hw * 0.10, g.hy - g.hh * 0.28),
            (g.hx - g.hw * 0.52, g.hy - g.hh * 0.92),
        ], edge=edge)
    if "plume" in f:           # quail
        for k, off in enumerate((-0.05, 0.06, 0.16)):
            _arc(surf, spec.accent, g.hx + g.hw * off, g.hy - g.hh * 0.62,
                 g.hw * 0.30, g.hh * 0.70, math.pi * 0.9, math.pi * 1.7,
                 max(2, edge + 1))
    if "dewlap" in f:          # iguana throat fan
        _poly(surf, spec.accent, [
            (g.hx + g.hw * 0.10, g.hy + g.hh * 0.36),
            (g.hx + g.hw * 0.52, g.hy + g.hh * 0.30),
            (g.hx + g.hw * 0.24, g.hy + g.hh * 0.96),
        ], edge=edge)
    if "whiskers" in f:
        for dy in (-0.06, 0.06):
            pygame.draw.line(
                surf, OUTLINE,
                (int(g.hx + g.hw * 0.34), int(g.hy + g.hh * (0.24 + dy))),
                (int(g.hx + g.hw * 0.92), int(g.hy + g.hh * (0.14 + dy * 3))),
                max(1, edge))
    if "face" in f:            # monkey / lemur light face patch
        _ellipse(surf, spec.accent, g.hx + g.hw * 0.14, g.hy + g.hh * 0.14,
                 g.hw * 0.74, g.hh * 0.72)
    if "belly" in f:
        _ellipse(surf, spec.accent, g.bx, g.by + g.bh * 0.24,
                 g.bw * 0.66, g.bh * 0.36)
    if "fin" in f:
        _poly(surf, spec.shade, [
            (g.bx - g.bw * 0.06, g.by - g.bh * 0.46),
            (g.bx + g.bw * 0.16, g.by - g.bh * 0.46),
            (g.bx - g.bw * 0.02, g.by - g.bh * 0.86),
        ], edge=edge)
    if "tusk" in f:            # narwhal
        pygame.draw.line(surf, (244, 240, 226),
                         (int(g.bx + g.bw * 0.44), int(g.by - g.bh * 0.10)),
                         (int(g.w * 0.99), int(g.by - g.bh * 0.42)),
                         max(3, g.edge))
    if "spout" in f:
        # A fountain, not an arrow: droplets fanning up and outward.
        sx, sy = g.bx + g.bw * 0.10, g.by - g.bh * 0.34
        for k in range(7):
            t = k / 6.0
            ang = math.pi * (1.18 + 0.64 * t)     # sweep up and over
            dist = g.bh * (0.24 + 0.22 * math.sin(t * math.pi))
            px = sx + math.cos(ang) * dist * 1.1
            py = sy + math.sin(ang) * dist
            pygame.draw.circle(surf, (206, 232, 246), (int(px), int(py)),
                               max(2, int(g.bh * (0.11 - 0.04 * abs(t - 0.5) * 2))))
    if "bones" in f:           # x-ray fish
        for i in range(6):
            rx = g.bx - g.bw * 0.24 + g.bw * 0.10 * i
            pygame.draw.line(surf, spec.accent,
                             (int(rx), int(g.by - g.bh * 0.24)),
                             (int(rx - g.bw * 0.02), int(g.by + g.bh * 0.26)),
                             max(2, edge))
        pygame.draw.line(surf, spec.accent,
                         (int(g.bx - g.bw * 0.30), int(g.by - g.bh * 0.04)),
                         (int(g.bx + g.bw * 0.30), int(g.by - g.bh * 0.04)),
                         max(2, edge))
    if "frills" in f:          # jellyfish skirt
        for i in range(5):
            fx = g.bx + g.bw * (-0.36 + 0.18 * i)
            _arc(surf, spec.accent, fx, g.by + g.bh * 0.30,
                 g.bw * 0.20, g.bh * 0.24, math.pi, math.tau, max(2, edge + 1))


def _draw_legs(surf: pygame.Surface, spec: AnimalSpec, g: _Geo,
               fractions: tuple[float, ...], color: tuple[int, int, int],
               width: float) -> None:
    leg_top = g.by + g.bh * 0.22
    hoof = spec.accent if "hooves" in spec.features else None
    if "socks" in spec.features:
        hoof = spec.accent
    for fx in fractions:
        _leg(surf, color, g.w * fx, leg_top, g.w * width, g.ground - leg_top,
             hoof=hoof)


#: Features that belong *behind* the head — a frill or a lion's ruff drawn
#: after it would bury the face.
_BEHIND_HEAD = frozenset({"frill", "ruff"})


class _Subset:
    """A spec with its feature list filtered, so the builders can run
    ``_draw_features`` twice — once for the parts that sit behind the head and
    once for everything else. Clearer than threading a z-order argument
    through every feature branch."""

    __slots__ = ("_spec", "features")

    def __init__(self, spec: AnimalSpec, keep: frozenset[str], invert: bool) -> None:
        self._spec = spec
        if invert:
            self.features = tuple(f for f in spec.features if f not in keep)
        else:
            self.features = tuple(f for f in spec.features if f in keep)

    def __getattr__(self, item):          # everything else comes from the spec
        return getattr(self._spec, item)


def _build_quadruped(surf: pygame.Surface, w: int, h: int, pose: str,
                     spec: AnimalSpec) -> _Geo:
    g = _Geo(w, h, max(2, int(h * 0.012)))
    leg_h = h * spec.leg
    leg_top = g.ground - leg_h
    neck_squeeze = 1.0 - 0.25 * min(1.0, spec.neck)
    g.bh = h * 0.40 * spec.chunk * neck_squeeze
    g.bw = w * 0.62 * spec.chunk
    g.bx = w * 0.42
    g.by = leg_top - g.bh * 0.22
    g.hh = h * 0.27 * spec.head
    g.hw = w * 0.19 * spec.head
    # A bigger head needs to sit further back or its muzzle runs off the front
    # of the sprite (triceratops' beak was losing its tip).
    g.hx = w * (0.72 - 0.10 * (spec.head - 1.0))
    # Head rides high and forward so it reads as a head on a neck rather than
    # a second lump of body. The floor leaves room for whatever is on top of
    # it — long ears reach ~1.5 head-heights above centre, everything else
    # about 1.15 — so a giraffe's neck or a unicorn's horn can't push those
    # past the top edge and get sliced off.
    headroom = 1.55 if spec.ears == "long" else 1.20
    g.hy = max(g.hh * headroom,
               g.by - g.bh * 0.55 - g.hh * 0.28 - spec.neck * h * 0.20)

    _draw_legs(surf, spec, g, (0.30, 0.66), spec.shade, 0.072 * spec.chunk)
    _draw_tail(surf, spec, g)
    # Neck: a tapered quad from the shoulder up to the head. Drawn without an
    # outline on purpose — an outlined quad leaves a seam straight across the
    # body and the head where they overlap.
    _poly(surf, spec.body, [
        (g.bx + g.bw * 0.14, g.by - g.bh * 0.34),
        (g.bx + g.bw * 0.44, g.by - g.bh * 0.06),
        (g.hx + g.hw * 0.10, g.hy + g.hh * 0.34),
        (g.hx - g.hw * 0.58, g.hy + g.hh * 0.30),
    ], outline=False)
    _ellipse(surf, spec.body, g.bx, g.by, g.bw, g.bh)
    pattern = _pattern_layer(spec, g)
    if pattern is not None:
        surf.blit(pattern, (0, 0))
    _ellipse(surf, OUTLINE, g.bx, g.by, g.bw, g.bh, g.edge)
    _draw_features(surf, _Subset(spec, _BEHIND_HEAD, invert=False), g, pose)
    _draw_ears(surf, spec, g, near=False)
    _ellipse(surf, spec.body, g.hx, g.hy, g.hw * 1.65, g.hh)
    _ellipse(surf, OUTLINE, g.hx, g.hy, g.hw * 1.65, g.hh, g.edge)
    _draw_muzzle(surf, spec, g)
    _draw_ears(surf, spec, g, near=True)
    _draw_features(surf, _Subset(spec, _BEHIND_HEAD, invert=True), g, pose)
    _eyes(surf, [(g.hx + g.hw * 0.20, g.hy - g.hh * 0.12)], h * spec.eye, pose)
    _draw_legs(surf, spec, g, (0.22, 0.58), spec.body, 0.082 * spec.chunk)
    return g


def _build_biped(surf: pygame.Surface, w: int, h: int, pose: str,
                 spec: AnimalSpec) -> _Geo:
    """Dinosaur posture: body horizontal, tail counterbalancing, head forward."""
    g = _Geo(w, h, max(2, int(h * 0.014)))
    g.bh = h * 0.36 * spec.chunk
    g.bw = w * 0.46 * spec.chunk
    g.bx = w * 0.44
    g.by = h * 0.46
    g.hh = h * 0.24 * spec.head
    g.hw = w * 0.16 * spec.head
    g.hx = w * 0.70
    g.hy = max(g.hh * 0.62, h * 0.22)

    _draw_tail(surf, spec, g)
    _dino_leg(surf, spec, g, offset=0.34, color=spec.shade, scale=0.88)
    # Neck
    _poly(surf, spec.body, [
        (g.bx + g.bw * 0.30, g.by - g.bh * 0.32),
        (g.bx + g.bw * 0.72, g.by - g.bh * 0.02),
        (g.hx + g.hw * 0.20, g.hy + g.hh * 0.44),
        (g.hx - g.hw * 0.60, g.hy + g.hh * 0.40),
    ], outline=False)
    _ellipse(surf, spec.body, g.bx, g.by, g.bw, g.bh)
    _ellipse(surf, OUTLINE, g.bx, g.by, g.bw, g.bh, g.edge)
    if "feathers" in spec.features:
        for i in range(6):
            t = i / 5
            base = g.by - g.bh * (0.44 - 0.04 * t)
            _poly(surf, spec.accent, [
                (g.bx + g.bw * (0.26 - 0.62 * t), base),
                (g.bx + g.bw * (0.34 - 0.62 * t), base),
                (g.bx + g.bw * (0.20 - 0.62 * t), base - g.bh * 0.26),
            ], outline=False)
    _draw_features(surf, spec, g, pose)
    if "tinyarms" in spec.features:
        ax, ay = g.bx + g.bw * 0.42, g.by - g.bh * 0.06
        _poly(surf, spec.shade, [
            (ax, ay), (ax + g.bw * 0.26, ay + g.bh * 0.18),
            (ax + g.bw * 0.20, ay + g.bh * 0.34), (ax - g.bw * 0.02, ay + g.bh * 0.16),
        ], edge=max(1, g.edge // 2))
    _ellipse(surf, spec.body, g.hx, g.hy, g.hw * 2.1, g.hh)
    _ellipse(surf, OUTLINE, g.hx, g.hy, g.hw * 2.1, g.hh, g.edge)
    _draw_muzzle(surf, spec, g)
    _eyes(surf, [(g.hx + g.hw * 0.10, g.hy - g.hh * 0.16)], h * spec.eye, pose)
    _dino_leg(surf, spec, g, offset=0.02, color=spec.body, scale=1.0, claws=True)
    return g


def _dino_leg(surf: pygame.Surface, spec: AnimalSpec, g: _Geo, offset: float,
              color: tuple[int, int, int], scale: float,
              claws: bool = False) -> None:
    """A bird-like hind leg: thick drumstick thigh, angled shin, flat foot.

    Two stacked polygons drew as a rectangular box, which made both dinosaurs
    look like they were standing behind a crate. Real weight comes from the
    thigh being a fat ellipse and the shin angling *back* under it.
    """
    edge = max(1, g.edge // 2)
    hip_x = g.bx + g.bw * offset
    hip_y = g.by + g.bh * 0.16
    thigh_w = g.bw * 0.46 * scale
    thigh_h = (g.ground - hip_y) * 0.66
    _ellipse(surf, color, hip_x, hip_y + thigh_h * 0.30, thigh_w, thigh_h)
    _ellipse(surf, OUTLINE, hip_x, hip_y + thigh_h * 0.30, thigh_w, thigh_h, edge)
    # Shin sweeps back and down from the front of the thigh to the ankle.
    ankle_x = hip_x - g.bw * 0.16 * scale
    ankle_y = g.ground - g.bh * 0.12
    shin_w = thigh_w * 0.30
    _poly(surf, color, [
        (hip_x + thigh_w * 0.22, hip_y + thigh_h * 0.36),
        (hip_x + thigh_w * 0.22 - shin_w * 0.2, hip_y + thigh_h * 0.72),
        (ankle_x + shin_w * 0.55, ankle_y),
        (ankle_x - shin_w * 0.55, ankle_y),
    ], edge=edge)
    # Foot
    foot = pygame.Rect(int(ankle_x - shin_w * 0.7), int(ankle_y - g.bh * 0.02),
                       int(g.bw * 0.34 * scale), int(g.bh * 0.14))
    pygame.draw.rect(surf, color, foot, border_radius=max(2, edge * 2))
    pygame.draw.rect(surf, OUTLINE, foot, edge, border_radius=max(2, edge * 2))
    if claws:
        claw_color = (spec.accent if "sicklefoot" in spec.features
                      else (240, 236, 224))
        for i in range(3):
            tx = foot.right - g.bw * 0.02 - g.bw * 0.03 * i
            _poly(surf, claw_color, [
                (tx, foot.top + g.bh * 0.02),
                (tx + g.bw * 0.09, foot.centery),
                (tx, foot.bottom),
            ], outline=False)


def _build_bird(surf: pygame.Surface, w: int, h: int, pose: str,
                spec: AnimalSpec) -> _Geo:
    g = _Geo(w, h, max(2, int(h * 0.013)))
    leg_h = h * spec.leg
    leg_top = g.ground - leg_h
    g.bh = h * 0.46 * spec.chunk
    g.bw = w * 0.60 * spec.chunk
    g.bx = w * 0.46
    g.by = leg_top - g.bh * 0.30
    g.hh = h * 0.30 * spec.head
    g.hw = w * 0.17 * spec.head
    g.hx = w * 0.62
    g.hy = max(g.hh * 0.62, g.by - g.bh * 0.44)

    for fx in (0.42, 0.56):
        pygame.draw.line(surf, spec.accent, (int(w * fx), int(leg_top)),
                         (int(w * fx), int(g.ground)), max(3, g.edge * 2))
        # Three toes.
        for dx in (-0.05, 0.0, 0.05):
            pygame.draw.line(surf, spec.accent,
                             (int(w * fx), int(g.ground)),
                             (int(w * (fx + dx)), int(g.ground + h * 0.012)),
                             max(2, g.edge))
    _draw_tail(surf, spec, g)
    _ellipse(surf, spec.body, g.bx, g.by, g.bw, g.bh)
    pattern = _pattern_layer(spec, g)
    if pattern is not None:
        surf.blit(pattern, (0, 0))
    _ellipse(surf, OUTLINE, g.bx, g.by, g.bw, g.bh, g.edge)
    if "wing" in spec.features:
        _ellipse(surf, spec.shade, g.bx + g.bw * 0.10, g.by + g.bh * 0.06,
                 g.bw * 0.46, g.bh * 0.62)
        _arc(surf, OUTLINE, g.bx + g.bw * 0.10, g.by + g.bh * 0.06,
             g.bw * 0.46, g.bh * 0.62, math.pi * 0.05, math.pi * 1.15,
             max(1, g.edge // 2))
    _draw_ears(surf, spec, g, near=False)
    _ellipse(surf, spec.body, g.hx, g.hy, g.hw * 2.0, g.hh)
    _ellipse(surf, OUTLINE, g.hx, g.hy, g.hw * 2.0, g.hh, g.edge)
    _draw_ears(surf, spec, g, near=True)
    _draw_muzzle(surf, spec, g)
    _draw_features(surf, spec, g, pose)
    if "bigeyes" in spec.features:
        # Owl: two huge facial discs, both visible even in profile.
        for dx in (-0.34, 0.30):
            ex = g.hx + g.hw * dx
            _ellipse(surf, spec.accent, ex, g.hy - g.hh * 0.06,
                     g.hw * 0.86, g.hh * 0.72)
        _eyes(surf, [(g.hx - g.hw * 0.34, g.hy - g.hh * 0.06),
                     (g.hx + g.hw * 0.30, g.hy - g.hh * 0.06)], h * spec.eye, pose)
    else:
        _eyes(surf, [(g.hx + g.hw * 0.18, g.hy - g.hh * 0.12)], h * spec.eye, pose)
    return g


def _build_swimmer(surf: pygame.Surface, w: int, h: int, pose: str,
                   spec: AnimalSpec) -> _Geo:
    g = _Geo(w, h, max(2, int(h * 0.013)))
    g.bh = h * 0.46 * spec.chunk
    g.bw = w * 0.76 * spec.chunk
    g.bx = w * 0.46
    g.by = h * 0.52
    g.hh = g.bh
    g.hw = g.bw * 0.20
    g.hx = g.bx + g.bw * 0.30
    g.hy = g.by

    _draw_tail(surf, spec, g)
    _ellipse(surf, spec.body, g.bx, g.by, g.bw, g.bh)
    pattern = _pattern_layer(spec, g)
    if pattern is not None:
        surf.blit(pattern, (0, 0))
    _ellipse(surf, OUTLINE, g.bx, g.by, g.bw, g.bh, g.edge)
    _draw_features(surf, spec, g, pose)
    # A broad happy mouth along the front of the body.
    _arc(surf, OUTLINE, g.bx + g.bw * 0.28, g.by + g.bh * 0.10,
         g.bw * 0.34, g.bh * 0.36, math.pi * 1.08, math.pi * 1.92, max(2, g.edge))
    _eyes(surf, [(g.bx + g.bw * 0.30, g.by - g.bh * 0.14)], h * spec.eye, pose)
    return g


def _build_floater(surf: pygame.Surface, w: int, h: int, pose: str,
                   spec: AnimalSpec) -> _Geo:
    g = _Geo(w, h, max(2, int(h * 0.013)))
    g.bh = h * 0.46
    g.bw = w * 0.72
    g.bx = w * 0.50
    g.by = h * 0.34
    g.hh, g.hw, g.hx, g.hy = g.bh, g.bw * 0.2, g.bx, g.by

    # Tentacles first so the bell overlaps their tops.
    for i in range(6):
        t = i / 5
        tx = g.bx + g.bw * (-0.34 + 0.68 * t)
        pts = [(tx, g.by + g.bh * 0.30)]
        for k in range(1, 7):
            u = k / 6
            pts.append((tx + math.sin(u * 5.0 + i) * g.bw * 0.06,
                        g.by + g.bh * 0.30 + (h * 0.60) * u))
        pygame.draw.lines(surf, spec.shade, False,
                          [(int(x), int(y)) for x, y in pts], max(2, g.edge))
    _ellipse(surf, spec.body, g.bx, g.by, g.bw, g.bh)
    _ellipse(surf, OUTLINE, g.bx, g.by, g.bw, g.bh, g.edge)
    _ellipse(surf, spec.accent, g.bx - g.bw * 0.16, g.by - g.bh * 0.16,
             g.bw * 0.24, g.bh * 0.20)
    _draw_features(surf, spec, g, pose)
    _eyes(surf, [(g.bx - g.bw * 0.16, g.by + g.bh * 0.08),
                 (g.bx + g.bw * 0.16, g.by + g.bh * 0.08)], h * spec.eye, pose)
    return g


def _build_flyer(surf: pygame.Surface, w: int, h: int, pose: str,
                 spec: AnimalSpec) -> _Geo:
    """Wings swept back behind a forward-thrust head — pterodactyl.

    The first version spread both wings across the whole sprite, which buried
    the body and read as a paper kite rather than an animal. Keeping the wings
    behind the shoulder and giving the head the front third fixes it: the
    silhouette a toddler recognises is the long beak and the head crest.
    """
    g = _Geo(w, h, max(2, int(h * 0.013)))
    g.bh = h * 0.28
    g.bw = w * 0.22
    g.bx = w * 0.62
    g.by = h * 0.56
    g.hh = h * 0.19
    g.hw = w * 0.085
    g.hx = w * 0.80
    g.hy = h * 0.34

    def wing(color: tuple[int, int, int], tip: tuple[float, float],
             trail: tuple[float, float]) -> None:
        _poly(surf, color, [
            (g.bx + g.bw * 0.10, g.by - g.bh * 0.34),
            (w * tip[0], h * tip[1]),
            (w * trail[0], h * trail[1]),
            (g.bx - g.bw * 0.30, g.by + g.bh * 0.26),
        ], edge=max(1, g.edge // 2))
        pygame.draw.line(surf, spec.shade,
                         (int(g.bx + g.bw * 0.10), int(g.by - g.bh * 0.34)),
                         (int(w * tip[0]), int(h * tip[1])), max(2, g.edge))

    # Far wing sweeps up and back, near wing lower — two depths, no overlap
    # with the head.
    wing(spec.shade, tip=(0.10, 0.16), trail=(0.20, 0.40))
    _ellipse(surf, spec.body, g.bx, g.by, g.bw, g.bh)
    _ellipse(surf, OUTLINE, g.bx, g.by, g.bw, g.bh, g.edge)
    wing(spec.body, tip=(0.05, 0.52), trail=(0.16, 0.72))
    # Little tucked-up legs.
    for dx in (-0.02, 0.06):
        pygame.draw.line(surf, spec.shade,
                         (int(g.bx + g.bw * dx), int(g.by + g.bh * 0.30)),
                         (int(g.bx + g.bw * (dx - 0.55)), int(g.by + g.bh * 0.66)),
                         max(2, g.edge))
    _poly(surf, spec.body, [
        (g.bx + g.bw * 0.20, g.by - g.bh * 0.34),
        (g.bx + g.bw * 0.56, g.by - g.bh * 0.04),
        (g.hx - g.hw * 0.20, g.hy + g.hh * 0.46),
        (g.hx - g.hw * 1.10, g.hy + g.hh * 0.30),
    ], outline=False)
    _ellipse(surf, spec.body, g.hx, g.hy, g.hw * 2.0, g.hh)
    _ellipse(surf, OUTLINE, g.hx, g.hy, g.hw * 2.0, g.hh, g.edge)
    _draw_muzzle(surf, spec, g)
    _draw_features(surf, spec, g, pose)
    _eyes(surf, [(g.hx + g.hw * 0.10, g.hy - g.hh * 0.14)], h * spec.eye, pose)
    return g


_BUILDERS = {
    "quadruped": _build_quadruped,
    "biped": _build_biped,
    "bird": _build_bird,
    "swimmer": _build_swimmer,
    "floater": _build_floater,
    "flyer": _build_flyer,
}


# ---------------------------------------------------------------------------
# Public sprite API
# ---------------------------------------------------------------------------
def animal_names() -> tuple[str, ...]:
    """Every creature that can be drawn, bespoke and spec-driven alike."""
    return tuple(sorted(set(_BESPOKE_DRAWERS) | set(SPECS)))


def faces_right(name: str) -> bool:
    """True for the side-on cast (which can be flipped to face either way).

    The four originals are drawn front-on and must never be flipped — a
    mirrored front view is just a different, slightly wrong front view.
    """
    return name not in _BESPOKE_DRAWERS


def aspect(name: str) -> float:
    if name in _BESPOKE_DRAWERS:
        return _BESPOKE_ASPECT[name]
    return SPECS[name].aspect


def _squash(base: pygame.Surface) -> pygame.Surface:
    """Wider and shorter, standing on the same ground line.

    This is the landing frame of every hop. Deriving it from the finished
    ``idle`` sprite means one implementation covers bespoke and spec-driven
    animals alike, and it is still a cache-time cost, not a per-frame one.
    """
    w, h = base.get_size()
    squat = pygame.transform.smoothscale(
        base, (max(2, int(w * 1.14)), max(2, int(h * 0.86))))
    out = _new_surface(w, h)
    out.blit(squat, squat.get_rect(midbottom=(w // 2, h)))
    return out


def animal_sprite(name: str, height: int, pose: str = "idle") -> pygame.Surface:
    """Return the cached sprite for ``name`` at ``height`` px in ``pose``.

    Unknown ``name`` raises ``KeyError``; unknown ``pose`` falls back to
    ``"idle"``. Side-on animals face **right**. The returned surface is
    shared — never draw onto it.
    """
    if name not in _BESPOKE_DRAWERS and name not in SPECS:
        raise KeyError(name)
    if pose not in POSES:
        pose = "idle"
    height = max(24, int(height))
    key = (name, height, pose)
    cached = _animal_cache.get(key)
    if cached is not None:
        return cached

    if pose == "squash":
        surf = _squash(animal_sprite(name, height, "idle"))
    else:
        width = int(height * aspect(name))
        surf = _new_surface(width, height)
        bespoke = _BESPOKE_DRAWERS.get(name)
        if bespoke is not None:
            bespoke(surf, width, height, pose)
        else:
            _BUILDERS[SPECS[name].build](surf, width, height, pose, SPECS[name])
    surf = _finish(surf)
    _animal_cache[key] = surf
    return surf


def animal_sprite_facing(name: str, height: int, pose: str,
                         going_left: bool) -> pygame.Surface:
    """``animal_sprite`` mirrored when travelling left.

    Flips are cached like everything else, so a crossing costs at most three
    extra surfaces the first time a given animal runs at a given size.
    """
    sprite = animal_sprite(name, height, pose)
    if not going_left or not faces_right(name):
        return sprite
    key = (name, max(24, int(height)), pose if pose in POSES else "idle")
    flipped = _flip_cache.get(key)
    if flipped is None:
        flipped = _finish(pygame.transform.flip(sprite, True, False))
        _flip_cache[key] = flipped
    return flipped


# ---------------------------------------------------------------------------
# Mini countable objects
# ---------------------------------------------------------------------------
def _mini_duck(surf: pygame.Surface, s: int) -> None:
    edge = max(2, int(s * 0.035))
    pygame.draw.polygon(surf, DUCK_ORANGE, [
        (int(s * 0.38), int(s * 0.82)), (int(s * 0.56), int(s * 0.96)),
        (int(s * 0.28), int(s * 0.96)),
    ])
    _ellipse(surf, DUCK_YELLOW, s * 0.46, s * 0.64, s * 0.72, s * 0.50)
    _ellipse(surf, OUTLINE, s * 0.46, s * 0.64, s * 0.72, s * 0.50, edge)
    _ellipse(surf, DUCK_YELLOW_DARK, s * 0.52, s * 0.66, s * 0.34, s * 0.24)
    _ellipse(surf, DUCK_YELLOW, s * 0.40, s * 0.28, s * 0.40, s * 0.38)
    _ellipse(surf, OUTLINE, s * 0.40, s * 0.28, s * 0.40, s * 0.38, edge)
    # Rounded ellipse bill (a long thin quad read as a stick, not a beak).
    _ellipse(surf, DUCK_ORANGE, s * 0.66, s * 0.30, s * 0.28, s * 0.14)
    _ellipse(surf, OUTLINE, s * 0.66, s * 0.30, s * 0.28, s * 0.14,
             max(1, edge // 2))
    _eyes(surf, [(s * 0.42, s * 0.24)], s * 0.07, "idle")


def _mini_apple(surf: pygame.Surface, s: int) -> None:
    edge = max(2, int(s * 0.035))
    pygame.draw.line(surf, STEM_BROWN,
                     (int(s * 0.50), int(s * 0.34)), (int(s * 0.56), int(s * 0.12)),
                     max(3, int(s * 0.05)))
    _ellipse(surf, LEAF_GREEN, s * 0.68, s * 0.18, s * 0.30, s * 0.16)
    _ellipse(surf, OUTLINE, s * 0.68, s * 0.18, s * 0.30, s * 0.16, max(1, edge // 2))
    _ellipse(surf, APPLE_RED, s * 0.50, s * 0.62, s * 0.76, s * 0.68)
    _ellipse(surf, APPLE_DARK, s * 0.68, s * 0.66, s * 0.34, s * 0.52)
    _ellipse(surf, OUTLINE, s * 0.50, s * 0.62, s * 0.76, s * 0.68, edge)
    _ellipse(surf, (255, 255, 255), s * 0.35, s * 0.48, s * 0.16, s * 0.12)


def _mini_frog(surf: pygame.Surface, s: int) -> None:
    edge = max(2, int(s * 0.035))
    _ellipse(surf, FROG_GREEN, s * 0.50, s * 0.62, s * 0.78, s * 0.62)
    _ellipse(surf, OUTLINE, s * 0.50, s * 0.62, s * 0.78, s * 0.62, edge)
    _ellipse(surf, (200, 230, 160), s * 0.50, s * 0.74, s * 0.44, s * 0.30)
    for side in (-1, 1):
        ex = s * 0.50 + side * s * 0.20
        pygame.draw.circle(surf, FROG_GREEN, (int(ex), int(s * 0.28)), max(4, int(s * 0.17)))
        pygame.draw.circle(surf, OUTLINE, (int(ex), int(s * 0.28)),
                           max(4, int(s * 0.17)), max(1, edge // 2))
    _eyes(surf, [(s * 0.30, s * 0.28), (s * 0.70, s * 0.28)], s * 0.10, "idle")
    _arc(surf, PUPIL, s * 0.50, s * 0.62, s * 0.42, s * 0.26,
         math.pi * 1.12, math.pi * 1.88, max(2, edge))


def _mini_flower(surf: pygame.Surface, s: int) -> None:
    edge = max(2, int(s * 0.03))
    petal = max(4, int(s * 0.19))
    for i in range(6):
        ang = math.tau * i / 6 - math.pi / 2
        px = s * 0.50 + math.cos(ang) * s * 0.27
        py = s * 0.50 + math.sin(ang) * s * 0.27
        pygame.draw.circle(surf, PETAL_PINK, (int(px), int(py)), petal)
        pygame.draw.circle(surf, OUTLINE, (int(px), int(py)), petal, max(1, edge // 2))
    pygame.draw.circle(surf, PETAL_CENTER, (int(s * 0.50), int(s * 0.50)),
                       max(4, int(s * 0.17)))
    pygame.draw.circle(surf, OUTLINE, (int(s * 0.50), int(s * 0.50)),
                       max(4, int(s * 0.17)), max(1, edge // 2))


def _mini_star(surf: pygame.Surface, s: int) -> None:
    edge = max(2, int(s * 0.035))
    pts = _star_points(s * 0.50, s * 0.52, s * 0.46)
    pygame.draw.polygon(surf, STAR_YELLOW, pts)
    pygame.draw.polygon(surf, STAR_EDGE, pts, edge)
    pygame.draw.circle(surf, (255, 255, 255), (int(s * 0.42), int(s * 0.44)),
                       max(2, int(s * 0.07)))


def _mini_stegosaurus(surf: pygame.Surface, s: int) -> None:
    edge = max(2, int(s * 0.035))
    green, dark, plate = (122, 176, 128), (84, 136, 96), (238, 156, 92)
    for fx in (0.30, 0.44, 0.60, 0.72):
        _leg(surf, dark, s * fx, s * 0.72, s * 0.10, s * 0.24)
    # Tail wedge + body.
    pygame.draw.polygon(surf, green, [
        (int(s * 0.30), int(s * 0.50)), (int(s * 0.04), int(s * 0.40)),
        (int(s * 0.28), int(s * 0.66)),
    ])
    _ellipse(surf, green, s * 0.52, s * 0.58, s * 0.72, s * 0.40)
    _ellipse(surf, OUTLINE, s * 0.52, s * 0.58, s * 0.72, s * 0.40, edge)
    # The signature back plates.
    for i, (px, size) in enumerate(((0.34, 0.13), (0.48, 0.18), (0.62, 0.15),
                                    (0.74, 0.10))):
        pygame.draw.polygon(surf, plate, [
            (int(s * (px - size * 0.6)), int(s * 0.40)),
            (int(s * px), int(s * (0.40 - size * 1.5))),
            (int(s * (px + size * 0.6)), int(s * 0.40)),
        ])
    _ellipse(surf, green, s * 0.86, s * 0.46, s * 0.28, s * 0.22)
    _ellipse(surf, OUTLINE, s * 0.86, s * 0.46, s * 0.28, s * 0.22, max(1, edge // 2))
    _eyes(surf, [(s * 0.90, s * 0.42)], s * 0.055, "idle")


def _mini_triceratops(surf: pygame.Surface, s: int) -> None:
    edge = max(2, int(s * 0.035))
    olive, dark, bone = (154, 168, 118), (114, 128, 84), (238, 232, 208)
    for fx in (0.26, 0.40, 0.54, 0.66):
        _leg(surf, dark, s * fx, s * 0.72, s * 0.11, s * 0.24)
    pygame.draw.polygon(surf, dark, [
        (int(s * 0.26), int(s * 0.50)), (int(s * 0.03), int(s * 0.56)),
        (int(s * 0.26), int(s * 0.66)),
    ])
    _ellipse(surf, olive, s * 0.46, s * 0.58, s * 0.70, s * 0.40)
    _ellipse(surf, OUTLINE, s * 0.46, s * 0.58, s * 0.70, s * 0.40, edge)
    # Frill, then head over it.
    _ellipse(surf, dark, s * 0.76, s * 0.40, s * 0.42, s * 0.52)
    _ellipse(surf, OUTLINE, s * 0.76, s * 0.40, s * 0.42, s * 0.52, max(1, edge // 2))
    _ellipse(surf, olive, s * 0.84, s * 0.46, s * 0.34, s * 0.30)
    _ellipse(surf, OUTLINE, s * 0.84, s * 0.46, s * 0.34, s * 0.30, max(1, edge // 2))
    for bx, top in ((0.80, 0.20), (0.90, 0.24)):
        pygame.draw.polygon(surf, bone, [
            (int(s * (bx - 0.05)), int(s * 0.38)),
            (int(s * (bx + 0.05)), int(s * 0.38)),
            (int(s * (bx + 0.06)), int(s * top)),
        ])
    _eyes(surf, [(s * 0.86, s * 0.44)], s * 0.055, "idle")


_MINI_DRAWERS = {
    "duck": _mini_duck,
    "apple": _mini_apple,
    "frog": _mini_frog,
    "flower": _mini_flower,
    "star": _mini_star,
    "stegosaurus": _mini_stegosaurus,
    "triceratops": _mini_triceratops,
}


def mini_sprite(kind: str, size: int) -> pygame.Surface:
    """Cached square sprite (~``size`` px tall) of a countable object.

    Unknown ``kind`` raises ``KeyError``. The surface is shared — blit only.
    """
    draw = _MINI_DRAWERS[kind]            # KeyError for an unknown kind
    size = max(16, int(size))
    key = (kind, size)
    cached = _mini_cache.get(key)
    if cached is not None:
        return cached
    surf = _new_surface(size, size)
    draw(surf, size)
    surf = _finish(surf)
    _mini_cache[key] = surf
    return surf
