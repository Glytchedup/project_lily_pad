"""Giant letters (and glyph text like number digits) with pop-in animation.

Upgraded per VISUAL_REVIEW.md #6: thick contrasting outline, occasional
rainbow-gradient fill, a gentle bob/sway wobble during the hold phase, and
googly eyes that turn the glyph into a creature. Painted glyphs and their eye
poses are sized at spawn. The original font pop uses an integer scale.
"""

from __future__ import annotations

import colorsys
import logging
import math
import random
import tomllib
from bisect import bisect_left
from functools import cache, lru_cache
from pathlib import Path
from string import ascii_uppercase

import pygame

from . import assets
from .base import EffectContext, random_bright
from .eyes import draw_eye, draw_original_eye, prepare_eye
from .eyes import set_eye_art as set_eye_art  # App and capture configure both glyph art kits here.

_font_cache: dict[int, pygame.font.Font] = {}
_painted = False
_stickers: dict[str, pygame.Surface] = {}
log = logging.getLogger(__name__)


def set_letter_art(mode: str, root: Path | None = None) -> None:
    """Select the glyph route; root contains letters/manifest.toml."""
    global _painted
    if mode not in {"painted", "traced", "drawn"}:
        raise ValueError(f"Unknown letter art mode: {mode}")
    _painted = mode == "painted"
    _stickers.clear()
    _scaled_sticker.cache_clear()
    _pop_frames.cache_clear()
    if not _painted:
        return
    directory = (root if root is not None else assets.asset_root()) / "letters"
    try:
        with (directory / "manifest.toml").open("rb") as stream:
            manifest = tomllib.load(stream)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        log.warning("Ignoring letter manifest in %s: %s", directory, exc)
        return
    rows = manifest.get("letters", {})
    if manifest.get("schema") != 1 or not isinstance(rows, dict):
        return
    for letter in ascii_uppercase:
        if letter not in rows:
            continue
        try:
            path = Path(rows[letter]["file"])
            if path.anchor or ".." in path.parts:
                raise ValueError("file must be relative to the letter manifest")
            art = assets.load_image(directory / path)
            bounds = art.get_bounding_rect(min_alpha=1)
            if not bounds or not art.get_bounding_rect(min_alpha=128):
                raise ValueError("empty sticker")
            _stickers[letter] = art.subsurface(bounds)
        except (KeyError, TypeError, ValueError, OSError, pygame.error, NotImplementedError) as exc:
            log.warning("Ignoring painted letter %s: %s", letter, exc)


def painted_letters() -> bool:
    """Placement follows the requested mode even when a sticker falls back."""
    return _painted


def _width_at(native: tuple[int, int], height: int) -> int:
    return max(1, round(native[0] * height / native[1]))


def _eye_anchors(art: pygame.Surface) -> tuple[int, int, int]:
    """Find two inked columns on the upper stroke, including split strokes like M."""
    w, h = art.get_size()
    rows = sorted(range(h), key=lambda y: abs(y - h * .14))
    for y in rows:
        ink = [x for x in range(w) if art.get_at((x, y)).a >= 128]
        if ink:
            return ink[len(ink) // 4], ink[3 * len(ink) // 4], y
    # At very small display sizes, smoothing may soften all of the opaque ink.
    return w // 3, 2 * w // 3, round(h * .14)


@cache
def _scaled_sticker(letter: str, height: int):
    native = _stickers[letter]
    size = _width_at(native.get_size(), height), height
    art = pygame.transform.smoothscale(native, size) if size != native.get_size() else native
    return art, _eye_anchors(art)


# A short set of reusable pop poses, including the exact hold and overshoot.
# Keep only a handful of large pop sets between presses on the 1 GB Pi.
_POP_SCALES = (.05, .18, .32, .46, .60, .74, .88, 1., 1.075, 1.15)
_POP_CUTS = tuple((a + b) / 2 for a, b in zip(_POP_SCALES, _POP_SCALES[1:]))


@lru_cache(maxsize=6)
def _pop_frames(art: pygame.Surface) -> tuple[pygame.Surface, ...]:
    w, h = art.get_size()
    return tuple(art if scale == 1 else pygame.transform.scale(
        art, (max(1, int(w * scale)), max(1, int(h * scale))))
        for scale in _POP_SCALES)


_CANDIDATES = (tuple((x, y) for y in (.14, .27, .40) for x in (.08, .35, .65, .92))
               + ((.08, .68), (.92, .68)))


def _footprint(w: int, h: int) -> pygame.Rect:
    """Envelope of the centred pop and the hold-phase sway, including narrow glyphs."""
    return pygame.Rect(0, 0, max(math.ceil(1.15 * w), w + 2 * math.ceil(.012 * h)),
                       math.ceil(1.15 * h))


def _place(ctx: EffectContext, native: tuple[int, int], height: int,
           occupied: list[pygame.Rect]) -> tuple[tuple[int, int], int]:
    screen = pygame.Rect((0, 0), ctx.size)
    tie = ctx.rng.random()  # one draw even for a unique fit or a completely full screen
    best_score = (math.inf, 0)
    spots = []
    for fraction in (1., .925, .85):
        h = math.ceil(height * fraction)
        box = _footprint(_width_at(native, h), h)
        for fx, fy in _CANDIDATES:
            box.center = round(screen.w * fx), round(screen.h * fy)
            box.clamp_ip(screen)
            inside = box.clip(screen)
            area = box.w * box.h - inside.w * inside.h
            for rect in occupied:
                hit = inside.clip(rect)
                area += hit.w * hit.h
            score = area, -h  # largest equally clear size wins
            if score < best_score:
                spots.clear()
                best_score = score
            if score == best_score:
                spots.append((box.center, h))
        if best_score[0] == 0:
            break
    return spots[int(tie * len(spots))]


def _font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.Font(None, size)  # bundled freesansbold
    return _font_cache[size]


_OUTLINE_OFFSETS = [(-1, -1), (0, -1), (1, -1), (-1, 0),
                    (1, 0), (-1, 1), (0, 1), (1, 1)]


def _rainbowize(glyph: pygame.Surface) -> None:
    """Multiply a white-rendered glyph by a vertical rainbow gradient
    (~28 horizontal bands; spawn-time only)."""
    w, h = glyph.get_size()
    bands = 28
    strip = pygame.Surface((w, h))
    # Bands sized to span the glyph surface exactly — a fixed band height
    # overshot the surface, so the violet end of the ramp fell past the ink
    # and letters only ever showed red-to-cyan.
    for i in range(bands):
        y0 = round(i * h / bands)
        y1 = round((i + 1) * h / bands)
        r, g, b = colorsys.hsv_to_rgb((i / (bands - 1)) * 0.92, 0.85, 1.0)
        pygame.draw.rect(strip, (int(r * 255), int(g * 255), int(b * 255)),
                         (0, y0, w, max(1, y1 - y0)))
    glyph.blit(strip, (0, 0), special_flags=pygame.BLEND_RGB_MULT)


def render_glyph(text: str, size: int, color: tuple[int, int, int],
                 rng=None, rainbow: bool = False) -> pygame.Surface:
    """Fill + thick outline, rendered once. White fills get a colored outline
    so they still read; everything else gets a white one."""
    outline_color = (255, 255, 255)
    if color == (255, 255, 255):
        # BRIGHT_PALETTE contains white, so draw until we get a real color —
        # a white outline on a white fill would erase the whole effect.
        while outline_color == (255, 255, 255):
            outline_color = random_bright(rng)
    if rainbow:
        fill = _font(size).render(text, True, (255, 255, 255)).convert_alpha()
        _rainbowize(fill)
    else:
        fill = _font(size).render(text, True, color).convert_alpha()
    outline = _font(size).render(text, True, outline_color).convert_alpha()
    t = max(2, size // 36)  # outline thickness
    out = pygame.Surface((fill.get_width() + 2 * t, fill.get_height() + 2 * t),
                         pygame.SRCALPHA)
    for dx, dy in _OUTLINE_OFFSETS:
        out.blit(outline, (t + dx * t, t + dy * t))
    out.blit(fill, (t, t))
    return out


class GiantLetter:
    """A huge letter pops in, wobbles with googly eyes, fades out.

    Painted mode blits cached pop poses for the first ~0.3 s. The original
    font route keeps its continuous integer scaling during that interval.
    The hold-phase wobble is a position bob/sway rather than a rotation —
    rotating a ~650 px RGBA surface every frame is the kind of cost the Pi
    frame budget exists to forbid, and the bob reads just as alive.
    """

    POP_TIME = 0.3
    HOLD_TIME = 1.0
    FADE_TIME = 0.6
    RAINBOW_CHANCE = 0.25

    def __init__(self, ctx: EffectContext, text: str,
                 pos: tuple[float, float] | None = None,
                 color: tuple[int, int, int] | None = None,
                 height_frac: float = 0.6,
                 eyes: bool = True,
                 hold_time: float | None = None,
                 arrival_space: list[pygame.Rect] | None = None) -> None:
        # The font's optional white-outline reroll must not affect placement
        # or the next effect when a painted file is present, missing or bad.
        art_rng = random.Random(ctx.rng.random()) if _painted else ctx.rng
        self.color = color or random_bright(art_rng)
        size = int(ctx.height * height_frac)
        rainbow = art_rng.random() < self.RAINBOW_CHANCE
        self._eye_ink = None
        self._pop = None
        source = _stickers.get(text)
        if source is None:
            art = render_glyph(text, size, self.color, art_rng, rainbow)
            native = art.get_size()
            height = art.get_height()
        else:
            native = source.get_size()
            # Match the ink height the outlined font would have displayed.
            _, _, low, high, _ = _font(size).metrics(text)[0]
            height = max(1, high - low + 2 * max(2, size // 36))
        if pos is None and _painted:
            obstacles = ctx.occupied()
            if arrival_space:
                obstacles = obstacles + arrival_space
            pos, height = _place(ctx, native, height, obstacles)
        self.pos = pos or (ctx.rng.uniform(ctx.width * 0.3, ctx.width * 0.7),
                           ctx.rng.uniform(ctx.height * 0.35, ctx.height * 0.65))
        if source is not None:
            art, self._eye_ink = _scaled_sticker(text, height)
        elif height != art.get_height():
            art = pygame.transform.smoothscale(art, (_width_at(native, height), height))
        if _painted:
            self._pop = _pop_frames(art)
        # A subsurface shares the cached pixels but owns its blanket fade alpha.
        self.glyph = art.subsurface(art.get_rect()) if source is not None else art
        self.eyes = eyes
        self.eye_phase = ctx.rng.uniform(0, math.tau)
        self._eye_frames = {}
        if eyes and self._pop is not None:
            variant = sum(map(ord, text)) - ord("A")
            for pose in self._pop:
                _, _, radius = self._eye_layout(pose.get_rect())
                if radius not in self._eye_frames:
                    frames = prepare_eye(radius, variant)
                    if frames is None:
                        break
                    self._eye_frames[radius] = frames
        self.age = 0.0
        # hold_time lets a caller stretch the display (count-along keeps its
        # digit up until the last object has been counted).
        self.hold_time = self.HOLD_TIME if hold_time is None else hold_time
        self.total = self.POP_TIME + self.hold_time + self.FADE_TIME

    @property
    def footprint(self) -> pygame.Rect:
        rect = _footprint(*self.glyph.get_size())
        rect.center = int(self.pos[0]), int(self.pos[1])
        return rect

    def update(self, dt: float) -> bool:
        self.age += dt
        return self.age < self.total

    def retire(self) -> None:
        """Skip straight to the fade — the engine sheds the oldest glyphs when
        the screen gets crowded. Idempotent, and never *extends* a life."""
        self.age = max(self.age, self.total - self.FADE_TIME)

    def _wobble(self) -> tuple[int, int]:
        if self.age < self.POP_TIME:
            return (0, 0)
        t = self.age - self.POP_TIME
        h = self.glyph.get_height()
        return (int(math.sin(t * 2.1 + self.eye_phase) * h * 0.012),
                int(math.sin(t * 3.4) * h * 0.02))

    def _eye_layout(self, rect: pygame.Rect) -> tuple[tuple[int, int], int, int]:
        """Carry the two upper-stroke anchors through the painted pop poses."""
        r = max(6, rect.height // 14)
        cy = rect.top + int(rect.height * 0.10)
        xs = (rect.centerx - int(rect.width * 0.16), rect.centerx + int(rect.width * 0.16))
        if self._eye_ink is not None:
            left, right, y = self._eye_ink
            w, h = self.glyph.get_size()
            if rect.size != (w, h):
                left, right = round(left * rect.w / w), round(right * rect.w / w)
                y = round(y * rect.h / h)
            xs = rect.x + left, rect.x + right
            cy = rect.y + y
            # Big googly eyes read as a face at a glance; they may nearly touch (owner: "upgrade the eyes").
            r = max(2, min(rect.height // 9, int((right - left) * 0.62)))
        return xs, cy, r

    def _blink(self) -> float:
        phase = self.eye_phase / math.tau
        period = 2 + 3 * phase
        elapsed = (self.age + phase * period) % period
        return max(0., 1 - abs(elapsed - .10) / .10)

    def _draw_eyes(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        xs, cy, r = self._eye_layout(rect)
        wander = self.age * 2.6 + self.eye_phase
        px = int(math.cos(wander) * r * 0.35)
        py = int(math.sin(wander * 0.7) * r * 0.35)
        frames = self._eye_frames.get(r)
        if frames is None:
            for ex in xs:
                draw_original_eye(surface, (ex, cy), r, px, py)
            return
        blink = self._blink()
        settle = self.age / (self.POP_TIME + .12)
        if settle < 1:
            py -= round(r * .40 * (1 - settle) * math.sin(math.tau * settle))
        for ex in xs:
            draw_eye(surface, (ex, cy), r, px, py, blink, art=frames)

    def draw(self, surface: pygame.Surface) -> None:
        img = self.glyph
        if self.age < self.POP_TIME:
            # Overshoot pop: grow 0 → 1.15, settle back to 1.0
            t = self.age / self.POP_TIME
            if t < 0.7:
                scale = max(0.05, 1.15 * (t / 0.7))
            else:
                scale = 1.15 - 0.15 * ((t - 0.7) / 0.3)
            if self._pop is not None:
                img = self._pop[bisect_left(_POP_CUTS, scale)]
            else:
                w = max(1, int(img.get_width() * scale))
                h = max(1, int(img.get_height() * scale))
                img = pygame.transform.scale(img, (w, h))
        elif self.age > self.POP_TIME + self.hold_time:
            fade = 1.0 - (self.age - self.POP_TIME - self.hold_time) / self.FADE_TIME
            # The glyph is instance-owned and the phases are monotonic, so
            # set_alpha in place is safe — copying a ~1 MB surface every fade
            # frame was measured at 3.7x the cost of the plain blit.
            img.set_alpha(int(255 * max(0.0, fade)))
        ox, oy = self._wobble()
        rect = img.get_rect(center=(int(self.pos[0]) + ox, int(self.pos[1]) + oy))
        surface.blit(img, rect)
        if self.eyes and self.age <= self.POP_TIME + self.hold_time and (
                self._eye_frames or self.age >= self.POP_TIME):
            self._draw_eyes(surface, rect)

    def __len__(self) -> int:  # counts toward particle budget as a flat cost
        return 20
