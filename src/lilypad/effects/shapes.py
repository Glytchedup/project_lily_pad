"""Colours and shapes — the third lesson, after letters and numbers.

Letters bring animals and digits bring countable things; the punctuation keys
brought twelve identical sparkles. That is the same wasted-row problem the
F-keys had before the back half became dinosaurs, and it is fixed the same
way: those keys now name a colour or a shape out loud.

The two halves teach by holding one thing constant and varying the other,
which is the whole pedagogy in one sentence:

* a **shape** key shows one shape in a random colour — the shape is the lesson;
* a **colour** key shows several *different* shapes in one colour — the colour
  is the lesson, and nothing else on screen agrees except the hue.

Art is cel-shaded to match Pip: flat fill, one hard-edged shadow crescent, a
gloss highlight, and a heavy keyline — which is what reads from across a room
where a soft gradient turns to mush.

Every sprite is built once at a supersampled size and scaled down, so the
edges are smooth without any per-frame cost. The expensive part is cached per
``(kind, size)`` as a **white** master; colour arrives as a
``BLEND_RGB_MULT`` tint, which turns the white fill into the colour, darkens
the grey band into that colour's shadow, and leaves the near-black keyline
near-black. So the whole palette costs one extra surface per combination
rather than a fresh supersampled render.
"""

from __future__ import annotations

import math

import pygame

from .base import EffectContext, random_bright
from .particles import ParticleSystem, burst, confetti_rain

#: Every shape a key can name. Deliberately the five a 2-year-old meets first —
#: adding "pentagon" would be a word for the adult in the room, not the child.
SHAPE_KINDS: tuple[str, ...] = ("circle", "square", "triangle", "star", "heart")

#: The colour vocabulary, as *names a child is taught*, which is why this is a
#: separate list from BRIGHT_PALETTE: the palette contains teal, indigo and
#: white because they look good in a particle burst, and none of the three is
#: a word worth drilling at two. Values are the palette's where they agree.
NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "red":    (255, 59, 48),
    "orange": (255, 149, 0),
    "yellow": (255, 214, 10),
    "green":  (52, 199, 89),
    "blue":   (10, 132, 255),
    "purple": (191, 90, 242),
    "pink":   (255, 55, 95),
}

#: Supersample factor for shape rendering. pygame's polygon and rect drawing
#: is not anti-aliased, and a hard-jagged heart at 500 px reads as a mistake
#: rather than a style. 3x is the point where the stairs stop being visible at
#: 1080p; higher just costs memory in the transient buffer.
SUPERSAMPLE = 3

KEYLINE = (24, 22, 30)
SHADOW = (168, 168, 172)        # multiplied into the fill -> a darker band
GLOSS_ALPHA = 78

#: (kind, size) -> white master, ready to tint.
_master_cache: dict[tuple[str, int], pygame.Surface] = {}
#: (kind, size, color) -> finished sprite.
_sprite_cache: dict[tuple[str, int, tuple[int, int, int]], pygame.Surface] = {}


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def _polygon(kind: str, box: float) -> list[tuple[float, float]]:
    """Points for ``kind`` inscribed in a ``box``-sized square at the origin.

    Circles and squares are drawn by pygame directly and never come here.
    """
    c = box / 2
    if kind == "triangle":
        # Sat on its base rather than centred on the centroid: a triangle
        # floating above its own baseline reads as falling over.
        return [(c, box * 0.06), (box * 0.96, box * 0.92), (box * 0.04, box * 0.92)]
    if kind == "star":
        points = []
        for i in range(10):
            # Start at -90 deg so a point is at the top; alternate outer/inner.
            angle = -math.pi / 2 + i * math.pi / 5
            r = c * 0.98 if i % 2 == 0 else c * 0.42
            points.append((c + math.cos(angle) * r, c + math.sin(angle) * r))
        return points
    if kind == "heart":
        # The classic parametric heart, sampled densely enough that the cusp
        # and the two lobes survive the downscale.
        points = []
        for i in range(72):
            t = i * math.tau / 72
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t)
                  - 2 * math.cos(3 * t) - math.cos(4 * t))
            points.append((c + x * (c / 17.5), c + y * (c / 17.5)))
        return points
    raise ValueError(f"no polygon for {kind!r}")


def _fill_shape(surface: pygame.Surface, kind: str, box: float,
                inset: float, color: tuple[int, int, int]) -> None:
    """Draw ``kind`` filled, shrunk by ``inset`` px on every side."""
    size = box - 2 * inset
    if size <= 1:
        return
    if kind == "circle":
        pygame.draw.circle(surface, color, (box / 2, box / 2), size / 2)
        return
    if kind == "square":
        # Rounded, because a hard 90-degree corner next to a heart and a star
        # looks like a missing sprite rather than a deliberate shape.
        pygame.draw.rect(surface, color, (inset, inset, size, size),
                         border_radius=int(size * 0.12))
        return
    pts = [(inset + x * size / box, inset + y * size / box)
           for x, y in _polygon(kind, box)]
    pygame.draw.polygon(surface, color, pts)


# --------------------------------------------------------------------------
# Sprite construction
# --------------------------------------------------------------------------

def _build_master(kind: str, size: int) -> pygame.Surface:
    """A white, cel-shaded, keylined shape at ``size`` px, ready to tint."""
    ss = size * SUPERSAMPLE
    box = float(ss)
    keyline_w = max(2.0, ss * 0.035)

    # The interior, as its own layer — everything else is clipped back to it.
    inner = pygame.Surface((ss, ss), pygame.SRCALPHA)
    _fill_shape(inner, kind, box, keyline_w, (255, 255, 255))

    # Cel shadow: the interior in grey, with the interior itself stamped back
    # offset up-left. What survives is a hard crescent along the lower right.
    shade = inner.copy()
    shade.fill(SHADOW, special_flags=pygame.BLEND_RGB_MULT)
    offset = -ss * 0.055
    shade.blit(inner, (offset, offset))
    # The offset stamp hangs outside the silhouette on the up-left edge; MIN
    # against the untouched interior clips both colour and alpha back to it.
    shade.blit(inner, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)

    # Gloss: an ellipse in the upper left, clipped the same way. Pure white and
    # applied *after* the tint, so it stays a highlight instead of becoming
    # another shade of the fill colour.
    gloss = pygame.Surface((ss, ss), pygame.SRCALPHA)
    pygame.draw.ellipse(gloss, (255, 255, 255, GLOSS_ALPHA),
                        (ss * 0.18, ss * 0.14, ss * 0.34, ss * 0.22))
    gloss.blit(inner, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)

    out = pygame.Surface((ss, ss), pygame.SRCALPHA)
    _fill_shape(out, kind, box, 0, KEYLINE)
    out.blit(shade, (0, 0))
    out.blit(gloss, (0, 0))
    return pygame.transform.smoothscale(out, (size, size))


def master_sprite(kind: str, size: int) -> pygame.Surface:
    key = (kind, size)
    if key not in _master_cache:
        _master_cache[key] = _build_master(kind, size)
    return _master_cache[key]


def shape_sprite(kind: str, size: int,
                 color: tuple[int, int, int]) -> pygame.Surface:
    """A finished, tinted shape. Cached — callers must not mutate the result.

    Tinting is a multiply, which is what keeps one master usable for every
    colour: white fill becomes the colour, the grey band becomes a darker
    version of it, and the near-black keyline stays near-black.
    """
    size = max(8, int(size))
    key = (kind, size, color)
    if key not in _sprite_cache:
        sprite = master_sprite(kind, size).copy()
        sprite.fill(color, special_flags=pygame.BLEND_RGB_MULT)
        _sprite_cache[key] = sprite
    return _sprite_cache[key]


def prewarm(screen_height: int) -> int:
    """Build the masters the two effects will ask for. Returns how many.

    Same reasoning as the animal cast: assembling a supersampled shape costs
    several milliseconds, and that hitch should not land on a child's first
    keypress. Only the *masters* are prebuilt — a tint is cheap enough to pay
    for on the press that needs it.
    """
    for size in (_giant_size(screen_height), _splash_size(screen_height)):
        for kind in SHAPE_KINDS:
            master_sprite(kind, size)
    return len(_master_cache)


def _giant_size(screen_height: int) -> int:
    return max(8, int(screen_height * GiantShape.HEIGHT_FRAC))


def _splash_size(screen_height: int) -> int:
    return max(8, int(screen_height * ColorSplash.HEIGHT_FRAC))


# --------------------------------------------------------------------------
# Effects
# --------------------------------------------------------------------------

class GiantShape:
    """One huge shape pops in, breathes, and fades — the shape is the lesson.

    Colour is deliberately random on every press: a circle that is always blue
    teaches "blue circle" as one word. Varying it is what separates the shape
    from its colour, which is the entire point of having both.
    """

    POP_TIME = 0.32
    HOLD_TIME = 1.15
    FADE_TIME = 0.55
    HEIGHT_FRAC = 0.46

    def __init__(self, ctx: EffectContext, kind: str,
                 color: tuple[int, int, int] | None = None,
                 pos: tuple[float, float] | None = None) -> None:
        self.ctx = ctx
        self.kind = kind if kind in SHAPE_KINDS else SHAPE_KINDS[0]
        self.color = color or random_bright(ctx.rng)
        self.sprite = shape_sprite(self.kind, _giant_size(ctx.height), self.color)
        self.pos = pos or (
            ctx.rng.uniform(ctx.width * 0.34, ctx.width * 0.66),
            ctx.rng.uniform(ctx.height * 0.38, ctx.height * 0.60),
        )
        self.age = 0.0
        self.phase = ctx.rng.uniform(0, math.tau)
        self.total = self.POP_TIME + self.HOLD_TIME + self.FADE_TIME
        # A burst in the shape's own colour, so the whole event reads as one
        # thing rather than a shape with unrelated confetti behind it.
        self.sparks = burst(ctx, self.pos, count=38, speed=330,
                            colors=[self.color], life=1.0)

    def update(self, dt: float) -> bool:
        self.age += dt
        self.sparks.update(dt)
        return self.age < self.total or len(self.sparks) > 0

    def _scale(self) -> float:
        """Overshoot on the way in, then a slow breath during the hold."""
        if self.age < self.POP_TIME:
            t = self.age / self.POP_TIME
            if t < 0.7:
                return max(0.05, 1.16 * (t / 0.7))
            return 1.16 - 0.16 * ((t - 0.7) / 0.3)
        return 1.0 + 0.022 * math.sin((self.age - self.POP_TIME) * 2.6 + self.phase)

    def draw(self, surface: pygame.Surface) -> None:
        self.sparks.draw(surface)
        if self.age >= self.total:
            return
        img = self.sprite
        scale = self._scale()
        if abs(scale - 1.0) > 0.002:
            w = max(1, int(img.get_width() * scale))
            img = pygame.transform.scale(img, (w, w))
        held = self.POP_TIME + self.HOLD_TIME
        if self.age > held:
            fade = max(0.0, 1.0 - (self.age - held) / self.FADE_TIME)
            # The cache is shared, so a fading frame must work on a copy —
            # set_alpha on the cached sprite would poison every later use.
            if img is self.sprite:
                img = img.copy()
            img.set_alpha(int(255 * fade))
        surface.blit(img, img.get_rect(center=(int(self.pos[0]), int(self.pos[1]))))

    def __len__(self) -> int:
        return 20 + len(self.sparks)


class ColorSplash:
    """One colour, many shapes — the colour is the lesson.

    Every shape on screen is a different kind and every one is the same hue,
    so the only thing the child can generalise from is the colour. Shapes pop
    in left to right on a beat, the way count-along paces its objects, because
    five things appearing at once is a flash rather than a sequence.
    """

    POP_INTERVAL = 0.13
    HOLD_AFTER_LAST = 1.15
    FADE_TIME = 0.55
    HEIGHT_FRAC = 0.2

    def __init__(self, ctx: EffectContext, color_name: str,
                 count: int = 5) -> None:
        self.ctx = ctx
        self.name = color_name if color_name in NAMED_COLORS else "red"
        self.color = NAMED_COLORS[self.name]
        self.age = 0.0
        rng = ctx.rng

        # One of each kind, shuffled, so the *set* of shapes is different every
        # press while the colour never is.
        kinds = list(SHAPE_KINDS)
        rng.shuffle(kinds)
        kinds = kinds[:max(1, min(count, len(kinds)))]

        size = _splash_size(ctx.height)
        self.items: list[dict] = []
        for i, kind in enumerate(kinds):
            frac = (i + 0.5) / len(kinds)
            self.items.append({
                "sprite": shape_sprite(kind, size, self.color),
                "pos": (ctx.width * (0.14 + 0.72 * frac),
                        ctx.height * (0.5 - 0.1 * math.sin(frac * math.pi))),
                "born": i * self.POP_INTERVAL,
                "phase": rng.uniform(0, math.tau),
            })
        self.last_born = (len(kinds) - 1) * self.POP_INTERVAL
        self.total = self.last_born + self.HOLD_AFTER_LAST + self.FADE_TIME
        # Confetti in the same colour: the background agrees with the lesson.
        self.confetti = confetti_rain(ctx, count=70, colors=[self.color])

    def update(self, dt: float) -> bool:
        self.age += dt
        self.confetti.update(dt)
        return self.age < self.total or len(self.confetti) > 0

    def draw(self, surface: pygame.Surface) -> None:
        self.confetti.draw(surface)
        fade_start = self.total - self.FADE_TIME
        alpha = 1.0
        if self.age > fade_start:
            alpha = max(0.0, 1.0 - (self.age - fade_start) / self.FADE_TIME)
        if alpha <= 0.0:
            return
        for item in self.items:
            t = self.age - item["born"]
            if t <= 0:
                continue
            img = item["sprite"]
            pop = min(1.0, t / 0.18)
            scale = 1.18 * (pop / 0.8) if pop < 0.8 else 1.18 - 0.18 * ((pop - 0.8) / 0.2)
            scale += 0.02 * math.sin(t * 2.4 + item["phase"])
            if abs(scale - 1.0) > 0.002:
                w = max(1, int(img.get_width() * scale))
                img = pygame.transform.scale(img, (w, w))
            if alpha < 1.0:
                if img is item["sprite"]:
                    img = img.copy()
                img.set_alpha(int(255 * alpha))
            x, y = item["pos"]
            surface.blit(img, img.get_rect(center=(int(x), int(y))))

    def __len__(self) -> int:
        return 20 * len(self.items) + len(self.confetti)
