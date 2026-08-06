"""The farm-animal cast — peekaboo friends for Pip, plus countable minis.

Implements VISUAL_REVIEW.md #2 (cow / duck / pig / sheep slide up from the
bottom edge, blink, wiggle, slide away) and the sprite helpers for #7
(small countable objects for the count-along effect).

All art is original, drawn once from pygame primitives (ellipses, circles,
polygons, arcs) in the same chunky, big-eyed, high-contrast spirit as Pip in
``critter.py`` — no licensed characters, no image assets on disk.

Performance rules (matching the ``particles.py`` header): every sprite is
pre-rendered exactly once into a cached ``SRCALPHA`` surface at spawn time;
per-frame work is a single blit plus integer offset math. No per-pixel Python
loops, no per-frame surface allocation.
"""

from __future__ import annotations

import math

import pygame

from .base import EffectContext

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

#: Letters that summon an animal (VISUAL_REVIEW #2). The registry maps each of
#: these to a ``PeekabooAnimal`` alongside the normal giant letter.
ANIMAL_LETTERS: dict[str, str] = {"C": "cow", "D": "duck", "P": "pig", "S": "sheep"}

#: Small countable objects for the count-along effect (VISUAL_REVIEW #7).
MINI_KINDS: tuple[str, ...] = ("duck", "apple", "frog", "flower", "star")

POSES: tuple[str, ...] = ("idle", "blink")

# Body width as a multiple of the requested height, per animal.
_ASPECT: dict[str, float] = {"cow": 1.15, "duck": 1.05, "pig": 1.15, "sheep": 1.20}

# Cache keys are (name, height, pose) / (kind, size). In normal use `name` is
# one of four animals, `pose` one of two, and the heights come from a handful
# of screen-derived values (40% of a fixed display height, plus whatever the
# count-along picks), so the dicts top out at a few dozen small surfaces for
# the life of the process. No eviction policy is needed — an LRU here would
# cost more than it saves.
_animal_cache: dict[tuple[str, int, str], pygame.Surface] = {}
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


# ---------------------------------------------------------------------------
# The animals
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


_ANIMAL_DRAWERS = {
    "cow": _draw_cow,
    "duck": _draw_duck,
    "pig": _draw_pig,
    "sheep": _draw_sheep,
}


def animal_sprite(name: str, height: int, pose: str = "idle") -> pygame.Surface:
    """Return the cached sprite for ``name`` at ``height`` px in ``pose``.

    Unknown ``name`` raises ``KeyError``; unknown ``pose`` falls back to
    ``"idle"``. The returned surface is shared — never draw onto it.
    """
    draw = _ANIMAL_DRAWERS[name]          # KeyError for an unknown animal
    if pose not in POSES:
        pose = "idle"
    height = max(24, int(height))
    key = (name, height, pose)
    cached = _animal_cache.get(key)
    if cached is not None:
        return cached
    width = int(height * _ASPECT[name])
    surf = _new_surface(width, height)
    draw(surf, width, height, pose)
    surf = _finish(surf)
    _animal_cache[key] = surf
    return surf


# ---------------------------------------------------------------------------
# Mini countable objects (VISUAL_REVIEW #7)
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
    bill = [
        (int(s * 0.54), int(s * 0.25)), (int(s * 0.92), int(s * 0.27)),
        (int(s * 0.92), int(s * 0.35)), (int(s * 0.53), int(s * 0.36)),
    ]
    pygame.draw.polygon(surf, DUCK_ORANGE, bill)
    pygame.draw.polygon(surf, OUTLINE, bill, max(1, edge // 2))
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


_MINI_DRAWERS = {
    "duck": _mini_duck,
    "apple": _mini_apple,
    "frog": _mini_frog,
    "flower": _mini_flower,
    "star": _mini_star,
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


# ---------------------------------------------------------------------------
# The peekaboo effect
# ---------------------------------------------------------------------------
def _ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _ease_in(t: float) -> float:
    return t ** 3


class PeekabooAnimal:
    """An animal slides up from below, lives a little, and slides away.

    Timeline: 0.5 s ease-out rise → 2.2 s hold (two blinks + a gentle bob and
    sway) → 0.5 s ease-in drop. ``update`` returns False once it is fully back
    off-screen.

    Motion choice: a sinusoidal **bob + sway**, not ``pygame.transform.rotate``.
    At ~40 % of a 1080p screen the sprite is ~430 px tall; rotating it every
    frame allocates and fills a fresh ~800 KB surface 60 times a second, and
    because the angle changes continuously none of it can be cached — that is
    real work on the Pi's software blit path for a wobble a 2-year-old reads
    the same either way. Bob/sway is pure integer offset math on a cached
    surface: one blit per frame, zero allocation.
    """

    RISE_TIME = 0.5
    HOLD_TIME = 2.2
    FALL_TIME = 0.5
    # Hold-relative windows in which the eyes are shut ("blinks twice").
    _BLINKS = ((0.55, 0.70), (1.35, 1.50))

    def __init__(self, ctx: EffectContext, name: str) -> None:
        self.name = name
        self.age = 0.0
        self.total = self.RISE_TIME + self.HOLD_TIME + self.FALL_TIME
        self.pose = "idle"
        height = max(48, int(ctx.height * 0.40))
        self.height = height
        # Pre-render both poses now so the blink never costs a frame.
        self._idle = animal_sprite(name, height, "idle")
        self._blink = animal_sprite(name, height, "blink")
        self._sprite_w = self._idle.get_width()
        # Middle 70 % of the width, sprite kept fully on-screen.
        half = self._sprite_w * 0.5
        low = min(max(ctx.width * 0.15, half), ctx.width - half)
        high = max(min(ctx.width * 0.85, ctx.width - half), half)
        self.x = ctx.rng.uniform(min(low, high), max(low, high))
        # Off-screen: sprite top at the bottom edge. Resting: mostly visible,
        # feet just past the edge so it reads as peeking over a fence.
        self._y_off = float(ctx.height)
        self._y_rest = ctx.height - height * 0.90
        self.y = self._y_off

    # -- animation -------------------------------------------------------
    def _pose_for(self, hold_t: float) -> str:
        for start, stop in self._BLINKS:
            if start <= hold_t < stop:
                return "blink"
        return "idle"

    def update(self, dt: float) -> bool:
        self.age += dt
        t = self.age
        if t < self.RISE_TIME:
            e = _ease_out(t / self.RISE_TIME)
            self.pose = "idle"
        elif t < self.RISE_TIME + self.HOLD_TIME:
            e = 1.0
            self.pose = self._pose_for(t - self.RISE_TIME)
        else:
            fall = min(1.0, (t - self.RISE_TIME - self.HOLD_TIME) / self.FALL_TIME)
            e = 1.0 - _ease_in(fall)
            self.pose = "idle"
        self.y = self._y_off + (self._y_rest - self._y_off) * e
        return self.age < self.total

    def draw(self, surface: pygame.Surface) -> None:
        sprite = self._blink if self.pose == "blink" else self._idle
        bob = math.sin(self.age * math.tau * 1.6) * self.height * 0.022
        sway = math.sin(self.age * math.tau * 0.85) * self.height * 0.018
        rect = sprite.get_rect(midtop=(int(self.x + sway), int(self.y + bob)))
        surface.blit(sprite, rect)

    def __len__(self) -> int:  # flat cost against the engine's particle budget
        return 25
