"""Pip the frog — the one character who is always on screen, on his lily pad.

Cel-shaded on purpose. The pond is near-black and everything else in the app is
a burst that appears and fades; Pip is the only constant, so he is the thing a
toddler looks *at* rather than watches. Flat colour with hard-edged shadow and
highlight bands and a heavy dark keyline reads at a glance from across a room,
where a soft gradient turns to mush.

Two rules shape the code:

* **The sprite is cached by (radius, pose).** Building him is extravagant —
  a dozen shapes, two clipped shading passes, an outline on everything — and
  that is fine, because it happens once per size. Only the per-frame blit is
  budgeted. Squash is the exception: it is continuous, so it is applied at draw
  time with a plain ``scale``, which is cheap and only runs in the few frames
  after a bounce.
* **Physics is untouched.** ``self.r``, ``self.x``, ``self.y`` and the bounce
  behaviour are exactly as before; only the drawing changed. The lily pad is
  cosmetic — it drifts under him and never affects where he can go, because a
  character a child is shoving with arrow keys should never get caught on
  scenery.

He is also a co-player, not scenery: the engine tells him where every new
effect appeared (``notice``) and he reacts —

* **Gaze-follow.** His pupils steer toward the most recent spawn, then relax
  back to neutral. Gaze is *quantised* into eight ``look_*`` poses so it stays
  inside the (radius, pose) cache — a continuous pupil offset would mean a
  per-frame sprite build, which is exactly what the cache exists to forbid.
  Cartoon eyes darting in steps read as charm, not cheapness.
* **Tongue-catch.** A spawn gets a tongue flick toward it (cooldown-rationed)
  and a happy hop. The open ``tongue`` mouth is a cached pose; the tongue
  itself is the one other continuous thing besides squash, drawn as four
  vector strokes for a handful of frames because a cached pose cannot stretch
  toward an arbitrary point.
* **Celebration.** Milestones and mash storms put him in the ``cheer`` pose
  (arms up, happy-shut eyes, open mouth) with one huge launch and joy-hops
  while the party lasts.

No licensed characters; every pixel comes from pygame primitives.
"""

from __future__ import annotations

import math

import pygame

# Cel palette: three flat greens, no gradients between them.
BODY = (108, 206, 74)
BODY_LIGHT = (156, 236, 116)
BODY_DARK = (64, 154, 60)
BELLY = (232, 246, 182)
BELLY_DARK = (198, 224, 146)
OUTLINE = (20, 44, 26)
CHEEK = (248, 146, 158)
EYE_WHITE = (255, 255, 255)
PUPIL = (28, 30, 34)
NOSTRIL = (44, 92, 44)

TONGUE = (244, 108, 128)   # sticky cartoon pink, deliberately not the cheeks'
MOUTH_OPEN = (46, 22, 30)  # the inside of an open mouth

PAD = (44, 120, 62)
PAD_LIGHT = (70, 158, 84)
PAD_DARK = (26, 82, 48)
PAD_OUTLINE = (14, 40, 26)

POSES = (
    "idle", "blink", "tongue", "cheer",
    "look_l", "look_r", "look_u", "look_d",
    "look_ul", "look_ur", "look_dl", "look_dr",
)

# Quantised gaze direction → pose name, and back again for the sprite builder.
# (0, 0) is deliberately absent: looking straight ahead IS "idle".
_GAZE_POSES: dict[tuple[int, int], str] = {
    (-1, 0): "look_l", (1, 0): "look_r", (0, -1): "look_u", (0, 1): "look_d",
    (-1, -1): "look_ul", (1, -1): "look_ur", (-1, 1): "look_dl", (1, 1): "look_dr",
}
_POSE_PUPILS = {name: d for d, name in _GAZE_POSES.items()}

#: How long a spawn holds his attention before the pupils relax to neutral.
GAZE_HOLD = 2.2
#: Normalised direction components smaller than this read as "straight ahead".
_GAZE_DEADZONE = 0.38

# The tongue flick: fast out, a beat at full stretch, a slower slurp back.
TONGUE_OUT = 0.10
TONGUE_HOLD = 0.06
TONGUE_IN = 0.16
TONGUE_TOTAL = TONGUE_OUT + TONGUE_HOLD + TONGUE_IN
#: Max stretch, as a fraction of screen height. Long enough to be a cartoon
#: gag, short enough that a far-corner spawn gets a reach *toward* it.
TONGUE_REACH = 0.45
#: Seconds between flicks. A toddler mashes several keys a second; the gaze
#: tracks every one of them, the tongue only the ones it can savour.
FLICK_COOLDOWN = 0.7
#: The mouth's centre as a fraction of the sprite box's height, so the tongue
#: stays rooted to his face even mid-squash (the box scales, the fraction
#: doesn't). Must agree with where frog_sprite draws the mouth.
_MOUTH_FRAC = 0.52

#: Happy-hop launch for a tongue-catch, as a fraction of hop_impulse. Small,
#: but a real launch — so the landing is a real bounce with squash and ripples.
HAPPY_HOP = 0.34
#: The milestone-party launch. Joy-hops while excited are 0.8; the first one
#: is visibly bigger than anything an ordinary catch produces.
MEGA_HOP = 1.15

_sprite_cache: dict[tuple[int, str], pygame.Surface] = {}
_pad_cache: dict[int, pygame.Surface] = {}


def _finish(surf: pygame.Surface) -> pygame.Surface:
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        return surf.convert_alpha()
    return surf


def _ellipse(surf, colour, cx, cy, w, h, width=0):
    rect = pygame.Rect(0, 0, max(1, int(w)), max(1, int(h)))
    rect.center = (int(cx), int(cy))
    pygame.draw.ellipse(surf, colour, rect, width)
    return rect


def _shade_band(target: pygame.Surface, mask: pygame.Surface, colour,
                cx: float, cy: float, w: float, h: float) -> None:
    """A hard-edged blob of ``colour``, clipped to ``mask``'s alpha.

    This is what makes it read as cel shading rather than airbrushing: the
    boundary between lit and unlit is a crisp curve, not a fade. Clipping is
    the usual alpha-multiply trick — the mask is white, so it leaves colour
    alone and multiplies alpha.
    """
    layer = pygame.Surface(target.get_size(), pygame.SRCALPHA)
    _ellipse(layer, colour, cx, cy, w, h)
    layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    target.blit(layer, (0, 0))


def _smile(surf: pygame.Surface, cx: float, cy: float, width: float,
           depth: float, thickness: int) -> None:
    """A wide upturned mouth, as a sampled curve.

    ``pygame.draw.arc`` is unreliable for exactly this shape — a wide, flat
    ellipse with a thick stroke — and silently drew nothing. A polyline always
    renders and gives control over where the corners turn up.
    """
    pts = []
    steps = 24
    for i in range(steps + 1):
        t = i / steps * 2 - 1                       # -1 .. 1
        pts.append((cx + t * width * 0.5, cy + (1 - t * t) * depth))
    pygame.draw.lines(surf, OUTLINE, False, pts, thickness)
    # Corners flicked up, which is most of what makes it read as a smile.
    for side in (-1, 1):
        end = (cx + side * width * 0.5, cy)
        pygame.draw.line(surf, OUTLINE, end,
                         (end[0] + side * width * 0.06, cy - depth * 0.45),
                         thickness)


def _stamp_outline(target: pygame.Surface, silhouette: pygame.Surface,
                   colour, thickness: int) -> None:
    """Draw a single keyline around a whole silhouette.

    Outlining each ellipse separately leaves seams where shapes overlap — on a
    frog that lands as a stray line straight across his face, because the head
    and body are two overlapping ellipses. Stamping the *union* eight times
    underneath gives one clean line around the outside and none within.
    """
    dark = silhouette.copy()
    dark.fill(colour, special_flags=pygame.BLEND_RGB_MAX)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                   (-1, -1), (1, -1), (-1, 1), (1, 1)):
        target.blit(dark, (dx * thickness, dy * thickness))


def frog_sprite(r: int, pose: str = "idle") -> pygame.Surface:
    """Cached front-on Pip, ``r`` being the physics radius he is built around."""
    r = max(12, int(r))
    if pose not in POSES:
        pose = "idle"
    key = (r, pose)
    hit = _sprite_cache.get(key)
    if hit is not None:
        return hit

    w, h = int(r * 3.4), int(r * 3.0)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    cx = w / 2
    cy = h * 0.62                      # body centre
    line = max(2, int(r * 0.10))

    body_w, body_h = r * 2.30, r * 1.66
    head_w, head_h = r * 1.94, r * 1.36
    head_cy = cy - r * 0.60
    eye_r = r * 0.46
    eye_y = head_cy - head_h * 0.44

    def limb(colour, x, y, ew, eh):
        """A limb is its own shape, so it keeps its own outline — that seam is
        wanted, it's what separates a leg from the body."""
        _ellipse(s, colour, x, y, ew, eh)
        _ellipse(s, OUTLINE, x, y, ew, eh, line)

    # ---- feet and haunches, behind the body ------------------------------
    for side in (-1, 1):
        limb(BODY_DARK, cx + side * r * 1.14, h - r * 0.26, r * 1.05, r * 0.44)
    for side in (-1, 1):
        limb(BODY, cx + side * r * 0.44, h - r * 0.22, r * 0.68, r * 0.36)
    for side in (-1, 1):
        limb(BODY, cx + side * r * 1.00, cy + r * 0.40, r * 1.12, r * 1.02)

    # ---- head + body as one silhouette (frogs have no neck) --------------
    # Built black so BLEND_RGB_MAX can tint it to anything; a white silhouette
    # would swallow every colour it was asked to take.
    sil = pygame.Surface((w, h), pygame.SRCALPHA)
    _ellipse(sil, (0, 0, 0), cx, cy, body_w, body_h)
    _ellipse(sil, (0, 0, 0), cx, head_cy, head_w, head_h)
    for side in (-1, 1):
        _ellipse(sil, (0, 0, 0), cx + side * r * 0.60, eye_y, eye_r * 2.2, eye_r * 2.2)
    mask = sil.copy()
    mask.fill((255, 255, 255), special_flags=pygame.BLEND_RGB_MAX)

    _stamp_outline(s, sil, OUTLINE, line)
    body = sil.copy()
    body.fill(BODY, special_flags=pygame.BLEND_RGB_MAX)
    s.blit(body, (0, 0))

    # Cel shading: one lit band up-left, one shadow band down-right. Big soft
    # shapes with hard clipped edges — the hallmark of the style.
    _shade_band(s, mask, BODY_LIGHT, cx - r * 0.52, head_cy - r * 0.30,
                r * 1.70, r * 1.30)
    _shade_band(s, mask, BODY_DARK, cx + r * 0.86, cy + r * 0.52,
                r * 1.85, r * 1.50)

    # Belly, over the shading so it stays bright.
    _ellipse(s, BELLY, cx, cy + r * 0.34, r * 1.44, r * 0.94)
    _shade_band(s, mask, BELLY_DARK, cx + r * 0.66, cy + r * 0.78, r * 1.05, r * 0.62)
    _ellipse(s, OUTLINE, cx, cy + r * 0.34, r * 1.44, r * 0.94, max(1, line - 1))

    # ---- arms, in front of the body --------------------------------------
    if pose == "cheer":
        # Both arms thrown up beside the head — the universal "hooray!".
        for side in (-1, 1):
            limb(BODY, cx + side * r * 1.22, head_cy - r * 0.35, r * 0.46, r * 0.92)
    else:
        for side in (-1, 1):
            limb(BODY, cx + side * r * 0.92, cy + r * 0.10, r * 0.48, r * 0.84)

    # ---- eyes -------------------------------------------------------------
    gaze = _POSE_PUPILS.get(pose)
    for side in (-1, 1):
        ex = cx + side * r * 0.60
        if pose == "blink":
            # A closed lid: a fat arc where the eye was, which reads far better
            # at small sizes than a squashed white sliver.
            rect = pygame.Rect(0, 0, int(eye_r * 1.8), int(eye_r * 1.8))
            rect.center = (int(ex), int(eye_y))
            pygame.draw.arc(s, OUTLINE, rect, math.pi * 1.10, math.pi * 1.90,
                            max(2, line))
        elif pose == "cheer":
            # Happy-shut eyes: the blink arc flipped — ∩ reads as "so happy",
            # ∪ as "asleep". Same square rect, so arc stays reliable.
            rect = pygame.Rect(0, 0, int(eye_r * 1.8), int(eye_r * 1.8))
            rect.center = (int(ex), int(eye_y))
            pygame.draw.arc(s, OUTLINE, rect, math.pi * 0.15, math.pi * 0.85,
                            max(2, line))
        else:
            _ellipse(s, EYE_WHITE, ex, eye_y, eye_r * 1.66, eye_r * 1.66)
            _ellipse(s, OUTLINE, ex, eye_y, eye_r * 1.66, eye_r * 1.66,
                     max(1, line - 1))
            if gaze is not None:
                # Both pupils steer the same way: opposite offsets read as
                # cross-eyed, not as looking at something.
                px_ = ex + gaze[0] * eye_r * 0.34
                py_ = eye_y + gaze[1] * eye_r * 0.28
            else:
                px_ = ex + side * eye_r * 0.10
                py_ = eye_y + eye_r * 0.12
            _ellipse(s, PUPIL, px_, py_, eye_r * 0.94, eye_r * 1.04)
            # The highlight stays with the light source, not the pupil —
            # that is what keeps a steered eye reading as wet and alive.
            _ellipse(s, EYE_WHITE, ex + side * eye_r * 0.30, eye_y - eye_r * 0.36,
                     eye_r * 0.40, eye_r * 0.40)

    # ---- face -------------------------------------------------------------
    for side in (-1, 1):
        _ellipse(s, NOSTRIL, cx + side * r * 0.24, head_cy - r * 0.02,
                 r * 0.13, r * 0.11)

    # A frog's mouth runs the full width of its face — a small mouth reads as a
    # different animal entirely. Drawn as an explicit curve rather than
    # ``draw.arc``: arc is unreliable on a wide, flat rect with a thick stroke
    # and rendered nothing at all here.
    if pose == "cheer":
        # A wide-open cheer with the tongue showing — the mouth doing jazz hands.
        _ellipse(s, MOUTH_OPEN, cx, head_cy + r * 0.36, r * 1.06, r * 0.70)
        _ellipse(s, TONGUE, cx, head_cy + r * 0.52, r * 0.60, r * 0.30)
        _ellipse(s, OUTLINE, cx, head_cy + r * 0.36, r * 1.06, r * 0.70,
                 max(2, int(r * 0.11)))
    elif pose == "tongue":
        # A round little "o" for the tongue to shoot out of. The tongue itself
        # is drawn at draw time (its length is continuous); its root must land
        # on this mouth, which is what _MOUTH_FRAC records.
        _ellipse(s, MOUTH_OPEN, cx, head_cy + r * 0.30, r * 0.62, r * 0.50)
        _ellipse(s, OUTLINE, cx, head_cy + r * 0.30, r * 0.62, r * 0.50,
                 max(2, int(r * 0.11)))
    else:
        _smile(s, cx, head_cy + r * 0.16, r * 1.56, r * 0.42, max(2, int(r * 0.11)))

    for side in (-1, 1):
        _ellipse(s, CHEEK, cx + side * r * 0.78, head_cy + r * 0.40,
                 r * 0.44, r * 0.28)

    s = _finish(s)
    _sprite_cache[key] = s
    return s


def lily_pad_sprite(r: int) -> pygame.Surface:
    """Pip's own pad — bigger and brighter than the background ones.

    The pond scenery already floats three small dark pads. This one has to read
    as *his*, in the foreground, so it is lighter, wider and gets the same
    keyline and hard-edged shading as the frog.
    """
    r = max(12, int(r))
    hit = _pad_cache.get(r)
    if hit is not None:
        return hit

    # Flatter than it is wide, and deliberately shallow: seen almost edge-on
    # from the toddler's viewpoint, and a taller pad would push its front notch
    # off the bottom of the screen.
    pw, ph = int(r * 4.6), int(r * 1.40)
    s = pygame.Surface((pw, ph), pygame.SRCALPHA)
    cx, cy = pw / 2, ph * 0.52
    line = max(2, int(r * 0.09))

    _ellipse(s, PAD, cx, cy, pw * 0.96, ph * 0.86)

    mask = pygame.Surface((pw, ph), pygame.SRCALPHA)
    _ellipse(mask, (255, 255, 255), cx, cy, pw * 0.96, ph * 0.86)
    _shade_band(s, mask, PAD_LIGHT, cx - r * 0.5, cy - r * 0.34, pw * 0.62, ph * 0.44)
    _shade_band(s, mask, PAD_DARK, cx + r * 0.7, cy + r * 0.46, pw * 0.70, ph * 0.52)

    # Veins radiating from the notch, the detail that says "lily pad" and not
    # "green puddle".
    for i in range(-3, 4):
        a = math.pi * 0.5 + i * 0.30
        pygame.draw.line(s, PAD_DARK, (cx, cy),
                         (cx + math.cos(a) * pw * 0.44,
                          cy - math.sin(a) * ph * 0.40), max(1, line // 2))

    _ellipse(s, PAD_OUTLINE, cx, cy, pw * 0.96, ph * 0.86, line)

    # The classic wedge cut out of the near edge, punched to fully transparent.
    notch = [(cx, cy + ph * 0.04),
             (cx - pw * 0.10, cy + ph * 0.52),
             (cx + pw * 0.10, cy + ph * 0.52)]
    pygame.draw.polygon(s, (0, 0, 0, 0), notch)

    s = _finish(s)
    _pad_cache[r] = s
    return s


# How the pad hangs off the waterline Pip's feet rest on: its centre sits this
# fraction of its own height below that line, and it rides this fraction of his
# radius up and down. Named because ``pad_reach`` below has to agree with the
# drawing exactly — the pad's front notch is its whole charm and it is the first
# thing to go over the bottom edge.
_PAD_SINK = 0.40
_PAD_BOB = 0.05

#: Downward acceleration, in screen heights per second squared.
GRAVITY = 1.4

#: How much faster than one frame of gravity a landing must be to count as a
#: real bounce. Anything slower is Pip settling, not Pip hopping.
REST_FACTOR = 1.5


def pad_reach(r: int) -> float:
    """How far below the waterline the pad's lowest bob reaches."""
    return lily_pad_sprite(r).get_height() * (_PAD_SINK + 0.5) + r * _PAD_BOB


def _radius_for(screen_h: int) -> int:
    """The physics radius a Frog on a screen this tall is built around.

    Shared with :func:`prewarm` so the poses built at boot are the poses the
    live Frog will actually ask for — a prewarm at the wrong radius is worse
    than none, it doubles the work and still hitches.
    """
    return max(30, int(screen_h * 0.06))


def prewarm(screen_height: int) -> int:
    """Build every pose now, before anyone presses a key.

    Pip used to have two poses, both built on the first frame. He now has a
    dozen — gaze directions, the tongue mouth, the cheer — and each is a few
    milliseconds of shading passes and outline stamps. Paid lazily that lands
    as a hiccup the first time he glances at something, which is the exact
    moment he is supposed to look alive. Paid here it is part of a boot nobody
    is watching. Returns how many sprites were touched.
    """
    r = _radius_for(screen_height)
    for pose in POSES:
        frog_sprite(r, pose)
    lily_pad_sprite(r)
    return len(POSES)


class _Pad:
    """The pad drifts under Pip instead of being nailed to one spot.

    A pad floats, so following him reads as natural on water — and it means he
    is *always* sitting on his lily pad, which a fixed pad could not promise
    once a toddler has shoved him into a corner.
    """

    FOLLOW = 2.6        # how fast it catches up, in units of dt

    def __init__(self, size: tuple[int, int], r: int, surface_y: float) -> None:
        self.w, self.h = size
        self.r = r
        self.x = self.w * 0.5
        # Where the top of the pad sits — the line Pip's feet rest on.
        self.surface_y = surface_y
        self.age = 0.0

    def update(self, dt: float, target_x: float) -> None:
        self.age += dt
        self.x += (target_x - self.x) * min(1.0, dt * self.FOLLOW)

    @property
    def bob(self) -> float:
        """Vertical float, as an offset. Exposed so a resting Pip can ride it —
        a pad sliding up and down through the soles of his feet is worse than
        no bob at all."""
        return math.sin(self.age * 1.3) * self.r * _PAD_BOB

    @property
    def y(self) -> float:
        sprite_h = lily_pad_sprite(self.r).get_height()
        return self.surface_y + sprite_h * _PAD_SINK + self.bob

    def draw(self, surface: pygame.Surface) -> None:
        sprite = lily_pad_sprite(self.r)
        surface.blit(sprite, sprite.get_rect(center=(int(self.x), int(self.y))))


class Frog:
    """Persistent — update() always returns True; the engine owns exactly one."""

    def __init__(self, size: tuple[int, int]) -> None:
        self.w, self.h = size
        self.r = _radius_for(self.h)
        self.x = self.w * 0.5
        self.y = self.h * 0.82
        self.vx = 0.0
        self.vy = 0.0
        self.squash = 0.0        # 0..1, decays; squashes the draw
        self.age = 0.0
        #: Settled on the pad with no vertical motion left. Drives whether he
        #: rides the pad's float, and is the honest answer to "is he still?".
        self.resting = False
        self.hop_impulse = self.h * 0.9
        self.just_bounced = False    # set each update; engine spawns ripples
        self._excited_until = 0.0    # celebration joy-hops while age < this
        # --- reactions: gaze, tongue, party -------------------------------
        self._gaze_target = (self.x, 0.0)
        self._gaze_until = 0.0       # gaze relaxes once age passes this
        self._gaze = (0, 0)          # quantised look direction; (0,0) = ahead
        self._tongue_target = (self.x, 0.0)
        self._tongue_t = TONGUE_TOTAL    # >= TONGUE_TOTAL means fully retracted
        self._next_flick = 0.0
        #: Kind of the last spawn he was told about ("letter", "number", …).
        #: Purely observational — for tests and future flavour, never logic.
        self.last_noticed: str | None = None

        #: Vertical gap from his centre to the soles of his feet.
        self._feet = self.r * 0.62
        # Resting height. He used to settle at ``h - r``, which puts his feet on
        # the very bottom pixel and left no room to show what he is sitting on.
        # Lifting the floor is what makes the lily pad visible at all — and the
        # amount is *measured* from the pad rather than guessed, because a
        # guessed 1.8r left the notch hanging a few pixels off the screen.
        self.floor_y = self.h - pad_reach(self.r) - self._feet
        self.pad = _Pad(size, self.r, self.floor_y + self._feet)

    def shove(self, direction: tuple[int, int]) -> None:
        dx, dy = direction
        self.vx += dx * self.hop_impulse
        self.vy += dy * self.hop_impulse
        # A hop always gets a little lift so left/right feels like jumping.
        if dy == 0:
            self.vy -= self.hop_impulse * 0.25

    def notice(self, pos: tuple[float, float], kind: str = "effect") -> None:
        """Something (letter / number / animal / shape) just appeared at ``pos``.

        The engine calls this once per spawn. Pip looks at it, and — cooldown
        permitting — flicks his tongue toward it with a happy little hop, like
        he is catching it. During a party the cheer wins instead: the tongue
        and the cheer share the mouth, and an excited frog is already reacting
        as hard as he can.
        """
        self._gaze_target = (float(pos[0]), float(pos[1]))
        self._gaze_until = self.age + GAZE_HOLD
        self.last_noticed = kind
        if self.age < self._excited_until:
            return
        if self.age >= self._next_flick:
            self._next_flick = self.age + FLICK_COOLDOWN
            self._tongue_t = 0.0
            self._tongue_target = self._gaze_target
            if self.resting:
                # A real launch, so the landing is a real bounce: squash and
                # the engine's splash ripple come for free. Only from rest —
                # boosting him mid-flight would fight the arrow-key physics.
                self.vy = -self.hop_impulse * HAPPY_HOP

    def celebrate(self, seconds: float = 3.0) -> None:
        """Milestone joy: one huge launch right now, then joy-hops while excited.

        ``min`` keeps whichever upward speed is faster, so a party that lands
        mid-flight never *cancels* motion. The tongue retracts because the
        cheer pose owns the mouth.
        """
        self._excited_until = self.age + seconds
        self._tongue_t = TONGUE_TOTAL
        self.vy = min(self.vy, -self.hop_impulse * MEGA_HOP)

    def keep_celebrating(self, seconds: float = 0.6) -> None:
        """Extend a running party without re-firing the launch.

        The engine calls this every frame while the mash-storm overlay is
        live, so Pip parties for exactly as long as the storm does — however
        long the toddler keeps drumming.
        """
        self._excited_until = max(self._excited_until, self.age + seconds)

    def update(self, dt: float) -> bool:
        self.age += dt
        self.squash = max(0.0, self.squash - dt * 3)
        # Gravity + drag
        self.vy += self.h * GRAVITY * dt
        self.vx *= max(0.0, 1.0 - 1.2 * dt)
        self.x += self.vx * dt
        self.y += self.vy * dt
        r = self.r
        bounced = False
        if self.x < r:
            self.x, self.vx, bounced = r, abs(self.vx) * 0.85, True
        elif self.x > self.w - r:
            self.x, self.vx, bounced = self.w - r, -abs(self.vx) * 0.85, True
        if self.y < r:
            self.y, self.vy, bounced = r, abs(self.vy) * 0.85, True
        elif self.y > self.floor_y:
            # A resting frog re-enters the floor every frame carrying exactly
            # the speed gravity just gave him — which is proportional to dt.
            #
            # This test used to be a flat `impact < 40`, and that number is
            # only true at one frame rate: at 1080p gravity adds 25/frame at
            # 60 fps but 41/frame at 37 fps, so below ~37 fps a *sitting still*
            # frog registered a fresh landing on every single frame, squashing
            # and raining ripples forever. Exactly the frame rates a Pi drops
            # to under load, and the engine's own degradation makes it more
            # likely, not less. Compare against gravity's own step so the test
            # means the same thing at 60 fps and at 10.
            impact = abs(self.vy)
            self.y = self.floor_y
            if impact <= self.h * GRAVITY * dt * REST_FACTOR:
                self.vy = 0.0
            else:
                self.vy = -impact * 0.7
                bounced = True
            # Joy-hop: while excited and touching the floor, launch again.
            if self.age < self._excited_until:
                self.vy = -self.hop_impulse * 0.8
                self.vx += (1 if (int(self.age * 7) % 2) else -1) * self.hop_impulse * 0.3
        if bounced:
            self.squash = 1.0
        self.just_bounced = bounced
        # Drag is exponential and so never actually reaches zero: left alone,
        # Pip slides a fraction of a pixel sideways forever and the pad chases
        # him for the rest of the afternoon. Below a pixel a second, stop.
        if abs(self.vx) < self.w * 0.001:
            self.vx = 0.0
        self.resting = (self.vy == 0.0 and self.vx == 0.0
                        and self.y >= self.floor_y - 0.5)
        self.pad.update(dt, self.x)
        # --- reactions ----------------------------------------------------
        if self._tongue_t < TONGUE_TOTAL:
            self._tongue_t = min(TONGUE_TOTAL, self._tongue_t + dt)
        if self.age >= self._gaze_until:
            self._gaze = (0, 0)
        else:
            tx, ty = self._gaze_target
            dx_, dy_ = tx - self.x, ty - (self.y - self.r)   # from his eyes
            dist = math.hypot(dx_, dy_)
            if dist < self.r * 1.6:
                # Right on top of him: "looking at" that is cross-eyed.
                self._gaze = (0, 0)
            else:
                nx, ny = dx_ / dist, dy_ / dist
                self._gaze = (
                    -1 if nx < -_GAZE_DEADZONE else (1 if nx > _GAZE_DEADZONE else 0),
                    -1 if ny < -_GAZE_DEADZONE else (1 if ny > _GAZE_DEADZONE else 0),
                )
        return True

    @property
    def pose(self) -> str:
        # Priority: the tongue owns the mouth mid-flick, a party owns
        # everything, a blink closes even a steered eye, and only then does
        # the gaze pick which way the pupils point.
        if self._tongue_t < TONGUE_TOTAL:
            return "tongue"
        if self.age < self._excited_until:
            return "cheer"
        if (self.age % 4.0) > 3.85:
            return "blink"
        return _GAZE_POSES.get(self._gaze, "idle")

    def draw(self, surface: pygame.Surface) -> None:
        self.pad.draw(surface)

        sprite = frog_sprite(self.r, self.pose)
        if self.squash > 0.01:
            # Continuous, so it cannot be a cached pose. `scale` rather than
            # `smoothscale` — this runs for a handful of frames after every
            # bounce and the difference is invisible at that speed.
            sw, sh = sprite.get_size()
            sprite = pygame.transform.scale(
                sprite, (max(2, int(sw * (1 + 0.22 * self.squash))),
                         max(2, int(sh * (1 - 0.22 * self.squash)))))
        # Once he is settled, ride the pad's float instead of hovering at a
        # fixed height while it slides up and down through his feet. In flight
        # the pad is irrelevant — he is nowhere near it.
        y = self.y + (self.pad.bob if self.resting else 0.0)
        # Bottom-anchored so a squashing frog settles onto his pad rather than
        # shrinking toward his own middle.
        rect = sprite.get_rect(midbottom=(int(self.x), int(y + self._feet)))
        surface.blit(sprite, rect)
        if self._tongue_t < TONGUE_TOTAL:
            self._draw_tongue(surface, rect)

    def _draw_tongue(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        """The flick itself — the one continuous thing besides squash.

        Length is a tween and direction tracks the mouth as he hops, so it
        cannot be a cached pose; it is four vector strokes (keyline pass, then
        pink) for a handful of frames per flick. No surfaces are built.
        """
        t = self._tongue_t
        if t < TONGUE_OUT:
            ext = t / TONGUE_OUT
        elif t < TONGUE_OUT + TONGUE_HOLD:
            ext = 1.0
        else:
            ext = max(0.0, 1.0 - (t - TONGUE_OUT - TONGUE_HOLD) / TONGUE_IN)
        if ext <= 0.02:
            return
        # The mouth as a fraction of the (possibly squashed) sprite box, so
        # the tongue stays rooted to his face mid-bounce.
        mx = rect.centerx
        my = rect.top + rect.height * _MOUTH_FRAC
        dx_ = self._tongue_target[0] - mx
        dy_ = self._tongue_target[1] - my
        dist = math.hypot(dx_, dy_) or 1.0
        reach = min(dist, self.h * TONGUE_REACH) * ext
        tip = (mx + dx_ / dist * reach, my + dy_ / dist * reach)
        line = max(2, int(self.r * 0.10))
        thick = max(3, int(self.r * 0.20))
        tip_r = max(4, int(self.r * 0.28))
        # Keyline first, pink on top: the same one-heavy-outline look as the
        # rest of him, without stamping anything.
        pygame.draw.line(surface, OUTLINE, (mx, my), tip, thick + line * 2)
        pygame.draw.circle(surface, OUTLINE, (int(tip[0]), int(tip[1])), tip_r + line)
        pygame.draw.line(surface, TONGUE, (mx, my), tip, thick)
        pygame.draw.circle(surface, TONGUE, (int(tip[0]), int(tip[1])), tip_r)

    def __len__(self) -> int:
        return 8
