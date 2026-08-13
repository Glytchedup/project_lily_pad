"""Silhouettes and gaits: one builder per body plan.

Six builders — quadruped, biped, bird, swimmer, floater, flyer — assemble a
creature from its ``AnimalSpec`` row and the parts in ``animal_parts``. Twenty-six
bespoke drawing functions would be a thousand lines nobody could keep
consistent; one builder per body plan keeps the whole cast in a single house
style and makes recasting a letter a one-row edit.

Every creature here faces **right**; ``animal_art`` mirrors for the other
direction and caches both.
"""

from __future__ import annotations

import math

import pygame

from .animal_paint import (
    OUTLINE,
    _arc,
    _ellipse,
    _eyes,
    _poly,
)
from .animal_parts import (
    _Geo,
    _draw_ears,
    _draw_features,
    _draw_legs,
    _draw_muzzle,
    _draw_tail,
    _pattern_layer,
)
from .animal_specs import AnimalSpec

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
