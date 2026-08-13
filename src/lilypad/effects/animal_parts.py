"""Body parts for the generic side-on builder: where they go and how they look.

``_Geo`` records where one animal's body landed so every feature can attach to
it, and the ``_draw_*`` functions hang ears, muzzles, tails, legs, coat
markings and the long tail of per-creature features (horns, frills, spines,
trunks, shells...) off those coordinates.

Kept apart from ``animal_body``, which owns the silhouettes and gaits: this
module answers "what does a horn look like", that one answers "what shape is a
bird". Both are fed by one ``AnimalSpec`` row per creature.
"""

from __future__ import annotations

import math

import pygame

from .animal_paint import (
    OUTLINE,
    RAINBOW,
    _arc,
    _clip_to_ellipse,
    _ellipse,
    _leg,
    _new_surface,
    _poly,
)
from .animal_specs import AnimalSpec


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
