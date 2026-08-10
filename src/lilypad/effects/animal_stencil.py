"""Sprites built from a real animal outline instead of stacked ellipses.

A trial, currently covering three creatures (see ``animal_specs.STENCILS``).
The rest of the cast is still assembled from primitives by ``animal_art``, and
both kinds go through the same ``animal_sprite`` front door, so nothing
downstream — mirroring, squash, the ``(name, height, pose)`` cache, the gaits —
knows or cares which one it got.

The whole idea rests on one property of the source art: a PhyloPic silhouette
is a **solid black shape with a real alpha channel**. That makes it a stencil,
not a picture. Filling it with ``BLEND_RGB_MAX`` replaces the colour and leaves
the alpha — and therefore the outline — untouched, at any size. So the shape
comes from an anatomist and everything you actually notice about the animal
still comes from this file.

Cost lives entirely at cache-fill time, which is why it can be extravagant:
rasterising, cropping, rescaling, masking a coat pattern and stroking an
outline is several milliseconds per sprite, and it happens once per
``(name, height, pose)``. The per-frame blit is one alpha surface, exactly as
before.

Why not just draw better ellipses? Because the failure of the procedural
animals is not detail, it is *proportion* — a giraffe is a giraffe because of
the neck-to-leg ratio, and that is precisely what a stack of ellipses is bad at
and what a traced outline gets right for free.
"""

from __future__ import annotations

import logging
import math
import random
import re
import zlib
from pathlib import Path

import pygame

from .animal_specs import SPECS, STENCILS, AnimalSpec, StencilSpec

log = logging.getLogger(__name__)

#: Where the vendored outlines live. See ``CREDITS.md`` there for licences.
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "silhouettes"

OUTLINE = (34, 30, 38)
EYE_WHITE = (255, 255, 255)
PUPIL = (28, 28, 34)

#: Dark keyline thickness as a fraction of sprite height. Thin legs — a
#: giraffe's are a couple of pixels wide at any sane sprite size — disappear
#: against the pond without this.
_STROKE = 0.014

_svg_cache: dict[str, bytes] = {}
_shape_cache: dict[tuple[str, int], pygame.Surface] = {}
_body_cache: dict[tuple[str, int], pygame.Surface] = {}
_aspect_cache: dict[str, float] = {}

_VIEWBOX = re.compile(rb'viewBox\s*=\s*"([\d.\s+-]+)"')


class StencilUnavailable(RuntimeError):
    """This build of SDL_image cannot rasterise SVG, so stencils are off."""


def _supported() -> bool:
    return hasattr(pygame.image, "load_sized_svg")


def available() -> bool:
    """True if stencil sprites can actually be built on this machine.

    Checked once at startup rather than trusted: SVG support is an SDL_image
    build option, and a Pi that lacks it must fall back to the procedural
    animals rather than crash on the first giraffe.
    """
    if not _supported():
        return False
    try:
        for name in STENCILS:
            _shape(name, 64)
    except Exception:                      # noqa: BLE001 — any failure disqualifies
        log.exception("silhouette sprites unavailable, falling back to drawn animals")
        return False
    return True


def names() -> tuple[str, ...]:
    return tuple(sorted(STENCILS))


def has(name: str) -> bool:
    return name in STENCILS


# ---------------------------------------------------------------------------
# Loading the outline
# ---------------------------------------------------------------------------
def _svg(name: str) -> bytes:
    data = _svg_cache.get(name)
    if data is None:
        data = (ASSET_DIR / STENCILS[name].file).read_bytes()
        _svg_cache[name] = data
    return data


def _intrinsic_aspect(name: str) -> float:
    """Width/height from the SVG's own viewBox.

    These outlines are traced individually and their canvases are all different
    shapes — a giraffe is taller than it is wide, a humpback four times wider
    than tall. Asking for the wrong box would letterbox the animal inside its
    own sprite and quietly shrink it.
    """
    cached = _aspect_cache.get(name)
    if cached is not None:
        return cached
    m = _VIEWBOX.search(_svg(name))
    ratio = 1.0
    if m:
        nums = [float(v) for v in m.group(1).split()]
        if len(nums) == 4 and nums[3] > 0:
            ratio = nums[2] / nums[3]
    _aspect_cache[name] = ratio
    return ratio


def _shape(name: str, height: int) -> pygame.Surface:
    """The bare outline, tight-cropped, exactly ``height`` tall, facing right."""
    key = (name, height)
    cached = _shape_cache.get(key)
    if cached is not None:
        return cached
    if not _supported():
        raise StencilUnavailable("SDL_image has no SVG support")

    spec = STENCILS[name]
    ratio = _intrinsic_aspect(name)
    raw = pygame.image.load_sized_svg(
        ASSET_DIR / spec.file, (max(2, int(round(height * ratio))), max(2, height)))

    # Trim the transparent margin the SVG canvas may carry, so the sprite box
    # is the animal. Everything that positions an animal on screen assumes
    # that, and a stray margin reads as the creature floating.
    bounds = raw.get_bounding_rect()
    if bounds.width <= 0 or bounds.height <= 0:
        raise StencilUnavailable(f"{name} rasterised to nothing")
    shape = raw.subsurface(bounds).copy()

    if shape.get_height() != height:
        scale = height / shape.get_height()
        shape = pygame.transform.smoothscale(
            shape, (max(2, int(round(shape.get_width() * scale))), height))
    if spec.faces_left:
        shape = pygame.transform.flip(shape, True, False)

    _shape_cache[key] = shape
    return shape


def aspect(name: str) -> float:
    """Measured width/height of the finished sprite, outline included."""
    shape = _shape(name, 256)
    stroke = max(1, int(round(256 * _STROKE)))
    return (shape.get_width() + 2 * stroke) / 256.0


# ---------------------------------------------------------------------------
# Painting it
# ---------------------------------------------------------------------------
def _tinted(shape: pygame.Surface, colour) -> pygame.Surface:
    """``shape`` recoloured, alpha untouched.

    ``BLEND_RGB_MAX`` against a black silhouette is just "replace the colour":
    max(0, c) == c. Alpha is left alone by the RGB-only blend, which is the
    whole trick — the anti-aliased edge survives intact.
    """
    out = shape.copy()
    out.fill(colour, special_flags=pygame.BLEND_RGB_MAX)
    return out


def _mask(shape: pygame.Surface) -> pygame.Surface:
    """White copy of the shape, for clipping a layer to the animal.

    Multiplying a layer by this leaves its colours alone (x * 255/255) and
    multiplies its alpha by the animal's, so anything painted outside the body
    simply vanishes.
    """
    return _tinted(shape, (255, 255, 255))


def _clip(layer: pygame.Surface, shape: pygame.Surface) -> pygame.Surface:
    layer.blit(_mask(shape), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return layer


def _vertical_fade(w: int, h: int, top: float, bottom: float) -> pygame.Surface:
    """White, transparent above ``top``, opaque below ``bottom``.

    Drawn as a handful of bands rather than per-pixel: at sprite sizes the
    seams are invisible and this stays a cheap blit loop.
    """
    fade = pygame.Surface((w, h), pygame.SRCALPHA)
    y0, y1 = int(h * top), max(int(h * bottom), int(h * top) + 1)
    fade.fill((255, 255, 255, 255), pygame.Rect(0, y1, w, h - y1))
    bands = 14
    for i in range(bands):
        a = int(255 * (i + 1) / bands)
        ya = y0 + (y1 - y0) * i // bands
        yb = y0 + (y1 - y0) * (i + 1) // bands
        fade.fill((255, 255, 255, a), pygame.Rect(0, ya, w, max(1, yb - ya)))
    return fade


def _shade_underside(out: pygame.Surface, shape: pygame.Surface,
                     colour, top: float, bottom: float) -> None:
    layer = _tinted(shape, colour)
    layer.blit(_vertical_fade(*shape.get_size(), top, bottom),
               (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    out.blit(layer, (0, 0))


def _pattern(out: pygame.Surface, shape: pygame.Surface, spec: AnimalSpec,
             name: str) -> None:
    """Coat markings, clipped to the animal.

    Seeded from the name via CRC32, not ``hash()`` — string hashing is salted
    per process, so a giraffe would come out with different spots every launch.
    """
    kind = spec.pattern
    if kind == "none":
        return
    w, h = shape.get_size()
    layer = pygame.Surface((w, h), pygame.SRCALPHA)
    rng = random.Random(zlib.crc32(name.encode()))

    if kind == "patch":
        step = max(8, h // 9)
        for gy in range(0, h, step):
            for gx in range(0, w, step):
                cx = gx + step * 0.5 + rng.uniform(-step * 0.18, step * 0.18)
                cy = gy + step * 0.5 + rng.uniform(-step * 0.18, step * 0.18)
                r = step * rng.uniform(0.28, 0.38)
                pts = []
                sides = 6
                for i in range(sides):
                    a = 2 * math.pi * i / sides + rng.uniform(-0.22, 0.22)
                    rr = r * rng.uniform(0.82, 1.18)
                    pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
                pygame.draw.polygon(layer, spec.accent, pts)
    elif kind == "stripes":
        for x in range(0, w, max(6, w // 22)):
            tilt = rng.uniform(-0.12, 0.12) * h
            pygame.draw.polygon(layer, spec.accent, [
                (x, 0), (x + max(3, w // 60), 0),
                (x + max(3, w // 60) + tilt, h), (x + tilt, h)])
    elif kind in ("spots", "speckle"):
        n = 26 if kind == "spots" else 60
        r_lo, r_hi = (0.030, 0.055) if kind == "spots" else (0.010, 0.020)
        for _ in range(n):
            pygame.draw.circle(
                layer, spec.accent,
                (rng.randrange(w), rng.randrange(h)),
                max(1, int(h * rng.uniform(r_lo, r_hi))))

    out.blit(_clip(layer, shape), (0, 0))


def _eye(out: pygame.Surface, x: int, y: int, r: int, pose: str) -> None:
    """A deliberately oversized cartoon eye.

    This is the one place the trial fights its own source material. A traced
    outline is anatomically right, which means the real eye is tiny and the
    animal reads as a museum diagram. An eye three or four times life size is
    what makes it read as a character instead — and it is doing most of the
    work of "cute" on its own, since the proportions underneath cannot.
    """
    if pose == "blink":
        pygame.draw.arc(out, PUPIL, pygame.Rect(x - r, y - r, 2 * r, 2 * r),
                        math.pi * 1.15, math.pi * 1.85, max(2, r // 2))
        return
    pygame.draw.circle(out, EYE_WHITE, (x, y), r)
    pygame.draw.circle(out, OUTLINE, (x, y), r, max(1, r // 5))
    pygame.draw.circle(out, PUPIL, (x + r // 4, y + r // 6), max(2, int(r * 0.52)))
    pygame.draw.circle(out, EYE_WHITE, (x + r // 2, y - r // 3), max(1, r // 5))


def _stroke_px(height: int) -> int:
    return max(1, int(round(height * _STROKE)))


def _painted(name: str, height: int) -> pygame.Surface:
    """Everything except the eye, cached.

    The eye is the only thing a pose changes, and the rest — eight offset
    stamps of the whole sprite for the keyline, two shading passes, a coat
    pattern — is by far the expensive part. Splitting here means ``blink``
    costs one copy and two circles instead of a second full repaint.
    """
    key = (name, height)
    cached = _body_cache.get(key)
    if cached is not None:
        return cached

    stencil = STENCILS[name]
    spec = SPECS[name]
    stroke = _stroke_px(height)
    shape = _shape(name, max(2, height - 2 * stroke))
    sw, sh = shape.get_size()

    out = pygame.Surface((sw + 2 * stroke, sh + 2 * stroke), pygame.SRCALPHA)

    # Keyline: the shape stamped in the outline colour all around, then the
    # coloured animal dropped on top. Eight offsets is enough to read as a
    # ring; a circle of them would cost more and look the same.
    dark = _tinted(shape, OUTLINE)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                   (-1, -1), (1, -1), (-1, 1), (1, 1)):
        out.blit(dark, (stroke + dx * stroke, stroke + dy * stroke))

    body = _tinted(shape, spec.body)
    _shade_underside(body, shape, spec.shade, 0.46, 0.86)
    if stencil.belly > 0.0:
        _shade_underside(body, shape, spec.accent, 1.0 - stencil.belly,
                         1.0 - stencil.belly * 0.35)
    _pattern(body, shape, spec, name)
    out.blit(body, (stroke, stroke))

    _body_cache[key] = out
    return out


def build(name: str, height: int, pose: str) -> pygame.Surface:
    """Finished sprite: outline, body, underside, markings, eye.

    Faces right, like every other side-on animal. ``squash`` is not handled
    here — ``animal_art`` derives it from ``idle`` for the whole cast at once.
    """
    stencil = STENCILS[name]
    stroke = _stroke_px(height)
    out = _painted(name, height).copy()
    sw = out.get_width() - 2 * stroke
    sh = out.get_height() - 2 * stroke

    ex, ey = stencil.eye_at
    _eye(out, stroke + int(sw * ex), stroke + int(sh * ey),
         max(3, int(height * stencil.eye)), pose)
    return out
