"""Painted eye layers, sized at spawn and shared between both eyes."""

from __future__ import annotations

import logging
import math
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pygame

from . import assets

_kit: dict[str, tuple[pygame.Surface, ...]] = {}
_SQUASH = (1.0, .68, .38, .12)


def set_eye_art(mode: str, root: Path | None = None) -> None:
    """Load a complete kit from the asset root, or restore the original circles."""
    if mode not in ("painted", "traced", "drawn"):
        raise ValueError(f"Unknown eye art mode: {mode}")
    _kit.clear()
    _layers.cache_clear()
    if mode != "painted":
        return
    directory = (root if root is not None else assets.asset_root()) / "eyes"
    try:
        with (directory / "manifest.toml").open("rb") as stream:
            manifest = tomllib.load(stream)
        if manifest.get("schema") != 1:
            raise ValueError("expected schema = 1")
        kit = {}
        for kind in ("whites", "irises"):
            files = manifest[kind]
            if not isinstance(files, list) or not files:
                raise ValueError(f"expected a nonempty {kind} list")
            images = []
            for filename in files:
                path = Path(filename)
                if path.anchor or ".." in path.parts or path.suffix.lower() not in (".webp", ".png"):
                    raise ValueError(f"invalid eye asset path {filename!r}")
                image = assets.load_image(directory / path)
                bounds = image.get_bounding_rect()
                if not bounds:
                    raise ValueError(f"empty eye layer {filename}")
                images.append(image.subsurface(bounds))
            kit[kind] = tuple(images)
        _kit.update(kit)
    except (KeyError, OSError, TypeError, ValueError, pygame.error, NotImplementedError) as exc:
        logging.getLogger(__name__).info("Using drawn eyes: %s", exc)


@lru_cache(maxsize=96)
def _layers(kind: str, variant: int, px: int) -> tuple[pygame.Surface, ...]:
    source = _kit[kind][variant]
    w, h = source.get_size()
    scale = px / max(w, h)
    size = max(1, round(w * scale)), max(1, round(h * scale))
    opened = pygame.transform.smoothscale(source, size)
    frames = [opened]
    for fraction in _SQUASH[1:]:
        height = max(1, round(size[1] * fraction))
        frames.append(pygame.transform.smoothscale(opened, (size[0], height)))
    return tuple(frames)


@dataclass(frozen=True)
class EyeFrames:
    white: tuple[pygame.Surface, ...]
    iris: tuple[pygame.Surface, ...]
    travel: float


def prepare_eye(radius: int, variant: int = 0) -> EyeFrames | None:
    if not _kit:
        return None
    group, white_id = divmod(variant, len(_kit["whites"]))
    iris_id = (white_id + group) % len(_kit["irises"])
    white = _layers("whites", white_id, max(1, 2 * radius))
    diameter = min(white[0].get_size())
    iris_px = max(1, round(diameter * .55))
    iris = _layers("irises", iris_id, iris_px)
    # Allow for the slightly irregular painted rim, including rounding at small sizes.
    travel = max(0., .45 * diameter - iris_px / 2 - 1)
    return EyeFrames(white, iris, travel)


def _offset(dx: float, dy: float, limit: float) -> tuple[int, int]:
    length = math.hypot(dx, dy)
    scale = limit / length if length > limit else 1.
    return int(dx * scale), int(dy * scale)


def draw_original_eye(surface: pygame.Surface, center: tuple[int, int], radius: int,
                      look_dx: float, look_dy: float) -> None:
    x, y = center
    pygame.draw.circle(surface, (25, 25, 30), center, radius + 2)
    pygame.draw.circle(surface, (255, 255, 255), center, radius)
    pygame.draw.circle(surface, (25, 25, 30), (x + int(look_dx), y + int(look_dy)),
                       max(3, radius // 2))


def draw_eye(surface: pygame.Surface, center: tuple[int, int], radius: int,
             look_dx: float, look_dy: float, blink: float = 0., *,
             art: EyeFrames | None = None) -> None:
    """Look offsets are pixels. Pass the spawn-time frames to draw by blits alone."""
    if art is None:
        art = prepare_eye(radius)
    if art is None:
        draw_original_eye(surface, center, radius, look_dx, look_dy)
        return
    step = round(max(0., min(1., blink)) * (len(_SQUASH) - 1))
    white, iris = art.white[step], art.iris[step]
    dx, dy = _offset(look_dx, look_dy, art.travel)
    x, y = center
    surface.blit(white, white.get_rect(center=center))
    surface.blit(iris, iris.get_rect(center=(x + dx, y + int(dy * _SQUASH[step]))))


@dataclass(frozen=True)
class PipIrises:
    native_size: tuple[int, int]
    eye_at: tuple[float, float]
    white_radius: float
    sizes: tuple[pygame.Surface, ...]

    def draw(self, surface: pygame.Surface, rect: pygame.Rect, gaze: tuple[float, float]) -> None:
        w, h = self.native_size
        # The smaller axis still fits a round iris when Pip ducks or lands.
        radius = self.white_radius * min(rect.w / w, rect.h / h)
        px = max(1, min(len(self.sizes), int(1.4 * radius)))
        iris = self.sizes[px - 1]
        travel = max(0., radius - px / 2 - 1)
        dx, dy = _offset(gaze[0] * travel, gaze[1] * travel, travel)
        ex, ey = self.eye_at
        for fx in (ex, 1 - ex):
            center = rect.x + round(fx * rect.w) + dx, rect.y + round(ey * rect.h) + dy
            surface.blit(iris, iris.get_rect(center=center))


def prepare_pip(frame: pygame.Surface, eye_at: tuple[float, float],
                size: tuple[int, int]) -> PipIrises | None:
    """Measure the common clear disc around the two manifest anchors, once at spawn."""
    if not _kit:
        return None
    w, h = frame.get_size()
    ex, ey = eye_at
    cy = ey * h
    # Bound the search by the midpoint between the eyes and the native canvas.
    radius = min(abs(.5 - ex) * w, min(ex, 1 - ex) * w, cy, h - cy)
    for fx in (ex, 1 - ex):
        cx = fx * w
        for y in range(max(0, math.floor(cy - radius)), min(h, math.ceil(cy + radius) + 1)):
            for x in range(max(0, math.floor(cx - radius)), min(w, math.ceil(cx + radius) + 1)):
                if min(frame.get_at((x, y))) < 195:  # exclude keyline, skin and transparent edges
                    radius = min(radius, math.hypot(x - cx, y - cy))
    # One native pixel clears the boundary through both smoothscale and integer blit rounding.
    radius -= 1
    if radius <= 0:
        return None
    maximum = max(1, int(1.4 * radius * min(size[0] / w, size[1] / h)))
    sizes = tuple(_layers("irises", 0, px)[0] for px in range(1, maximum + 1))
    return PipIrises((w, h), eye_at, radius, sizes)
