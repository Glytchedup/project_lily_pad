"""Small countable objects for the count-along effect.

Pressing a digit pops that many *things*, and they are drawn here: ducks,
apples, frogs, flowers, stars and two small dinosaurs. Simpler than the cast
proper on purpose — at a tenth of the size, detail turns to mud, so these are
built from a handful of shapes that survive being small.

One kind per press (see ``numbers.py``): "three ducks" teaches, "a duck, a
star, a square" does not.
"""

from __future__ import annotations

import math

import pygame

from .animal_paint import (
    APPLE_DARK,
    APPLE_RED,
    DUCK_ORANGE,
    DUCK_YELLOW,
    DUCK_YELLOW_DARK,
    FROG_GREEN,
    LEAF_GREEN,
    OUTLINE,
    PETAL_CENTER,
    PETAL_PINK,
    PUPIL,
    STAR_EDGE,
    STAR_YELLOW,
    STEM_BROWN,
    _arc,
    _ellipse,
    _eyes,
    _finish,
    _leg,
    _new_surface,
    _star_points,
)

#: (kind, size) -> sprite. Same one-off-construction rule as the cast.
_mini_cache: dict[tuple[str, int], pygame.Surface] = {}


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
