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

import logging

import pygame

from . import animal_stencil
from .animal_body import _BUILDERS
from .animal_farm import _BESPOKE_DRAWERS
from .animal_paint import _finish, _new_surface
from .animal_specs import SPECS

# Re-exported rather than moved: this module stays the front door to the whole
# cast, so every existing `from .animal_art import ...` keeps working.
from .animal_mini import mini_sprite

log = logging.getLogger(__name__)

__all__ = [
    "MINI_KINDS", "POSES", "animal_names", "animal_sprite",
    "animal_sprite_facing", "aspect", "faces_right", "mini_sprite",
    "set_silhouettes", "silhouettes_enabled",
]

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
#
# The mode is part of the key because the two art routes produce different
# sprites — and different *widths* — for the same name and height. Without it,
# flipping the setting mid-process would serve stale art forever.
_animal_cache: dict[tuple[str, int, str, bool], pygame.Surface] = {}
_flip_cache: dict[tuple[str, int, str, bool], pygame.Surface] = {}

#: Whether traced-outline sprites are in use for the creatures that have one.
#: Set once at startup by ``set_silhouettes``; off until then so that importing
#: this module never touches the filesystem or needs a display.
_silhouettes = False


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


def set_silhouettes(on: bool) -> bool:
    """Turn traced-outline sprites on or off, and report what actually happened.

    Returns False if they were asked for but this machine can't rasterise SVG
    — an SDL_image build option, so it has to be probed rather than assumed.
    A Pi without it falls back to the drawn animals and logs why, instead of
    dying on the first giraffe.
    """
    global _silhouettes
    wanted = bool(on)
    if wanted and not animal_stencil.available():
        log.warning("silhouette animals requested but unavailable — using drawn animals")
        wanted = False
    if wanted != _silhouettes:
        _silhouettes = wanted
        log.info("animal art: %s", "traced outlines" if wanted else "drawn")
    return wanted


def silhouettes_enabled() -> bool:
    return _silhouettes


def _use_stencil(name: str) -> bool:
    return _silhouettes and animal_stencil.has(name)


def aspect(name: str) -> float:
    if _use_stencil(name):
        return animal_stencil.aspect(name)
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
    key = (name, height, pose, _silhouettes)
    cached = _animal_cache.get(key)
    if cached is not None:
        return cached

    if pose == "squash":
        surf = _squash(animal_sprite(name, height, "idle"))
    elif _use_stencil(name):
        surf = animal_stencil.build(name, height, pose)
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
    key = (name, max(24, int(height)), pose if pose in POSES else "idle",
           _silhouettes)
    flipped = _flip_cache.get(key)
    if flipped is None:
        flipped = _finish(pygame.transform.flip(sprite, True, False))
        _flip_cache[key] = flipped
    return flipped
