"""Sticker album: the first time each animal turns up, a small painted portrait
of it flies into a strip along the top edge.

The strip shows for ``HOLD_SECONDS`` after each new sticker and then slides
back up out of sight. During attract mode it stays down and shows the whole
collection ("Your collection"). Nothing is persisted: "today" means "since
power-on" (see ``lilypad.stats``).

Performance rules (matching ``particles.py``): portraits are built once, at
cache time, and cached by ``(name, size, mode)``. The strip itself is
composited onto one cached surface that is rebuilt only when the collection or
the mode changes, so a visible frame costs one alpha blit plus one blit per
sticker still in flight. The module draws nothing and uses no random numbers
while the album is off: ``create_album(False, ...)`` returns ``None``.

Portraits are crops of each *painted* idle frame: a square around the head,
centred on the manifest ``eye_at`` and sized from the canvas height, shifted to
stay inside the canvas, then scaled to ``PORTRAIT_PX``. The crop is taken from a
private decode of the frame file, never through ``painted.build`` (which would
resize and replace the engine's shared display-size frames). Animals with no
painted art get a drawn-art fallback.
"""

from __future__ import annotations

import logging
import math
import tomllib
from pathlib import Path

import pygame

from . import animal_art, assets, painted

log = logging.getLogger(__name__)

REF_HEIGHT = 1080           # the strip is specified at 1080p and scaled from it
PORTRAIT_PX = 96            # portrait edge at 1080p
STRIP_PX = 110              # strip height at 1080p
FLIGHT_SECONDS = 0.5        # animal position -> strip slot
HOLD_SECONDS = 2.0          # strip stays down this long after a new sticker
SLIDE_SECONDS = 0.25        # slide down / tuck up
HEAD_FRACTION = 0.65        # head square side as a fraction of the canvas height
MAX_DT = 0.25               # one long hitch must not teleport the animation

_TILE_TOP = (30, 56, 92)
_TILE_BOTTOM = (14, 26, 52)
_BORDER = (244, 247, 255)

Point = tuple[float, float]


# --------------------------------------------------------------------------
# Optional painted frames: assets/album/manifest.toml
# --------------------------------------------------------------------------

def album_assets(root: Path | None = None) -> dict[str, Path]:
    """Return ``{"strip": path, "card": path}`` for whichever files the manifest
    names and are present. A missing or malformed manifest yields ``{}``."""
    directory = (root if root is not None else assets.asset_root()) / "album"
    found: dict[str, Path] = {}
    try:
        with (directory / "manifest.toml").open("rb") as stream:
            manifest = tomllib.load(stream)
        if type(manifest.get("schema")) is not int or manifest["schema"] != 1:
            raise ValueError("expected schema = 1")
        for key in ("strip", "card"):
            filename = manifest.get(key)
            if not isinstance(filename, str):
                continue
            relative = Path(filename)
            if (relative.anchor or ".." in relative.parts
                    or relative.suffix.lower() not in (".png", ".webp", ".jpg", ".jpeg")):
                raise ValueError(f"invalid {key} path {filename!r}")
            path = directory / relative
            if path.is_file():
                found[key] = path
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log.warning("Ignoring album manifest in %s: %s", directory, exc)
        return {}
    return found


def load_backdrop(path: Path | None, size: tuple[int, int]) -> pygame.Surface | None:
    """Decode a painted backdrop scaled to ``size``; ``None`` if absent or bad."""
    if path is None:
        return None
    try:
        image = assets.load_image(path)
        if image.get_size() != size:
            image = pygame.transform.smoothscale(image, size)
        return image
    except (OSError, ValueError, pygame.error, NotImplementedError) as exc:
        log.warning("Album backdrop %s unusable, drawing instead: %s", path, exc)
        return None


# --------------------------------------------------------------------------
# Portraits
# --------------------------------------------------------------------------

def head_rect(canvas: tuple[int, int], eye: Point, fraction: float = HEAD_FRACTION
              ) -> pygame.Rect:
    """Square around the head, sized from the canvas height, kept in bounds."""
    cw, ch = canvas
    side = max(1, min(round(ch * fraction), cw, ch))
    x = round(eye[0] * cw - side / 2)
    y = round(eye[1] * ch - side / 2)
    return pygame.Rect(min(max(0, x), cw - side), min(max(0, y), ch - side), side, side)


_portraits: dict[tuple[str, int, str], pygame.Surface] = {}
_dimmed: dict[tuple[str, int, str], pygame.Surface] = {}
_sized: dict[tuple[str, int], pygame.Surface] = {}


def clear_cache() -> None:
    _portraits.clear()
    _dimmed.clear()
    _sized.clear()


def _painted_crop(name: str) -> pygame.Surface:
    """Head square of the painted idle frame, from a private native decode."""
    entry = painted._animal(name)
    frame = assets.load_image(entry.paths["idle"])
    rect = head_rect(frame.get_size(), entry.eye)
    crop = pygame.Surface(rect.size, pygame.SRCALPHA)    # also normalises indexed PNGs
    crop.blit(frame, (0, 0), rect)
    return crop


def _drawn_crop(name: str) -> pygame.Surface:
    """Fallback: the front of the drawn / traced sprite (side-on art faces right)."""
    sprite = animal_art.animal_sprite(name, 256)
    w, h = sprite.get_size()
    crop = pygame.Surface((min(w, h), h), pygame.SRCALPHA)
    crop.blit(sprite, (0, 0), pygame.Rect(max(0, w - h), 0, min(w, h), h))
    return crop


def _backdrop_tile(side: int) -> pygame.Surface:
    tile = pygame.Surface((side, side), pygame.SRCALPHA)
    for y in range(side):
        k = y / max(1, side - 1)
        colour = tuple(round(a + (b - a) * k) for a, b in zip(_TILE_TOP, _TILE_BOTTOM))
        pygame.draw.line(tile, (*colour, 255), (0, y), (side, y))
    return tile


def _sticker(art: pygame.Surface | None, label: str, size: int) -> pygame.Surface:
    """A rounded sticker tile with the art fitted inside (built 2x, then smoothed)."""
    big = size * 2
    radius = big // 5
    pad = max(2, big // 24)
    tile = _backdrop_tile(big)
    if art is not None and art.get_width() and art.get_height():
        inner = big - 2 * pad
        scale = inner / max(art.get_width(), art.get_height())
        fitted = pygame.transform.smoothscale(
            art, (max(1, round(art.get_width() * scale)), max(1, round(art.get_height() * scale))))
        tile.blit(fitted, fitted.get_rect(center=(big // 2, big // 2)))
    else:
        font = _font(round(big * 0.6))
        text = font.render(label[:1].upper() or "?", True, _BORDER)
        tile.blit(text, text.get_rect(center=(big // 2, big // 2)))
    mask = pygame.Surface((big, big), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    tile.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    pygame.draw.rect(tile, (*_BORDER, 255), tile.get_rect(), width=max(2, big // 32),
                     border_radius=radius)
    return pygame.transform.smoothscale(tile, (size, size))


def portrait(name: str, size: int = PORTRAIT_PX) -> pygame.Surface:
    """A cached square sticker portrait of ``name`` (shared: never draw onto it)."""
    size = max(8, int(size))
    mode = _mode(name)
    key = (name, size, mode)
    cached = _portraits.get(key)
    if cached is not None:
        return cached
    try:
        crop = _painted_crop(name) if mode == "painted" else _drawn_crop(name)
    except Exception as exc:                      # a bad frame must not cost a sticker
        log.warning("No portrait art for %s (%s); using a letter tile", name, exc)
        crop = None
    surface = _sticker(crop, name, size)
    _portraits[key] = surface
    return surface


def _mode(name: str) -> str:
    try:
        return "painted" if animal_art.resolved_mode(name) == "painted" else "drawn"
    except Exception:
        return "drawn"


def dim_portrait(name: str, size: int = PORTRAIT_PX) -> pygame.Surface:
    """The unlit version (summary grid): same sticker, darkened and see-through."""
    key = (name, max(8, int(size)), _mode(name))
    cached = _dimmed.get(key)
    if cached is None:
        cached = portrait(name, size).copy()
        cached.fill((105, 112, 140, 255), special_flags=pygame.BLEND_RGBA_MULT)
        cached.fill((255, 255, 255, 135), special_flags=pygame.BLEND_RGBA_MULT)
        _dimmed[key] = cached
    return cached


def _scaled(name: str, base: int, size: int) -> pygame.Surface:
    art = portrait(name, base)
    if size == base:
        return art
    key = (f"{name}:{base}", size)
    if key not in _sized:
        _sized[key] = pygame.transform.smoothscale(art, (size, size))
    return _sized[key]


_fonts: dict[int, pygame.font.Font] = {}


def _font(size: int) -> pygame.font.Font:
    if not pygame.font.get_init():
        pygame.font.init()
    size = max(8, int(size))
    if size not in _fonts:
        _fonts[size] = pygame.font.Font(None, size)       # bundled freesansbold
    return _fonts[size]


def _ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


# --------------------------------------------------------------------------
# The strip
# --------------------------------------------------------------------------

class _Flier:
    __slots__ = ("name", "start", "born", "index")

    def __init__(self, name: str, start: Point, born: float, index: int) -> None:
        self.name, self.start, self.born, self.index = name, start, born, index


class Album:
    """Sticker strip. Time-injected through ``update(dt)``; uses no randomness."""

    def __init__(self, size: tuple[int, int], root: Path | None = None) -> None:
        self.size = size
        w, h = size
        scale = h / REF_HEIGHT
        self.strip_h = max(8, round(STRIP_PX * scale))
        self.px = max(8, round(PORTRAIT_PX * scale))      # sticker edge in the strip
        self.margin = max(4, round(24 * scale))
        self.gap = max(2, round(10 * scale))
        self.caption_h = max(10, round(26 * scale))
        self.cap = max(1, (w - 2 * self.margin + self.gap) // (self.px + self.gap))
        self.seen: list[str] = []         # first-sighting order
        self.landed: list[str] = []       # stickers that have reached the strip
        self.attract = False
        self._known: set[str] = set()
        self._fliers: list[_Flier] = []
        self._t = 0.0
        self._hold_until = -math.inf
        self._offset = float(-self.strip_h)               # 0 = fully down
        self._composite: pygame.Surface | None = None
        self._composite_key: tuple | None = None
        found = album_assets(root)
        backdrop = load_backdrop(found.get("strip"), (w, self.strip_h))
        self.painted_strip = backdrop is not None
        self._bg = backdrop if backdrop is not None else self._drawn_bar()

    # ------------------------------------------------------------- building

    def _drawn_bar(self) -> pygame.Surface:
        w, h = self.size[0], self.strip_h
        bar = pygame.Surface((w, h), pygame.SRCALPHA)
        inset = max(4, w // 240)
        radius = max(6, h // 4)
        for grow, alpha in ((6, 26), (3, 44), (0, 0)):       # soft outer glow
            if grow:
                pygame.draw.rect(bar, (120, 170, 255, alpha),
                                 (inset - grow, -radius * 2, w - 2 * (inset - grow),
                                  h + radius * 2 - (6 - grow)), border_radius=radius + grow)
        pygame.draw.rect(bar, (12, 22, 44, 205),
                         (inset, -radius * 2, w - 2 * inset, h + radius * 2 - 6),
                         border_radius=radius)
        pygame.draw.rect(bar, (150, 190, 255, 120),
                         (inset, -radius * 2, w - 2 * inset, h + radius * 2 - 6),
                         width=2, border_radius=radius)
        return bar

    def _layout(self) -> tuple[list[str], int, int, int]:
        """(stickers shown, edge, step, y) for the current mode."""
        if self.attract:
            n = max(1, len(self.landed))
            usable = self.size[0] - 2 * self.margin
            edge = max(8, min(self.strip_h - self.caption_h - 8, self.px))
            if n * edge + (n - 1) * self.gap > usable:
                edge = max(8, (usable - (n - 1) * self.gap) // n)
            y = self.strip_h - edge - max(3, self.strip_h // 14)
            return list(self.landed), edge, edge + self.gap, y
        shown = self.landed[-self.cap:]
        return shown, self.px, self.px + self.gap, (self.strip_h - self.px) // 2

    def _slot_for(self, seen_index: int) -> tuple[int, int, int]:
        """Final (x, y, edge) of a flier that will be the ``seen_index``-th sticker
        in the recent (non-attract) layout."""
        slot = min(seen_index, self.cap - 1)
        return self.margin + slot * (self.px + self.gap), (self.strip_h - self.px) // 2, self.px

    def _build_composite(self) -> pygame.Surface:
        surface = self._bg.copy()
        shown, edge, step, y = self._layout()
        if self.attract and shown:
            font = _font(round(self.caption_h * 1.15))
            text = font.render("Your collection", True, (226, 236, 255))
            surface.blit(text, (self.margin, max(2, self.strip_h // 14)))
        for i, name in enumerate(shown):
            surface.blit(_scaled(name, self.px, edge), (self.margin + i * step, y))
        return surface

    # ----------------------------------------------------------------- feed

    def note_animal(self, name: str, pos: Point) -> bool:
        """An animal appeared at screen position ``pos`` (its centre). The first
        sighting of each name starts a sticker flight and returns True."""
        if name in self._known:
            return False
        self._known.add(name)
        index = len(self.seen)
        self.seen.append(name)
        self._hold_until = self._t + HOLD_SECONDS
        try:
            portrait(name, self.px)                       # build now, not mid-flight
        except Exception:
            log.exception("sticker portrait for %s failed", name)
        # Crossings spawn just off-screen and farm animals below the bottom edge.
        x = min(max(float(pos[0]), 0.0), float(self.size[0]))
        y = min(max(float(pos[1]), 0.0), float(self.size[1]))
        self._fliers.append(_Flier(name, (x, y), self._t, index))
        return True

    def set_attract(self, active: bool) -> None:
        self.attract = bool(active)

    # ---------------------------------------------------------- per frame

    @property
    def visible(self) -> bool:
        return self._offset > -self.strip_h

    def _wants_down(self) -> bool:
        if self._fliers or self._t < self._hold_until:
            return True
        return self.attract and bool(self.landed)

    def update(self, dt: float) -> None:
        dt = min(max(0.0, dt), MAX_DT)
        self._t += dt
        landed_any = False
        while self._fliers and self._t - self._fliers[0].born >= FLIGHT_SECONDS:
            self.landed.append(self._fliers.pop(0).name)
            landed_any = True
        target = 0.0 if self._wants_down() else float(-self.strip_h)
        step = self.strip_h * dt / SLIDE_SECONDS
        if self._offset < target:
            self._offset = min(target, self._offset + step)
        elif self._offset > target:
            self._offset = max(target, self._offset - step)
        if landed_any:
            self._composite_key = None

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible and not self._fliers:
            return
        if self.visible:
            key = (len(self.landed), self.attract)
            if self._composite is None or self._composite_key != key:
                self._composite = self._build_composite()
                self._composite_key = key
            surface.blit(self._composite, (0, round(self._offset)))
        for flier in self._fliers:
            k = _ease((self._t - flier.born) / FLIGHT_SECONDS)
            fx, fy, edge = self._slot_for(flier.index)
            tx, ty = fx + edge / 2, fy + edge / 2 + self._offset
            cx = flier.start[0] + (tx - flier.start[0]) * k
            cy = flier.start[1] + (ty - flier.start[1]) * k
            art = portrait(flier.name, self.px)
            surface.blit(art, (round(cx - art.get_width() / 2), round(cy - art.get_height() / 2)))

    def prewarm(self, names) -> None:
        """Build portraits ahead of time so a first sighting never hitches."""
        for name in names:
            try:
                portrait(name, self.px)
            except Exception:
                log.exception("prewarm portrait %s failed", name)


def create_album(enabled: bool, size: tuple[int, int], root: Path | None = None
                 ) -> Album | None:
    """``None`` when ``effects.album`` is off: legacy builds and draws nothing."""
    return Album(size, root) if enabled else None
