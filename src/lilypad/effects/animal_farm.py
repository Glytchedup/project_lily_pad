"""The four originals: cow, duck, pig and sheep, drawn front-on by hand.

Deliberately outside the generic side-on builder. They were tuned by eye, they
ship, and rewriting them into the spec system would risk making them worse to
no benefit — see PLAN.md D16. They peek up from the bottom of the screen rather
than crossing it, so there is no side view to trace and no ``StencilSpec`` row
for any of them.
"""

from __future__ import annotations

import math

import pygame

from .animal_paint import (
    COW_BLACK,
    COW_HORN,
    COW_WHITE,
    DUCK_ORANGE,
    DUCK_ORANGE_DARK,
    DUCK_YELLOW,
    DUCK_YELLOW_DARK,
    MUZZLE_DARK,
    MUZZLE_PINK,
    OUTLINE,
    PIG_PINK,
    PIG_PINK_DARK,
    PIG_SNOUT,
    PUPIL,
    SHEEP_GREY,
    SHEEP_GREY_LIGHT,
    WOOL,
    WOOL_SHADE,
    _arc,
    _ellipse,
    _eyes,
    _leg,
)


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
