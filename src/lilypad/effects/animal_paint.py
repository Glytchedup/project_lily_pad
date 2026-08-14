"""The shared paint box: the palette, and the primitives everyone draws with.

Split out of ``animal_art`` so the farm animals, the side-on builder and the
mini countable objects can each import what they need without importing each
other. Nothing here knows what an animal is — it is ellipses, arcs, polygons,
eyes and legs, plus the colours they are drawn in.

The palette is flat and saturated on purpose: it has to read from across a
living room, where a subtle gradient turns to mush.
"""

from __future__ import annotations

import math

import pygame


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
PETAL_PINK = (255, 105, 180)
PETAL_CENTER = (255, 214, 10)
STAR_YELLOW = (255, 214, 10)
STAR_EDGE = (255, 149, 0)

RAINBOW = ((255, 59, 48), (255, 149, 0), (255, 214, 10),
           (52, 199, 89), (10, 132, 255), (191, 90, 242))


# ---------------------------------------------------------------------------
# Tiny drawing helpers
# ---------------------------------------------------------------------------
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
