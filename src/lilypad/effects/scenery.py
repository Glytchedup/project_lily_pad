"""Drawn and painted ponds, animated in seconds of play.

The classic pond caches three gradients sharing a moon and starfield.
Painted moods each supply an opaque plate and two scrolling strips. Their
skies dip between moons beneath one twinkle field, and the foreground water can
also be drawn over swimming animals.
"""

from __future__ import annotations

import logging
import math
import tomllib
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from threading import Thread

import pygame

from ..config import SceneConfig
from . import assets
from .base import EffectContext
from .glow import glow_sprite
from .layout import POND

VARIANTS: tuple[str, ...] = ("night", "dusk", "aurora")

# Vertical gradient endpoints per variant: (top color, waterline color).
# Kept dark — max channel ~40 — so foreground effects still pop; the aurora
# variant gets an extra teal/green band mixed in up to ~70.
_GRADIENTS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "night": ((6, 8, 16), (14, 22, 36)),
    "dusk": ((10, 6, 18), (26, 16, 38)),
    "aurora": ((6, 10, 14), (10, 26, 30)),
}

_MOON_COLOR = (232, 232, 214)
_STAR_COLOR = (215, 220, 235)
_PAD_DARK = (18, 62, 40)
_PAD_RIM = (34, 96, 58)
_LOTUS_PINK = (219, 112, 147)
_LOTUS_PINK_LIGHT = (255, 182, 200)

_STAR_COUNT = 30
_TWINKLE_COUNT = 10
_LILY_COUNT = 3
_VARIANT_PERIOD_S = 300.0
_CROSSFADE_S = 4.0
_MOON_BAND = 0.40  # Upper fraction of a plate containing the painted moons.
_SKY_RAMP = 3 / 8  # Fraction of a painted transition spent fading each sky.
_log = logging.getLogger(__name__)


def _lerp_color(a: tuple[int, int, int], b: tuple[int, int, int],
                 t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _gen_stars(rng, w: int, h: int, count: int) -> list[dict]:
    stars = []
    for _ in range(count):
        stars.append({
            "x": rng.uniform(0, w),
            "y": rng.uniform(0, h * 0.6),
            "r": rng.choice((1, 1, 2, 2, 3)),
        })
    return stars


def _gen_sky_layout(rng, w: int, h: int) -> dict:
    """Moon position, starfield, and twinkle selection — generated ONCE and
    shared by all three variants, so the crossfade blends one sky into
    different light rather than showing two moons and two starfields."""
    stars = _gen_stars(rng, w, h, _STAR_COUNT)
    order = list(range(len(stars)))
    rng.shuffle(order)
    return {
        "moon": (int(w * rng.uniform(0.70, 0.86)),
                 int(h * rng.uniform(0.10, 0.22)),
                 max(14, int(h * 0.045))),
        "stars": stars,
        "twinkle_idx": order[:min(_TWINKLE_COUNT, len(stars))],
        "twinkle_phases": [rng.uniform(0, math.tau) for _ in range(
            min(_TWINKLE_COUNT, len(stars)))],
    }


def _draw_moon(surf: pygame.Surface, moon: tuple[int, int, int], h: int,
                top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    cx, cy, r = moon
    pygame.draw.circle(surf, _MOON_COLOR, (cx, cy), r)
    # Crescent trick: overlay a second circle painted in the local gradient
    # color to bite a chunk out of the disc.
    bite_color = _lerp_color(top, bottom, cy / h)
    offset = int(r * 0.55)
    pygame.draw.circle(surf, bite_color, (cx + offset, cy - int(offset * 0.3)), int(r * 0.92))


def _build_variant(size: tuple[int, int], name: str, layout: dict) -> pygame.Surface:
    w, h = size
    top, bottom = _GRADIENTS[name]
    surf = pygame.Surface(size).convert()

    strip = max(2, h // 80)
    band_center = h * 0.32
    band_half = h * 0.10
    y = 0
    while y < h:
        t = y / h
        color = _lerp_color(top, bottom, t)
        if name == "aurora":
            dist = abs((y + strip / 2) - band_center)
            if dist < band_half:
                boost = 1.0 - dist / band_half
                color = (
                    color[0],
                    min(70, int(color[1] + 55 * boost)),
                    min(70, int(color[2] + 40 * boost)),
                )
        pygame.draw.rect(surf, color, (0, y, w, strip))
        y += strip

    _draw_moon(surf, layout["moon"], h, top, bottom)

    stars = layout["stars"]
    for s in stars:
        pygame.draw.circle(surf, _STAR_COLOR, (int(s["x"]), int(s["y"])), s["r"])

    return surf


def _build_lily_sprite(r: float, lotus: bool) -> pygame.Surface:
    """One cached SRCALPHA lily-pad sprite: dark green ellipse, lighter
    rim, and a pie-notch cut to transparent (drawing alpha 0 directly
    overwrites the pixel alpha — the standard pygame.draw cutout trick)."""
    rw = max(10, int(r))
    rh = max(6, int(r * 0.6))
    pad = 4
    size = (rw * 2 + pad * 2, rh * 2 + pad * 2)
    sprite = pygame.Surface(size, pygame.SRCALPHA)
    cx, cy = size[0] // 2, size[1] // 2
    rect = pygame.Rect(0, 0, rw * 2, rh * 2)
    rect.center = (cx, cy)
    pygame.draw.ellipse(sprite, _PAD_DARK, rect)
    pygame.draw.ellipse(sprite, _PAD_RIM, rect, max(1, rw // 12))

    notch_half = max(4, int(rh * 0.25))
    notch = [(cx, cy), (cx + rw + pad, cy - notch_half), (cx + rw + pad, cy + notch_half)]
    pygame.draw.polygon(sprite, (0, 0, 0, 0), notch)

    if lotus:
        fx, fy = cx - rw // 3, cy - int(rh * 0.5)
        pygame.draw.circle(sprite, _LOTUS_PINK, (fx, fy), max(4, rw // 4))
        pygame.draw.circle(sprite, _LOTUS_PINK_LIGHT, (fx, fy), max(2, rw // 7))

    return sprite.convert_alpha()


def _gen_lily_pads(rng, w: int, h: int, count: int) -> list[dict]:
    lotus_i = rng.randrange(count)
    pads = []
    for i in range(count):
        frac = 0.18 + 0.64 * (i / max(1, count - 1))
        x = frac * w + rng.uniform(-0.04, 0.04) * w
        r = rng.uniform(0.035, 0.055) * h
        # Center sits roughly one pad-half-height above the edge so most of
        # the pad (and the lotus) is actually visible, not a bottom sliver.
        y = h - r * 0.6 - rng.uniform(0.0, 0.015) * h
        pads.append({
            "x": x, "y": y, "r": r,
            "phase": rng.uniform(0, math.tau),
            "lotus": i == lotus_i,
        })
    return pads


@dataclass(frozen=True)
class _MoodFiles:
    order: int
    name: str
    plate: Path
    far_shore: Path
    near_water: Path
    plate_shift: float


def _mood_files(root: Path) -> list[_MoodFiles]:
    directory = root / "world"
    try:
        with (directory / "manifest.toml").open("rb") as stream:
            rows = tomllib.load(stream).get("moods", {})
        if not isinstance(rows, dict):
            raise ValueError("expected a moods table")
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        _log.warning("Ignoring pond manifest: %s", exc)
        return []

    files = []
    for name, row in rows.items():
        try:
            order = row["order"]
            if type(order) is not int:
                raise ValueError("order must be an integer")
            shift = row.get("plate_shift", 0.0)
            if type(shift) not in (int, float) or not 0 <= shift < 1:
                raise ValueError("plate_shift must be a downward fraction of the display height")
            paths = []
            for key in ("plate", "far_shore", "near_water"):
                path = Path(row[key])
                if path.anchor or ".." in path.parts:
                    raise ValueError(f"{key} must be relative to the manifest")
                paths.append(directory / path)
            files.append(_MoodFiles(order, name, *paths, plate_shift=shift))
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("Ignoring pond mood %s: %s", name, exc)
    return sorted(files, key=lambda mood: (mood.order, mood.name))


def _scaled(image: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    if image.get_size() == size:
        return image
    return pygame.transform.smoothscale(image, size)


def _opaque_plate(image: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    if image.get_alpha() is not None or image.get_colorkey() is not None or image.get_bitsize() < 24:
        image = image.convert()
        image.set_alpha(None)
        image.set_colorkey(None)
    return _scaled(image, size)


def _wrap_blit(target: pygame.Surface, image: pygame.Surface, x: int, y: int) -> None:
    """Cover a screen row even when drift or shake exhausts the overscan."""
    width = image.get_width()
    left = x % width
    if left:
        target.blit(image, (left - width, y))
    if left < target.get_width():
        target.blit(image, (left, y))


class _Mood:
    def __init__(self, files: _MoodFiles, size: tuple[int, int]) -> None:
        w, h = size
        self.files = files
        self.plate = _opaque_plate(assets.load_image(files.plate), size)
        shift = round(h * files.plate_shift)
        if shift:
            # Reflect the top rows into the exposed sky and crop the same depth of water.
            sky = pygame.transform.flip(self.plate.subsurface((0, 0, w, shift)), False, True)
            self.plate.scroll(dy=shift)
            self.plate.blit(sky, (0, 0))
        self.sky_color = pygame.transform.average_color(self.plate, (0, 0, w, 1))[:3]
        strip_width = math.ceil(w * 1.04)
        far_height = max(1, round(h * 0.30))
        near_height = max(1, round(h * 0.22))
        self.far = _scaled(assets.load_image(files.far_shore), (strip_width, far_height))
        self.near = _scaled(assets.load_image(files.near_water), (strip_width, near_height))
        self.far_y = round(h * POND.far_shore[1]) - far_height
        self.near_y = round(h * POND.foreground[1]) - near_height
        self.center = (w - strip_width) // 2
        self._underlays: list[tuple[pygame.Rect, pygame.Surface]] = []
        self.flat_card: pygame.Surface | None = None

    def draw_strips(self, target: pygame.Surface, far_x: int, near_x: int, top: int = 0) -> None:
        _wrap_blit(target, self.far, self.center + far_x, self.far_y - top)
        _wrap_blit(target, self.near, self.center + near_x, self.near_y - top)

    def prepare(self, flat: bool, card: pygame.Surface | None) -> None:
        """Bake in place, saving just the covered rows for instant recovery."""
        self.flat_card = None
        bake_plate = flat and card is None
        if bake_plate and not self._underlays:
            for strip, y in ((self.far, self.far_y), (self.near, self.near_y)):
                band = self.plate.get_rect().clip((0, y, self.plate.get_width(), strip.get_height()))
                self._underlays.append((band, self.plate.subsurface(band).copy()))
            self.draw_strips(self.plate, 0, 0)
        elif not bake_plate and self._underlays:
            for band, original in self._underlays:
                self.plate.blit(original, band)
            self._underlays.clear()
        if flat and card is not None:
            self.flat_card = card.copy()
            self.draw_strips(self.flat_card, 0, 0)


class _Fireflies:
    """A deterministic sum of slow waves, pulled briefly toward the last key."""

    def __init__(self, ctx: EffectContext) -> None:
        w, h = ctx.size
        rng = ctx.rng
        self.homes = [(rng.uniform(.08, .92) * w, rng.uniform(.32, .84) * h,
                       rng.uniform(0, math.tau), rng.uniform(.55, 1.15)) for _ in range(24)]
        self.frames = (glow_sprite((112, 128, 48), 2), glow_sprite((224, 224, 96), 4))
        self.size = ctx.size
        self.positions = [(x, y) for x, y, _, _ in self.homes]
        self.target = (0.0, 0.0)
        self.remaining = 0.0

    def attract(self, x: float, y: float) -> None:
        self.target = (x, y)
        self.remaining = 2.0

    def update(self, age: float, dt: float) -> None:
        w, h = self.size
        hold = min(self.remaining, dt)
        self.remaining -= hold
        pull = 1 - math.exp(-2.4 * hold)
        follow = 1 - math.exp(-1.6 * (dt - hold))
        for i, (x, y, phase, rate) in enumerate(self.homes):
            t = age * rate + phase
            home_x = x + w * (.045 * math.sin(t) + .022 * math.sin(.63 * t + phase))
            home_y = y + h * (.035 * math.cos(.81 * t) + .018 * math.sin(1.3 * t))
            old_x, old_y = self.positions[i]
            # Keep a little of each fly's own motion even at the same key.
            old_x += pull * (self.target[0] + .12 * (home_x - x) - old_x)
            old_y += pull * (self.target[1] + .12 * (home_y - y) - old_y)
            self.positions[i] = (old_x + follow * (home_x - old_x),
                                 old_y + follow * (home_y - old_y))

    def draw(self, surface: pygame.Surface, age: float, shake_x: int) -> None:
        for (_, _, phase, rate), (x, y) in zip(self.homes, self.positions):
            sprite = self.frames[int(age * rate + phase) % 2]
            surface.blit(sprite, sprite.get_rect(center=(int(x) + shake_x, int(y))),
                         special_flags=pygame.BLEND_ADD)


class _PaintedWorld:
    """One active mood and a single lookahead slot, including in-flight loads."""

    def __init__(self, files: list[_MoodFiles], size: tuple[int, int], scene: SceneConfig) -> None:
        self.size = size
        self.files = files
        self.period = scene.mood_minutes * 60
        self.fade_time = min(_CROSSFADE_S, self.period)
        self.elapsed = 0.0
        self.current = self._load_next(None)
        self.next = self._load_next(self.current.files) if self.current else None
        self.pending: Future[_Mood | None] | None = None
        self.card: pygame.Surface | None = None
        self.flat = False
        if self.next is not None:
            w, h = size
            self.dip = pygame.Surface((w, math.ceil(h * POND.sky[1])), pygame.SRCALPHA)
            self._color_dip()
            # Above the first strip the two scenes share either the fully covered sky
            # or the same storybook card. Only the lower rows need a blend buffer.
            self.scratch_top = max(0, min(self.current.far_y, self.current.near_y,
                                          math.ceil(h * _MOON_BAND)))
            self.scratch = pygame.Surface((w, h - self.scratch_top)).convert()
        self.parallax = scene.parallax
        self.drift_time = 0.0
        self.far_x = self.near_x = self.shake_x = 0
        self.shake_px = 0
        self.shake_duration = self.shake_left = 0.0

    def _color_dip(self) -> None:
        # Cache one shared sky per pair. Feather it out before the bank so standing
        # figures keep their footing, including in the moonless middle of the fade.
        color = _lerp_color(self.current.sky_color, self.next.sky_color, .5)
        w, h = self.dip.get_size()
        solid = math.ceil(self.size[1] * _MOON_BAND)
        self.dip.fill(color)
        for y in range(solid, h):
            alpha = round(255 * (h - y - 1) / (h - solid))
            self.dip.fill((*color, alpha), (0, y, w, 1))

    def _load_next(self, after: _MoodFiles | None) -> _Mood | None:
        # Only the loader touches the list until its result has been collected.
        index = self.files.index(after) + 1 if after is not None else 0
        while self.files:
            index %= len(self.files)
            files = self.files[index]
            if files == after:
                break
            try:
                return _Mood(files, self.size)
            except (OSError, ValueError, pygame.error, NotImplementedError) as exc:
                _log.warning("Ignoring pond mood %s: %s", files.name, exc)
                self.files.pop(index)
        return None

    def _prefetch(self) -> None:
        # Startup loaded the first pair. Later decodes never wait on input or exit.
        future = self.pending = Future()
        after = self.current.files

        def load() -> None:
            try:
                future.set_result(self._load_next(after))
            except Exception as exc:
                future.set_exception(exc)

        Thread(target=load, daemon=True, name="pond-mood-loader").start()

    def prepare(self, flat: bool, card: pygame.Surface | None) -> None:
        if flat == self.flat and card is self.card:
            return
        self.flat, self.card = flat, card
        self.current.prepare(flat, card)
        if self.next:
            self.next.prepare(flat, card)

    def shake(self, px: int, seconds: float) -> None:
        self.shake_px = max(0, int(px))
        self.shake_duration = self.shake_left = max(0.0, seconds)
        self.shake_x = self.shake_px if self.shake_left else 0

    def update(self, dt: float) -> None:
        if self.parallax:
            # A delayed frame cannot move the near strip by more than one pixel.
            self.drift_time += min(dt, 0.1)
            self.far_x = round(40 * math.sin(self.drift_time * .09))
            self.near_x = round(70 * math.sin(self.drift_time * .13))
        self.shake_left = max(0.0, self.shake_left - dt)
        self.shake_x = 0
        if self.shake_left:
            t = self.shake_duration - self.shake_left
            self.shake_x = round(self.shake_px * self.shake_left / self.shake_duration
                                 * math.cos(math.tau * 8 * t))
        if self.pending is not None and self.pending.done():
            self.next = self.pending.result()
            self.pending = None
            if self.next:
                self.next.prepare(self.flat, self.card)
                self._color_dip()
        if self.next is None:
            self.elapsed = min(self.period, self.elapsed + dt)
            return
        self.elapsed += dt
        if self.elapsed >= self.period + self.fade_time:
            if len(self.files) == 2:
                steps = int((self.elapsed - self.fade_time) // self.period)
                self.elapsed -= steps * self.period
                if steps % 2:
                    self.current, self.next = self.next, self.current
            else:
                self.elapsed -= self.period
                self.current, self.next = self.next, None
                self._prefetch()

    def _fade_alphas(self) -> tuple[int, int]:
        """Incoming landscape and sky-cover opacity, respectively."""
        if self.next is None or self.elapsed <= self.period:
            return 0, 0
        t = min(1., (self.elapsed - self.period) / self.fade_time)
        cover = 255 if self.card is None else 0
        if t < _SKY_RAMP:
            return 0, round(cover * t / _SKY_RAMP)
        if t > 1 - _SKY_RAMP:
            return 255, round(cover * (1 - t) / _SKY_RAMP)
        return round(255 * (t - _SKY_RAMP) / (1 - 2 * _SKY_RAMP)), cover

    def _draw_mood(self, target: pygame.Surface, mood: _Mood, top: int = 0) -> None:
        base = mood.flat_card or self.card or mood.plate
        _wrap_blit(target, base, self.shake_x, -top)
        if not self.flat:
            mood.draw_strips(target, self.far_x + self.shake_x, self.near_x + self.shake_x, top)

    def draw(self, target: pygame.Surface) -> None:
        alpha, cover = self._fade_alphas()
        self._draw_mood(target, self.next if alpha == 255 else self.current)
        if 0 < alpha < 255:
            self._draw_mood(self.scratch, self.next, self.scratch_top)
            self.scratch.set_alpha(alpha)
            target.blit(self.scratch, (0, self.scratch_top))
        if cover:
            self.dip.set_alpha(cover)
            target.blit(self.dip, (0, 0))

    def draw_near_water(self, target: pygame.Surface) -> None:
        if self.flat:
            return
        x = self.current.center + self.near_x + self.shake_x
        y = self.current.near_y
        alpha, _ = self._fade_alphas()
        if alpha == 255:
            _wrap_blit(target, self.next.near, x, y)
            return
        if alpha:
            scratch = self.scratch
            band = (0, y, self.size[0], self.current.near.get_height())
            scratch.blit(target, (0, 0), band)
            _wrap_blit(scratch, self.next.near, x, 0)
        _wrap_blit(target, self.current.near, x, y)
        if alpha:
            scratch.set_alpha(alpha)
            target.blit(scratch, (0, y), (0, 0, self.size[0], self.current.near.get_height()))


class PondBackground:
    """Persistent full-screen background — the engine owns exactly one and
    draws it before anything else each frame (update() always True)."""

    def __init__(self, ctx: EffectContext, scene: SceneConfig | None = None, *,
                 root: Path | None = None) -> None:
        """Pass cfg.scene and the startup asset_root(kiosk=...) to enable painted art."""
        self.ctx = ctx
        w, h = ctx.size
        self._age = 0.0
        self._painted: _PaintedWorld | None = None
        self._flies: _Fireflies | None = None
        self._sky = _gen_sky_layout(ctx.rng, w, h)  # one twinkle field for every mood
        if scene is not None and scene.world == "painted":
            files = _mood_files(root if root is not None else assets.asset_root(kiosk=True))
            if files:
                world = _PaintedWorld(files, ctx.size, scene)
                if world.current is not None:
                    self._painted = world
                    world.prepare(ctx.scale < 0.6, None)
                    # The painted sky ends at the shore, above the classic starfield.
                    for star in self._sky["stars"]:
                        star["y"] *= POND.sky[1] / .6
                    if scene.fireflies:
                        self._flies = _Fireflies(ctx)
                    return

        self._variants = [_build_variant(ctx.size, name, self._sky) for name in VARIANTS]

        self._lily_pads = _gen_lily_pads(ctx.rng, w, h, _LILY_COUNT)
        self._lily_sprites = [
            _build_lily_sprite(p["r"], p["lotus"]) for p in self._lily_pads
        ]

        self._index = 0
        self._next_index = 1 % len(self._variants)
        self._time_in_variant = 0.0
        self._crossfading = False
        self._crossfade_elapsed = 0.0

    @property
    def painted(self) -> bool:
        """Whether a usable painted world was resolved at startup."""
        return self._painted is not None

    def attract(self, x: float, y: float) -> None:
        if self._flies is not None:
            self._flies.attract(x, y)

    def shake(self, px: int, seconds: float) -> None:
        if self._painted is not None:
            self._painted.shake(px, seconds)

    def set_card(self, surface: pygame.Surface | None) -> None:
        """Replace the painted base plate until cleared. The caller's art is read-only."""
        if self._painted is not None:
            card = _opaque_plate(surface, self.ctx.size) if surface is not None else None
            self._painted.prepare(self.ctx.scale < 0.6, card)

    def draw_near_water(self, surface: pygame.Surface) -> None:
        """P3 foreground lip; may be clipped to swimmers' destination rectangles."""
        if self._painted is not None:
            self._painted.draw_near_water(surface)

    def update(self, dt: float) -> bool:
        self._age += dt
        if self._painted is not None:
            self._painted.prepare(self.ctx.scale < 0.6, self._painted.card)
            self._painted.update(dt)
            if self._flies is not None:
                self._flies.update(self._age, dt)
            return True
        self._time_in_variant += dt

        if not self._crossfading and self._time_in_variant >= _VARIANT_PERIOD_S:
            self._crossfading = True
            self._crossfade_elapsed = 0.0
            self._next_index = (self._index + 1) % len(self._variants)

        if self._crossfading:
            self._crossfade_elapsed += dt
            if self._crossfade_elapsed >= _CROSSFADE_S:
                self._crossfading = False
                self._index = self._next_index
                self._time_in_variant = 0.0

        return True  # persistent; the engine owns it

    def draw(self, surface: pygame.Surface) -> None:
        if self._painted is not None:
            self._painted.draw(surface)
            self._draw_twinkles(surface, self._painted.shake_x)
            if self._flies is not None:
                self._flies.draw(surface, self._age, self._painted.shake_x)
            return
        current = self._variants[self._index]
        surface.blit(current, (0, 0))

        if self._crossfading:
            incoming = self._variants[self._next_index]
            alpha = int(255 * min(1.0, self._crossfade_elapsed / _CROSSFADE_S))
            incoming.set_alpha(alpha)
            surface.blit(incoming, (0, 0))
            incoming.set_alpha(255)

        self._draw_twinkles(surface)
        self._draw_lily_pads(surface)

    def _draw_twinkles(self, surface: pygame.Surface, shake_x: int = 0) -> None:
        for pos, star_idx in enumerate(self._sky["twinkle_idx"]):
            star = self._sky["stars"][star_idx]
            phase = self._sky["twinkle_phases"][pos]
            b = 0.5 + 0.5 * math.sin(self._age * 2.2 + phase)
            color = tuple(min(255, int(c * (0.4 + 0.9 * b))) for c in _STAR_COLOR)
            x = int(star["x"])
            if shake_x:
                x = (x + shake_x) % self.ctx.width
            pygame.draw.circle(surface, color, (x, int(star["y"])), star["r"] + 1)

    def _draw_lily_pads(self, surface: pygame.Surface) -> None:
        for pad, sprite in zip(self._lily_pads, self._lily_sprites):
            sway_x = math.sin(self._age * 0.6 + pad["phase"]) * pad["r"] * 0.15
            sway_y = math.cos(self._age * 0.4 + pad["phase"]) * pad["r"] * 0.06
            rect = sprite.get_rect(center=(int(pad["x"] + sway_x), int(pad["y"] + sway_y)))
            surface.blit(sprite, rect)

    def __len__(self) -> int:
        return _TWINKLE_COUNT + (len(self._flies.positions) if self._flies is not None else 0)
