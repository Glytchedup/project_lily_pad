"""The registered, right-facing animal frames in painted/manifest.toml."""

from __future__ import annotations

import logging
import math
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pygame

from . import assets
from .animal_specs import SPECS

log = logging.getLogger(__name__)
Point = tuple[float, float]
_root: Path | None = None
_IMAGE_ERRORS = (OSError, ValueError, pygame.error, NotImplementedError)


class FrameUnavailable(KeyError):
    """A previously loaded trial entry failed to decode at a new size."""


@dataclass
class _Animal:
    paths: dict[str, Path]
    native_size: tuple[int, int]
    eye: Point
    back: Point
    frames: dict[str, pygame.Surface]


_animals: dict[str, _Animal | None] = {}


def configure(root: Path) -> None:
    """Select the startup asset root, dropping data from any previous trial."""
    global _root
    _root = root / "painted"
    _rows.cache_clear()
    _animals.clear()


def _directory() -> Path:
    return _root if _root is not None else assets.asset_root() / "painted"


@cache
def _rows() -> dict:
    directory = _directory()
    try:
        with (directory / "manifest.toml").open("rb") as stream:
            manifest = tomllib.load(stream)
        if type(manifest.get("schema")) is not int or manifest["schema"] != 1:
            raise ValueError("expected schema = 1")
        rows = manifest.get("animals", {})
        if not isinstance(rows, dict):
            raise ValueError("expected an animals table")
        return rows
    except (OSError, ValueError) as exc:
        log.warning("Ignoring painted manifest in %s: %s", directory, exc)
        return {}


def _point(row: dict, key: str) -> Point:
    point = row[key]
    if not isinstance(point, list) or len(point) != 2 or not all(
        type(v) in (float, int) and 0 <= v <= 1 for v in point
    ):
        raise ValueError(f"invalid {key} coordinates")
    return point[0], point[1]


def _frame_path(filename: str) -> Path:
    relative = Path(filename)
    if (relative.anchor or ".." in relative.parts
            or relative.suffix.lower() not in (".png", ".webp")):
        raise ValueError(f"invalid painted frame path {filename!r}")
    return _directory() / relative


def _decode(paths: dict[str, Path], native_height: int) -> dict[str, pygame.Surface]:
    frames = {pose: assets.load_image(path) for pose, path in paths.items()}
    size = frames["idle"].get_size()
    if size[1] != native_height or any(frame.get_size() != size for frame in frames.values()):
        raise ValueError("frames must share the declared native canvas")
    for pose, frame in frames.items():
        if frame.get_bitsize() != 32 or not frame.get_masks()[3]:
            # The loader retains indexed PNGs' format when there is no display.
            rgba = pygame.Surface(size, pygame.SRCALPHA)
            rgba.blit(frame, (0, 0))
            frames[pose] = rgba
    return frames


def _load(name: str) -> _Animal | None:
    rows = _rows()
    if name not in rows:
        return None
    row = rows[name]
    try:
        if row["view"] not in ("side", "front"):
            raise ValueError("invalid view")
        height = row["native_height"]
        if type(height) is not int or height <= 0:
            raise ValueError("invalid native_height")
        files = row["frames"]
        paths = {pose: _frame_path(files[pose]) for pose in ("idle", "blink")}
        if "step" in files:
            paths["step"] = _frame_path(files["step"])
        _point(row, "anchor")
        eye, back = _point(row, "eye_at"), _point(row, "back_at")
        frames = _decode(paths, height)
        return _Animal(paths, frames["idle"].get_size(), eye, back, frames)
    except (KeyError, TypeError, *_IMAGE_ERRORS) as exc:
        log.warning("Ignoring painted animal %s: %s", name, exc)
        return None


def _lookup(name: str) -> _Animal | None:
    if name not in _animals:
        _animals[name] = _load(name)
    return _animals[name]


def has(name: str) -> bool:
    """Validate an entire entry together, including decoding its listed poses."""
    return _lookup(name) is not None


def _animal(name: str) -> _Animal:
    entry = _lookup(name)
    if entry is None:
        raise KeyError(name)
    return entry


def aspect(name: str) -> float:
    w, h = _animal(name).native_size
    return w / h


def eye_at(name: str) -> Point:
    return _animal(name).eye


def back_at(name: str) -> Point:
    return _animal(name).back


def _step_kind(name: str) -> str:
    spec = SPECS.get(name)
    return spec.build if spec else "front"


def has_step(name: str) -> bool:
    return "step" in _animal(name).paths or _step_kind(name) in ("swimmer", "floater")


def _tail_flex(base: pygame.Surface) -> pygame.Surface:
    """Bend only the rear 35% of the canvas, joining the body at zero offset."""
    w, h = base.get_size()
    rear = max(1, round(w * 0.35))
    out = base.copy()
    out.fill((0, 0, 0, 0), (0, 0, rear, h))
    for x in range(rear):
        phase = (rear - 1 - x) / max(1, rear - 1)
        dy = round(h * 0.04 * math.sin(1.5 * math.pi * phase))
        out.blit(base, (x, dy), (x, 0, 1, h))
    return out


def _compress(base: pygame.Surface, width: float, height: float) -> pygame.Surface:
    w, h = base.get_size()
    scaled = pygame.transform.scale(base, (max(1, int(w * width)), max(1, int(h * height))))
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    out.blit(scaled, scaled.get_rect(midbottom=(w // 2, h)))
    return out


def build(name: str, height: int, pose: str = "idle") -> pygame.Surface:
    """Return a shared pose. Retain decoded frames only at the active size."""
    animal = _animal(name)
    height = max(1, int(height))
    frames = animal.frames
    if frames["idle"].get_height() != height:
        w, h = animal.native_size
        if frames["idle"].get_height() != h:
            # Resize from the native canvas even after a display-size change.
            try:
                frames = _decode(animal.paths, h)
                if frames["idle"].get_size() != animal.native_size:
                    raise ValueError("native canvas changed since startup")
            except _IMAGE_ERRORS as exc:
                _animals[name] = None
                log.warning("Ignoring painted animal %s: %s", name, exc)
                raise FrameUnavailable(name) from exc
        if height != h:
            size = (max(1, round(w * height / h)), height)
            frames = {p: pygame.transform.smoothscale(frames[p], size) for p in animal.paths}
        animal.frames = frames
    if pose not in frames:
        idle = frames["idle"]
        if pose == "squash":
            frames[pose] = _compress(idle, 1.14, 0.86)
        elif pose == "step" and _step_kind(name) == "swimmer":
            frames[pose] = _tail_flex(idle)
        elif pose == "step" and _step_kind(name) == "floater":
            frames[pose] = _compress(idle, 1.0, 0.92)
        else:
            return idle
    return frames[pose]
