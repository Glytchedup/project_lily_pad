"""The cast list and how they move.

Every letter of the alphabet summons a creature. Four of them (cow, duck, pig,
sheep) are drawn front-on and pop up from the bottom edge like a peekaboo
puppet; the rest are drawn side-on and **travel across the screen** — walking,
hopping, flying or swimming — which reads far more like a living thing than a
sprite that appears and fades.

Sprite drawing lives in :mod:`lilypad.effects.animal_art`; the cast rows live
in :mod:`lilypad.effects.animal_specs`. This module owns who appears for which
key, what they sound like, and how they move.

Performance rules (matching the ``particles.py`` header): sprites are
pre-rendered and cached at spawn time; per-frame work is one blit plus integer
offset math, with a handful of small filled circles for dust. No per-frame
surface allocation, no rotation, no scaling.
"""

from __future__ import annotations

import logging
import math
from functools import cache

import pygame

from . import painted
from .animal_art import (  # noqa: F401 — re-exported for existing importers
    MINI_KINDS,
    POSES,
    animal_names,
    animal_sprite,
    animal_sprite_facing,
    aspect,
    faces_right,
    mini_sprite,
    resolved_mode,
)
from .animal_specs import SPECS
from .base import EffectContext
from .layout import CLASSIC, Layout

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The cast
# ---------------------------------------------------------------------------
#: One creature per letter. The four farm animals are the originals and keep
#: their front-on art; everyone else is side-on and crosses the screen.
ANIMAL_LETTERS: dict[str, str] = {
    "A": "alligator",
    "B": "bear",
    "C": "cow",
    "D": "duck",
    "E": "elephant",
    "F": "fox",
    "G": "giraffe",
    "H": "horse",
    "I": "iguana",
    "J": "jellyfish",
    "K": "koala",
    "L": "lion",
    "M": "monkey",
    "N": "narwhal",
    "O": "owl",
    "P": "pig",
    "Q": "quail",
    "R": "rabbit",
    "S": "sheep",
    "T": "trex",
    "U": "unicorn",
    "V": "velociraptor",
    "W": "whale",
    "X": "xrayfish",
    "Y": "yak",
    "Z": "zebra",
}

#: Every dinosaur in the app. Two have their own letter (T, V); the rest turn
#: up on the function keys, which previously all did the same thing.
DINOSAURS: tuple[str, ...] = (
    "trex", "velociraptor", "stegosaurus", "triceratops",
    "brachiosaurus", "pterodactyl",
)

#: Which synthesized call each creature makes. Kept next to the cast so the
#: audio layer can never drift from the visual one — the audio engine imports
#: this table rather than keeping its own copy.
ANIMAL_VOICES: dict[str, str] = {
    "cow": "moo", "duck": "quack", "pig": "oink", "sheep": "baa",
    "alligator": "growl", "bear": "growl", "koala": "growl",
    "elephant": "trumpet", "brachiosaurus": "trumpet",
    "fox": "screech", "monkey": "screech", "velociraptor": "screech",
    "pterodactyl": "screech",
    "horse": "neigh", "unicorn": "neigh", "zebra": "neigh",
    "lion": "roar", "trex": "roar",
    "owl": "hoot", "quail": "chirp",
    "giraffe": "squeak", "iguana": "squeak", "rabbit": "squeak",
    "narwhal": "whalesong", "whale": "whalesong",
    "jellyfish": "bloop", "xrayfish": "bloop",
    "yak": "moo",
    "stegosaurus": "stomp", "triceratops": "stomp",
}

#: How each creature gets across the screen. Anything unlisted walks.
GAITS: dict[str, str] = {
    "rabbit": "hop", "monkey": "hop", "trex": "hop", "velociraptor": "hop",
    "owl": "fly", "quail": "fly", "pterodactyl": "fly", "jellyfish": "fly",
    "whale": "swim", "narwhal": "swim", "xrayfish": "swim",
}

#: Creatures drawn front-on, which pop up instead of crossing.
PEEKABOO_CAST: frozenset[str] = frozenset({"cow", "duck", "pig", "sheep"})

# Frame schedules for painted art (rates are per second of the effect's own
# clock). A walker alternates idle/step on every bob trough, so this is the
# footfall rate (the bob is |sin| at 1.3 Hz, two troughs per cycle). Flyers,
# swimmers and floaters run a full idle-then-step cycle at their rate.
WALK_STEP_HZ = 2.6
FLY_FLAP_HZ = 2.0
SWIM_SWISH_HZ = 0.8
FLOAT_PULSE_HZ = 1.0
#: A hopper shows its stretched frame while sin(pi * phase) is above this.
HOP_STEP_ARC = 0.25


def _cycle_pose(age: float, hz: float) -> str:
    """idle for the first half of each cycle, step for the second."""
    return "step" if (age * hz) % 1.0 >= 0.5 else "idle"


# Startup selects the scene geometry before prebuilding the cast. Direct
# callers retain the classic layout and uncapped sizes until then.
_layout = CLASSIC
_max_sprite_width = 0.0

# Dust fades toward the pond's near-black rather than using per-frame alpha
# surfaces. Kept as a literal (not imported from ``engine``) because engine
# imports this module — and being a few units off on a puff nobody can name
# is worth more than a circular import.
DUST_FADE_TO = (6, 8, 12)
DUST_COLOR = (188, 176, 150)


def animal_for_letter(letter: str) -> str | None:
    """The creature summoned by ``letter``, or None. Case-insensitive."""
    return ANIMAL_LETTERS.get(letter.upper()[:1])


def voice_for(name: str) -> str | None:
    """The audio cue name for a creature, or None if it is a quiet one."""
    return ANIMAL_VOICES.get(name)


def _sprite_height(name: str, size: tuple[int, int], gait: str) -> int:
    if gait == "peekaboo":
        fraction = 0.40
    elif gait == "swim":
        fraction = _layout.swim_height
    else:
        fraction = AnimalCrossing._SIZE.get(gait, 0.34)
    height = max(48, int(size[1] * fraction))
    if _max_sprite_width:
        height = max(1, min(height, int(_max_sprite_width * size[0] / aspect(name))))
    return height


@cache
def _fit_size(sprite: pygame.Surface, width: int, height: int) -> pygame.Surface:
    return pygame.transform.smoothscale(sprite, (width, height))


def _scene_sprite(name: str, height: int, pose: str, going_left: bool,
                  screen_width: int) -> pygame.Surface:
    sprite = animal_sprite_facing(name, height, pose, going_left)
    if _max_sprite_width:
        limit = max(1, int(_max_sprite_width * screen_width))
        # Traced outlines can round wider than their measured aspect. A tiny
        # cap can also request less than the procedural builders' safe 24 px.
        w, h = sprite.get_size()
        if w > limit or h != height:
            width = min(limit, max(1, round(w * height / h)))
            return _fit_size(sprite, width, height)
    return sprite


# ---------------------------------------------------------------------------
# Shared bits
# ---------------------------------------------------------------------------
def _ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _ease_in(t: float) -> float:
    return t ** 3


class _Dust:
    """A few puffs kicked up on landing.

    Deliberately owned by the animal rather than pushed into the engine's
    effect list: they are part of the animal's performance, they die with it,
    and keeping them here means a crossing is still exactly one Effect.
    """

    __slots__ = ("puffs",)
    LIFE = 0.45

    def __init__(self) -> None:
        # x, y, vx, vy, radius, age
        self.puffs: list[list[float]] = []

    def kick(self, x: float, y: float, size: float, rng, count: int = 5) -> None:
        for _ in range(count):
            self.puffs.append([
                x + rng.uniform(-size * 0.35, size * 0.35), y,
                rng.uniform(-size * 1.6, size * 1.6), rng.uniform(-size * 1.1, -size * 0.3),
                rng.uniform(size * 0.10, size * 0.20), 0.0,
            ])

    def update(self, dt: float) -> None:
        for p in self.puffs:
            p[5] += dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 220.0 * dt          # settle back down
        self.puffs = [p for p in self.puffs if p[5] < self.LIFE]

    def draw(self, surface: pygame.Surface) -> None:
        for x, y, _vx, _vy, r, age in self.puffs:
            fade = age / self.LIFE
            color = (int(DUST_COLOR[0] + (DUST_FADE_TO[0] - DUST_COLOR[0]) * fade),
                     int(DUST_COLOR[1] + (DUST_FADE_TO[1] - DUST_COLOR[1]) * fade),
                     int(DUST_COLOR[2] + (DUST_FADE_TO[2] - DUST_COLOR[2]) * fade))
            pygame.draw.circle(surface, color, (int(x), int(y)),
                               max(1, int(r * (1.0 + fade))))

    def __len__(self) -> int:
        return len(self.puffs)


# ---------------------------------------------------------------------------
# Peekaboo — the four front-on farm animals
# ---------------------------------------------------------------------------
class PeekabooAnimal:
    """A front-on animal slides up from below, bounces, and slides away.

    Timeline: 0.5 s ease-out rise → 2.2 s hold → 0.5 s ease-in drop. During
    the hold it blinks twice and now takes **two little jumps**, landing with
    a squashed pose and a puff of dust — the squash is what sells the weight,
    and it costs nothing at runtime because the squashed sprite is generated
    once and cached like every other pose.

    Motion choice: sinusoidal bob + sway rather than ``pygame.transform``.
    At ~40 % of a 1080p screen the sprite is ~430 px tall; rotating or scaling
    it every frame allocates and fills a fresh ~800 KB surface 60 times a
    second, and because the angle changes continuously none of it can be
    cached — real work on the Pi's software blit path for a wobble a
    2-year-old reads the same either way.
    """

    RISE_TIME = 0.5
    HOLD_TIME = 2.2
    FALL_TIME = 0.5
    # Hold-relative jump start times; each lasts _JUMP_TIME.
    _JUMPS = (0.28, 1.10)
    _JUMP_TIME = 0.42
    # Hold-relative windows in which the eyes are shut ("blinks twice").
    # Deliberately placed *between* the jumps: a jump owns the pose while it
    # runs, so a blink window overlapping one would simply never be seen.
    _BLINKS = ((0.80, 0.96), (1.62, 1.80))

    def __init__(self, ctx: EffectContext, name: str) -> None:
        self.name = name
        self.age = 0.0
        self.total = self.RISE_TIME + self.HOLD_TIME + self.FALL_TIME
        self.pose = "idle"
        height = _sprite_height(name, ctx.size, "peekaboo")
        self.height = height
        self._rng = ctx.rng
        self._dust = _Dust()
        self._landed: set[int] = set()
        # Pre-render every pose now so nothing costs a frame mid-animation.
        self._sprites = {p: _scene_sprite(name, height, p, False, ctx.width) for p in POSES}
        self._sprite_w = self._sprites["idle"].get_width()
        # Middle 70 % of the width, sprite kept fully on-screen.
        half = self._sprite_w * 0.5
        low = min(max(ctx.width * 0.15, half), ctx.width - half)
        high = max(min(ctx.width * 0.85, ctx.width - half), half)
        self.x = ctx.rng.uniform(min(low, high), max(low, high))
        # Off-screen: sprite top at the bottom edge. Resting: mostly visible,
        # feet just past the edge so it reads as peeking over a fence.
        self._y_off = float(ctx.height)
        self._y_rest = ctx.height - height * 0.90
        self.y = self._y_off
        self.jump = 0.0

    # -- animation -------------------------------------------------------
    def _hold_pose(self, hold_t: float) -> str:
        for i, start in enumerate(self._JUMPS):
            since = hold_t - start
            if 0.0 <= since < self._JUMP_TIME:
                # Squash on the way down, in the last fifth of the arc.
                return "squash" if since > self._JUMP_TIME * 0.82 else "idle"
        for start, stop in self._BLINKS:
            if start <= hold_t < stop:
                return "blink"
        return "idle"

    def _jump_offset(self, hold_t: float) -> float:
        for i, start in enumerate(self._JUMPS):
            since = hold_t - start
            if 0.0 <= since < self._JUMP_TIME:
                arc = math.sin(math.pi * (since / self._JUMP_TIME))
                return arc * self.height * 0.22
            if since >= self._JUMP_TIME and i not in self._landed:
                self._landed.add(i)
                self._dust.kick(self.x, self.y + self.height * 0.04,
                                self.height * 0.30, self._rng)
        return 0.0

    def update(self, dt: float) -> bool:
        self.age += dt
        t = self.age
        self._dust.update(dt)
        if t < self.RISE_TIME:
            e = _ease_out(t / self.RISE_TIME)
            self.pose = "idle"
            self.jump = 0.0
        elif t < self.RISE_TIME + self.HOLD_TIME:
            e = 1.0
            hold_t = t - self.RISE_TIME
            self.pose = self._hold_pose(hold_t)
            self.jump = self._jump_offset(hold_t)
        else:
            fall = min(1.0, (t - self.RISE_TIME - self.HOLD_TIME) / self.FALL_TIME)
            e = 1.0 - _ease_in(fall)
            self.pose = "idle"
            self.jump = 0.0
        self.y = self._y_off + (self._y_rest - self._y_off) * e
        return self.age < self.total

    def draw(self, surface: pygame.Surface) -> None:
        self._dust.draw(surface)
        sprite = self._sprites.get(self.pose, self._sprites["idle"])
        bob = math.sin(self.age * math.tau * 1.6) * self.height * 0.022
        sway = math.sin(self.age * math.tau * 0.85) * self.height * 0.018
        rect = sprite.get_rect(midtop=(int(self.x + sway),
                                       int(self.y + bob - self.jump)))
        surface.blit(sprite, rect)

    def __len__(self) -> int:  # flat cost against the engine's particle budget
        return 25 + len(self._dust)


# ---------------------------------------------------------------------------
# Crossing — everybody else
# ---------------------------------------------------------------------------
class AnimalCrossing:
    """A side-on animal travels all the way across the screen and leaves.

    The gait decides the path:

    ``walk``  feet on the ground, gentle two-beat body bob
    ``hop``   a chain of parabolic arcs; every landing squashes and kicks dust
    ``fly``   a slow sine through the upper half of the screen
    ``swim``  a slower, shallower sine through the lower middle

    Direction is random, and the sprite is mirrored to face the way it is
    going (mirrors are cached, so this costs one extra surface per pose the
    first time an animal runs at a given size).
    """

    DURATION = 3.4
    MAX_PAUSE = 1.5
    GREET_DURATION = 0.6
    HOP_PERIOD = 0.62
    #: Wave amplitude as a fraction of sprite height, for the two air gaits.
    FLY_WAVE = 0.40
    SWIM_WAVE = 0.32
    _BLINKS = ((0.9, 1.05), (2.1, 2.25))

    #: Sprite height as a fraction of the screen, per gait. Flyers and
    #: swimmers read smaller because they have the whole sky/water to move in.
    _SIZE = {"walk": 0.34, "hop": 0.32, "fly": 0.24, "swim": 0.28}

    def __init__(self, ctx: EffectContext, name: str,
                 gait: str | None = None) -> None:
        self.name = name
        self.gait = gait or GAITS.get(name, "walk")
        self.age = 0.0
        self.total = self.DURATION
        self._travel_age = 0.0
        self._pause_left = 0.0
        self._greet_start = -self.GREET_DURATION
        self.pose = "idle"
        self._rng = ctx.rng
        self._dust = _Dust()
        self._hops_landed = 0
        spec = SPECS.get(name)
        self._floater = spec is not None and spec.build == "floater"

        height = _sprite_height(name, ctx.size, self.gait)
        self.height = height
        self.going_left = ctx.rng.random() < 0.5
        self._sprites = {
            p: _scene_sprite(name, height, p, self.going_left, ctx.width)
            for p in POSES
        }
        self._sprite_w = self._sprites["idle"].get_width()

        # Keep the landmark with the frames it was measured on. A later art
        # selection applies to new crossings, while these sprites stay live.
        self.back_at = None
        if resolved_mode(name) == "painted" and painted.has(name):
            self.back_at = painted.back_at(name)

        # Start fully off one edge, end fully off the other.
        pad = self._sprite_w * 0.6 + 8
        self._x_from = ctx.width + pad if self.going_left else -pad
        self._x_to = -pad if self.going_left else ctx.width + pad
        self.x = self._x_from

        # Ground line: on the bank, a little above the very bottom.
        self._ground = ctx.height * _layout.ground
        # Flyers and swimmers are centred on their path, so the band they may
        # start in has to leave room for half a sprite *plus* the full wave
        # amplitude — otherwise an owl that happens to start high sails off
        # the top of the screen mid-flap.
        self._air_y = self._band(ctx, self.FLY_WAVE, *_layout.fly_band)
        self._swim_y = self._band(ctx, self.SWIM_WAVE, *_layout.swim_band)
        self._wave = ctx.rng.uniform(0.0, math.tau)
        self.y = self._ground

    def _band(self, ctx: EffectContext, wave: float,
              lo_frac: float, hi_frac: float) -> float:
        half = self.height * 0.5
        margin = half + self.height * wave + 2.0
        lo = max(margin, ctx.height * lo_frac)
        hi = min(ctx.height - margin, ctx.height * hi_frac)
        if hi <= lo:                     # screen too short for the whole band
            return min(max(ctx.height * 0.5, half), ctx.height - half)
        return ctx.rng.uniform(lo, hi)

    # -- animation -------------------------------------------------------
    def _blinking(self) -> bool:
        return any(a <= self.age < b for a, b in self._BLINKS)

    @classmethod
    def pose_for(cls, gait: str, age: float, floater: bool = False) -> str:
        """The frame this gait shows at ``age`` seconds into the crossing.

        A pure function of the effect's own clock: it draws nothing from the
        shared rng, so the schedule can never perturb anyone else's dice. The
        poses are only labels. With traced or drawn art ``step`` aliases
        ``idle`` at the sprite level, so those routes look exactly as before.

        Priority: a hop's landing squash, then a blink, then the gait's own
        stepping frame. (A blink during a hop's landing would otherwise be a
        visible change to the legacy look.)
        """
        blinking = any(a <= age < b for a, b in cls._BLINKS)
        if gait == "hop":
            phase = (age % cls.HOP_PERIOD) / cls.HOP_PERIOD
            if phase > 0.90 or phase < 0.06:
                return "squash"
            if blinking:
                return "blink"
            return "step" if math.sin(math.pi * phase) > HOP_STEP_ARC else "idle"
        if blinking:
            return "blink"
        if gait == "walk":
            # One footfall per bob trough; the bob is |sin| at 1.3 Hz.
            return "step" if int(age * WALK_STEP_HZ) % 2 else "idle"
        if gait == "swim":
            return _cycle_pose(age, SWIM_SWISH_HZ)
        if floater:
            return _cycle_pose(age, FLOAT_PULSE_HZ)
        if gait == "fly":
            return _cycle_pose(age, FLY_FLAP_HZ)
        return "idle"

    def _vertical(self) -> tuple[float, str]:
        """Return (y of the sprite's anchor, pose) for the current age."""
        pose = self.pose_for(self.gait, self.age, self._floater)
        if self.gait == "hop":
            phase = (self.age % self.HOP_PERIOD) / self.HOP_PERIOD
            lift = math.sin(math.pi * phase) * self.height * 0.42
            landed = int(self.age / self.HOP_PERIOD)
            if landed > self._hops_landed:
                self._hops_landed = landed
                self._dust.kick(self.x, self._ground, self.height * 0.32,
                                self._rng, count=6)
            return self._ground - lift, pose
        if self.gait == "fly":
            y = self._air_y + math.sin(self.age * math.tau * 0.55 + self._wave) \
                * self.height * self.FLY_WAVE
            return y, pose
        if self.gait == "swim":
            y = self._swim_y + math.sin(self.age * math.tau * 0.42 + self._wave) \
                * self.height * self.SWIM_WAVE
            return y, pose
        # walk: a two-beat bob, feet staying on the ground line
        bob = abs(math.sin(self.age * math.tau * 1.3)) * self.height * 0.035
        return self._ground - bob, pose

    @property
    def airborne(self) -> bool:
        """True for gaits whose sprite is centred on y rather than standing
        on it."""
        return self.gait in ("fly", "swim")

    @property
    def width(self) -> int:
        return self._sprite_w

    @property
    def speed(self) -> float:
        """Horizontal travel speed in screen pixels per second while moving."""
        return abs(self._x_to - self._x_from) / self.DURATION

    def pause(self, seconds: float) -> None:
        """Hold x, sharing one extension budget across the whole crossing."""
        if self.age < self.total:
            extra = min(max(0.0, seconds - self._pause_left),
                        self.DURATION + self.MAX_PAUSE - self.total)
            self._pause_left += extra
            self.total += extra

    def greet_bounce(self) -> None:
        self._greet_start = self.age

    def update(self, dt: float) -> bool:
        self.age += dt
        self._dust.update(dt)
        paused = min(dt, self._pause_left)
        self._pause_left -= paused
        self._travel_age += dt - paused
        t = min(1.0, self._travel_age / self.DURATION)
        self.x = self._x_from + (self._x_to - self._x_from) * t
        self.y, self.pose = self._vertical()
        elapsed = self.age - self._greet_start
        if elapsed < self.GREET_DURATION:
            self.y -= self.height * 0.14 * abs(math.sin(math.tau * elapsed / self.GREET_DURATION))
        return self.age < self.total

    def _sprite_rect(self, sprite: pygame.Surface) -> pygame.Rect:
        point = (int(self.x), int(self.y))
        return sprite.get_rect(center=point) if self.airborne else sprite.get_rect(midbottom=point)

    def back_anchor(self, *, ground_margin: int | None = None) -> tuple[int, int]:
        """Pixel on the current sprite. Pass the engine's margin for registered ground art."""
        rect = self._sprite_rect(self._sprites[self.pose])
        if ground_margin is not None and not self.airborne:
            rect.bottom = round(self.y) + ground_margin
        if self.back_at is None:
            return rect.midtop
        fx, fy = self.back_at
        col = min(rect.w - 1, int(fx * rect.w))
        if self.going_left and faces_right(self.name):
            col = rect.w - 1 - col
        return rect.left + col, rect.top + min(rect.h - 1, round(fy * rect.h))

    def draw(self, surface: pygame.Surface) -> None:
        self._dust.draw(surface)
        sprite = self._sprites.get(self.pose, self._sprites["idle"])
        surface.blit(sprite, self._sprite_rect(sprite))

    def __len__(self) -> int:
        return 25 + len(self._dust)


def animal_effect(ctx: EffectContext, name: str):
    """The right performance for ``name``.

    Front-on animals pop up (mirroring or walking a front view sideways looks
    broken); side-on animals cross the screen.
    """
    if name in PEEKABOO_CAST:
        return PeekabooAnimal(ctx, name)
    return AnimalCrossing(ctx, name)


def random_dinosaur(ctx: EffectContext) -> str:
    return ctx.rng.choice(DINOSAURS)


def prewarm(screen_height: int, *, screen_width: int = 0, max_sprite_width: float = 0,
            layout: Layout = CLASSIC) -> int:
    """Select the scene geometry and warm painted/traced poses at their spawn size."""
    global _layout, _max_sprite_width
    if max_sprite_width and screen_width <= 0:
        raise ValueError("a positive screen_width is required for capped sprites")
    _layout, _max_sprite_width = layout, max_sprite_width
    _fit_size.cache_clear()
    counts = {"painted": 0, "traced": 0, "drawn": 0}
    built = 0
    for name in animal_names():
        mode = resolved_mode(name)
        counts[mode] += 1
        if mode == "drawn":
            continue
        side = faces_right(name)
        gait = GAITS.get(name, "walk") if side else "peekaboo"
        height = _sprite_height(name, (screen_width, screen_height), gait)
        poses = POSES if mode == "painted" and painted.has_step(name) else ("idle", "blink", "squash")
        for pose in poses:
            for going_left in ((False, True) if side else (False,)):
                try:
                    _scene_sprite(name, height, pose, going_left, screen_width)
                except Exception:                    # noqa: BLE001
                    log.exception("could not prebuild %s/%s", name, pose)
                else:
                    built += 1
    log.info("animal art: painted (%d), traced (%d), drawn (%d)",
             counts["painted"], counts["traced"], counts["drawn"])
    return built
