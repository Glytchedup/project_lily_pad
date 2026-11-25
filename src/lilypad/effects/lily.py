"""Lily, the child in the pond: a calm background companion who changes spots.

She sits at one of six named places around the painted pond (far shore left and
right, the bank beside Pip's pad, a big lily pad, tummy-down on the bank, and
under the moon pointing up). Every ``move_seconds`` of awake time she fades out
in a soft sparkle and fades in at a *different* spot. She blinks while sitting,
waves when an animal starts crossing, and cheers (bobbing on the beat) during a
party or any other celebration.

Everything is cached at load: every pose is prescaled once per spot, mirrored
copies included, so a frame costs blits and integer offsets only. The only
random stream is the one this effect owns, so enabling or disabling her never
shifts ``ctx.rng``. ``load_lily`` returns None for the drawn world, a missing or
malformed ``[lily]`` manifest entry, or when too few spots clear the safety
rules, and a game with no Lily draws exactly what it did before her.

Spots are fractions of the screen taken from the pond ``Layout`` and are kept
clear of the centre stage (where giant letters and crossing animals play) and of
the band Pip's pad can drift through.
"""

from __future__ import annotations

import logging
import math
import random
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pygame

from . import assets, critter
from .layout import Layout

log = logging.getLogger(__name__)

#: Poses the manifest must supply. tummy and point face right, the rest the viewer.
POSES = ("sit", "sit_blink", "wave", "tummy", "point", "cheer")
_MIRRORED = frozenset(("tummy", "point"))

#: Fade out, then fade in, each this long (the sparkle poof runs alongside).
FADE_SECONDS = 0.4
WAVE_SECONDS = 1.5
BLINK_EVERY = (3.0, 6.0)   # seconds from one blink's start to the next
BLINK_SECONDS = 0.16
PARTY_BOB_HZ = 2.0         # bobs per second when no beat clock is available
DEFAULT_MOVE_SECONDS = 75.0
_DEFAULT_SEED = 0x11E
#: The central stage, as screen-width fractions. Lily never stands inside it.
STAGE_X = (0.30, 0.70)
_SPARKLES = 8
_MAX_CARRY = 0.1


@dataclass(frozen=True)
class _SpotDef:
    name: str
    x: float          # centre, fraction of screen width
    feet: float       # baseline, fraction of screen height
    size: float       # standing height, fraction of screen height
    base: str         # resting pose: sit | tummy | point
    pad: bool = False  # draw a big lily pad underneath


def _spot_defs(layout: Layout) -> list[_SpotDef]:
    """Named spots derived from the pond bands (assumes far_shore and water exist)."""
    far = layout.ground - 0.008
    return [
        # Three each side of the stage. The painted moon sits near x 0.30, y 0.14 in
        # every mood, so she stands just left of it on the far shore and points at it.
        _SpotDef("far_shore_left", 0.044, far, 0.22, "sit"),
        _SpotDef("bank_near_pip", 0.137, layout.ground, 0.25, "sit"),
        _SpotDef("under_the_moon", 0.241, far, 0.26, "point"),
        _SpotDef("lily_pad", 0.762, layout.ground + 0.09, 0.22, "sit", pad=True),
        _SpotDef("far_shore_right", 0.957, far, 0.22, "sit"),
        _SpotDef("tummy_on_bank", 0.873, layout.ground, 0.22, "tummy"),
    ]


@dataclass
class _Spot:
    name: str
    cx: int
    feet: int
    size_px: int
    base: str
    poses: dict[str, tuple[pygame.Surface, tuple[int, int]]]   # surface, top-left
    pad: tuple[pygame.Surface, tuple[int, int]] | None
    rect: pygame.Rect                                         # union of every pose


def pip_pad_band_top(size: tuple[int, int]) -> int:
    """Top edge (px) of the strip Pip's drifting pad can occupy across the screen."""
    h = size[1]
    try:
        r = max(30, int(h * 0.06))
        sprite_h = critter.lily_pad_sprite(r).get_height()
        surface_y = h - critter.pad_reach(r)
        top = (surface_y + sprite_h * critter._PAD_SINK - sprite_h / 2
               - r * critter._PAD_BOB)
    except pygame.error:
        top = h * 0.90
    return math.floor(top) - 2


def _read_row(root: Path | None) -> tuple[dict, Path] | None:
    directory = (root if root is not None else assets.asset_root()) / "painted"
    try:
        with (directory / "manifest.toml").open("rb") as stream:
            manifest = tomllib.load(stream)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("Ignoring painted manifest for Lily in %s: %s", directory, exc)
        return None
    if type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        log.warning("Ignoring painted manifest for Lily: expected schema = 1")
        return None
    row = manifest.get("lily")
    if row is None:
        return None
    if not isinstance(row, dict):
        log.warning("Ignoring Lily: [lily] must be a table")
        return None
    return row, directory


def _rgba(frame: pygame.Surface) -> pygame.Surface:
    if frame.get_bitsize() == 32 and frame.get_masks()[3]:
        return frame
    out = pygame.Surface(frame.get_size(), pygame.SRCALPHA)
    out.blit(frame, (0, 0))
    return out


def _decode(row: dict, directory: Path) -> tuple[
        dict[str, pygame.Surface], int, tuple[float, float], dict[str, float]]:
    native = row["native_height"]
    if type(native) is not int or native <= 0:
        raise ValueError("invalid native_height")
    anchor = row["anchor"]
    if (not isinstance(anchor, list) or len(anchor) != 2
            or not all(type(v) in (int, float) and 0 <= v <= 1 for v in anchor)):
        raise ValueError("invalid anchor")
    files = row["frames"]
    frames = {}
    for pose in POSES:
        relative = Path(files[pose])
        if (relative.anchor or ".." in relative.parts
                or relative.suffix.lower() not in (".png", ".webp")):
            raise ValueError(f"invalid frame path {files[pose]!r}")
        frames[pose] = _rgba(assets.load_image(directory / relative))
        if frames[pose].get_width() < 1 or frames[pose].get_height() < 1:
            raise ValueError(f"empty frame {pose}")
    heights = row.get("heights", {})
    if not isinstance(heights, dict):
        raise TypeError("heights must be a table")
    for pose, fraction in heights.items():
        if type(fraction) not in (int, float) or not 0 < fraction <= 1.5:
            raise ValueError(f"invalid height for {pose}")
    return frames, native, (float(anchor[0]), float(anchor[1])), {
        pose: float(f) for pose, f in heights.items()}


def _pad_sprite(width: int, height: int) -> pygame.Surface:
    sprite = pygame.Surface((width, height), pygame.SRCALPHA)
    rect = sprite.get_rect()
    pygame.draw.ellipse(sprite, (18, 62, 40, 255), rect)
    pygame.draw.ellipse(sprite, (34, 96, 58, 255), rect, max(1, width // 14))
    pygame.draw.polygon(sprite, (0, 0, 0, 0), [
        rect.center, (rect.right + 2, rect.centery - max(2, height // 6)),
        (rect.right + 2, rect.centery + max(2, height // 6))])
    return sprite


def _dots(radius: int) -> tuple[pygame.Surface, ...]:
    """Three small round sparkles in warm white, cached for the poof."""
    out = []
    for scale, colour in ((1.0, (255, 250, 220)), (0.7, (255, 232, 170)),
                          (0.5, (200, 240, 255))):
        r = max(2, round(radius * scale))
        dot = pygame.Surface((2 * r + 1, 2 * r + 1), pygame.SRCALPHA)
        pygame.draw.circle(dot, (*colour, 90), (r, r), r)
        pygame.draw.circle(dot, (*colour, 255), (r, r), max(1, r // 2))
        out.append(dot)
    return tuple(out)


def _build_spot(defn: _SpotDef, size: tuple[int, int], frames: dict[str, pygame.Surface],
                native: int, anchor: tuple[float, float], heights: dict[str, float]) -> _Spot:
    w, h = size
    size_px = max(8, round(defn.size * h))
    scale = size_px / native
    cx, feet = round(defn.x * w), round(defn.feet * h)
    mirror = defn.x > 0.5
    wanted = {"sit": ("sit", "sit_blink", "wave", "cheer"),
              "tummy": ("tummy", "cheer"), "point": ("point", "cheer")}[defn.base]
    poses = {}
    rect = pygame.Rect(cx, feet, 0, 0)
    for pose in wanted:
        art = frames[pose]
        # `heights` is the pose height as a fraction of her standing height, so the
        # painted canvases may be any size and she still stays one size across poses.
        if pose in heights:
            tall = max(1, round(size_px * heights[pose]))
            target = (max(1, round(art.get_width() * tall / art.get_height())), tall)
        else:
            target = (max(1, round(art.get_width() * scale)),
                      max(1, round(art.get_height() * scale)))
        surface = pygame.transform.smoothscale(art, target)
        ax = anchor[0]
        if mirror and pose in _MIRRORED:
            surface = pygame.transform.flip(surface, True, False)
            ax = 1.0 - anchor[0]
        topleft = (round(cx - ax * target[0]), feet - round(anchor[1] * target[1]))
        poses[pose] = (surface, topleft)
        rect.union_ip(pygame.Rect(topleft, target))
    pad = None
    if defn.pad:
        pad_w, pad_h = round(size_px * 0.95), max(4, round(size_px * 0.26))
        pad_at = (cx - pad_w // 2, feet - round(pad_h * 0.65))
        pad = (_pad_sprite(pad_w, pad_h), pad_at)
        rect.union_ip(pygame.Rect(pad_at, (pad_w, pad_h)))
    return _Spot(defn.name, cx, feet, size_px, defn.base, poses, pad, rect)


def load_lily(root: Path | None, screen_size: tuple[int, int], layout: Layout, *,
              move_seconds: float = DEFAULT_MOVE_SECONDS,
              seed: int | None = None) -> Lily | None:
    """Build Lily from the ``[lily]`` manifest entry, or None to draw nothing.

    ``root`` is the asset root (the directory holding ``painted/``); None means
    the package default. Never touches ``ctx.rng``; ``seed`` seeds her own stream.
    """
    if layout.far_shore is None or layout.water is None:
        return None            # the drawn classic world has no shore to stand on
    found = _read_row(root)
    if found is None:
        return None
    row, directory = found
    try:
        frames, native, anchor, heights = _decode(row, directory)
    except (KeyError, TypeError, OSError, ValueError, pygame.error,
            NotImplementedError) as exc:
        log.warning("Ignoring painted Lily: %s", exc)
        return None

    w, h = screen_size
    pad_top = pip_pad_band_top(screen_size)
    stage = pygame.Rect(round(STAGE_X[0] * w), 0, round((STAGE_X[1] - STAGE_X[0]) * w), h)
    bob = max(2, round(0.012 * h))
    spots = []
    for defn in _spot_defs(layout):
        spot = _build_spot(defn, screen_size, frames, native, anchor, heights)
        reach = spot.rect.inflate(0, 2 * bob)
        if (not pygame.Rect(0, 0, w, h).contains(reach) or reach.colliderect(stage)
                or reach.bottom > pad_top):
            log.info("Lily spot %s does not fit this screen; dropped", spot.name)
            continue
        spots.append(spot)
    if len(spots) < 2:
        log.info("Lily needs two spots to move between; not drawing her")
        return None
    return Lily(spots, screen_size, move_seconds, _DEFAULT_SEED if seed is None else seed)


class Lily:
    """Persistent background character; the engine owns one and never ends her."""

    def __init__(self, spots: list[_Spot], size: tuple[int, int],
                 move_seconds: float = DEFAULT_MOVE_SECONDS, seed: int = _DEFAULT_SEED) -> None:
        if len(spots) < 2:
            raise ValueError("Lily needs at least two spots")
        self.spots = spots
        self.size = size
        self.move_seconds = max(1.0, float(move_seconds))
        self._rng = random.Random(seed)
        self._bob_px = max(2, round(0.012 * size[1]))
        self._dots = _dots(max(2, round(size[1] * 0.006)))

        self.index = self._rng.randrange(len(spots))
        self.phase = "in"          # in | hold | out
        self.phase_time = 0.0
        self.move_time = 0.0       # awake seconds since arriving
        self.age = 0.0
        self.asleep = False
        self.party = False
        self._beat = None
        self.wave_left = 0.0
        self.cheer_left = 0.0
        self.blink_in = self._rng.uniform(*BLINK_EVERY)
        self.blink_left = 0.0
        self._sparkle_angle = self._rng.uniform(0, math.tau)

    # -- state ---------------------------------------------------------------

    @property
    def spot(self) -> _Spot:
        return self.spots[self.index]

    @property
    def spot_name(self) -> str:
        return self.spot.name

    @property
    def cheering(self) -> bool:
        return self.party or self.cheer_left > 0

    @property
    def pose(self) -> str:
        spot = self.spot
        if self.cheering:
            return "cheer"
        if spot.base == "sit":
            if self.wave_left > 0:
                return "wave"
            return "sit_blink" if self.blink_left > 0 else "sit"
        return spot.base

    @property
    def alpha(self) -> int:
        if self.phase == "in":
            return min(255, int(255 * self.phase_time / FADE_SECONDS))
        if self.phase == "out":
            return max(0, int(255 * (1 - self.phase_time / FADE_SECONDS)))
        return 255

    @property
    def spot_rects(self) -> dict[str, pygame.Rect]:
        """Every pose's footprint per spot, padded by the bob; for layout checks."""
        return {s.name: s.rect.inflate(0, 2 * self._bob_px) for s in self.spots}

    # -- events --------------------------------------------------------------

    def on_animal_start(self) -> None:
        """An animal began crossing: wave for a moment if she is sitting."""
        if self.spot.base == "sit" and not self.asleep:
            self.wave_left = WAVE_SECONDS

    def set_party(self, active: bool, beat_clock=None) -> None:
        """Cheer for the length of a party, bobbing on ``beat_clock`` if given."""
        self.party = bool(active)
        self._beat = beat_clock if active else None

    def cheer(self, seconds: float = 2.0) -> None:
        """Cheer for a while (milestones, the Grand Parade)."""
        if not self.asleep:
            self.cheer_left = max(self.cheer_left, float(seconds))

    def sleep(self) -> None:
        self.asleep = True

    def wake(self) -> None:
        if self.asleep:
            self.asleep = False
            self.phase, self.phase_time = "in", 0.0

    # -- per frame -----------------------------------------------------------

    def update(self, dt: float, events=()) -> bool:
        if events and "animal_start" in events:
            self.on_animal_start()
        if self.asleep or not dt > 0 or not math.isfinite(dt):
            return True
        self.age += dt
        self.wave_left = max(0.0, self.wave_left - dt)
        self.cheer_left = max(0.0, self.cheer_left - dt)
        self.blink_left = max(0.0, self.blink_left - dt)
        self.blink_in -= dt
        if self.blink_in <= 0:
            self.blink_left = BLINK_SECONDS
            self.blink_in = self._rng.uniform(*BLINK_EVERY)

        if self.phase == "hold":
            self.move_time += dt
            if self.move_time >= self.move_seconds:
                self.phase = "out"
                self.phase_time = min(self.move_time - self.move_seconds, _MAX_CARRY)
        else:
            self.phase_time += dt
        if self.phase != "hold" and self.phase_time >= FADE_SECONDS:
            # A frame hitch carries a little into the next phase, never a whole move.
            carry = min(self.phase_time - FADE_SECONDS, _MAX_CARRY)
            if self.phase == "in":
                self.phase = "hold"
                self.move_time += carry     # keeps the wait when she wakes mid-way
            else:
                self._arrive()
                self.phase_time = carry
        return True

    def _arrive(self) -> None:
        others = [i for i in range(len(self.spots)) if i != self.index]
        self.index = self._rng.choice(others)
        self.phase = "in"
        self.move_time = 0.0
        self.wave_left = 0.0
        self.blink_left = 0.0
        self.blink_in = self._rng.uniform(*BLINK_EVERY)
        self._sparkle_angle = self._rng.uniform(0, math.tau)

    def _bob(self) -> int:
        """Vertical lift in whole pixels: on the beat if a clock is attached."""
        if self._beat is not None:
            if getattr(self._beat, "beat_index", -1) < 0:
                return 0
            phase = min(1.0, max(0.0, self._beat.beat_phase))
            return -round(self._bob_px * (1.0 - phase) ** 2)
        return -round(self._bob_px * (0.5 - 0.5 * math.cos(math.tau * PARTY_BOB_HZ * self.age)))

    def draw(self, surface: pygame.Surface) -> None:
        if self.asleep:
            return
        spot = self.spot
        alpha = self.alpha
        if alpha > 0:
            pose = self.pose
            lift = self._bob() if pose == "cheer" else 0
            # The pad stays put under her; only Lily herself bobs.
            parts = [(spot.pad, 0)] if spot.pad is not None else []
            parts.append((spot.poses[pose], lift))
            for (art, (x, y)), dy in parts:
                if alpha < 255:
                    art.set_alpha(alpha)
                surface.blit(art, (x, y + dy))
                if alpha < 255:
                    art.set_alpha(255)
        if self.phase != "hold":
            self._draw_poof(surface, spot)

    def _draw_poof(self, surface: pygame.Surface, spot: _Spot) -> None:
        u = min(1.0, self.phase_time / FADE_SECONDS)
        reach = spot.size_px * (0.15 + 0.35 * u)
        cx, cy = spot.cx, spot.feet - spot.size_px * 0.45
        level = int(230 * (1.0 - u))
        if level <= 0:
            return
        for k in range(_SPARKLES):
            angle = self._sparkle_angle + k * math.tau / _SPARKLES
            dot = self._dots[k % len(self._dots)]
            dot.set_alpha(level)
            surface.blit(dot, dot.get_rect(center=(round(cx + reach * math.cos(angle)),
                                                   round(cy + reach * math.sin(angle) * 1.2))))
            dot.set_alpha(255)
