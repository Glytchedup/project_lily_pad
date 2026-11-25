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

No licensed characters; the drawn route's pixels come from pygame primitives
and the painted route's from the repo's own generated art.

**Two routes.** ``effects.pip_art = "drawn"`` is the cel-shaded Pip described
above. ``"painted"`` loads the ``[pip]`` and ``[pad]`` rows of
``assets/painted/manifest.toml`` (idle/blink/cheer/eyes_white frames and one
pad) and scales them into the very same ``(radius, pose)`` cache and the same
box the drawn sprites occupy, so physics, ``floor_y`` and ``pad_reach`` never
notice which route is active. Anything missing or undecodable logs once and
falls back to the drawn Pip. ``eyes_white`` is a pupil-less frame; the pupils
are two small discs drawn on top at draw time so they can look around.
"""

from __future__ import annotations

import logging
import math
import tomllib
from pathlib import Path

import pygame

from . import assets

log = logging.getLogger(__name__)

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

PAD = (44, 120, 62)
PAD_LIGHT = (70, 158, 84)
PAD_DARK = (26, 82, 48)
PAD_OUTLINE = (14, 40, 26)

POSES = ("idle", "blink")
#: Frames the painted route can supply. ``cheer`` and ``eyes_white`` are
#: optional and alias ``idle`` when the art lacks them.
PAINTED_POSES = ("idle", "blink", "cheer", "eyes_white")

_sprite_cache: dict[tuple[int, str], pygame.Surface] = {}
_pad_cache: dict[int, pygame.Surface] = {}

# The painted sprite fills the drawn sprite's box (height 3.0 r) and the painted
# pad the drawn pad's height (1.4 r), so layout maths is route-independent.
_SPRITE_HEIGHT = 3.0
_PAD_HEIGHT = 1.40
#: Pupil disc radius, and how far it may roam from the eye centre, in units of r.
_PUPIL_R = 0.13
_PUPIL_TRAVEL = 0.12

_pip_art = "drawn"
_art_root: Path | None = None
#: Decoded painted art, filled lazily: {"pip": _PaintedPip | None, "pad": Surface | None}.
_painted: dict[str, object] = {}
_manifest_cache: dict | None = None


class _PaintedPip:
    """Native-size painted frames plus the measured left-eye position."""

    __slots__ = ("frames", "eye_at")

    def __init__(self, frames: dict[str, pygame.Surface], eye_at) -> None:
        self.frames = frames
        self.eye_at = eye_at


def set_pip_art(mode: str, root: Path | None = None) -> None:
    """Select ``"painted"`` or ``"drawn"`` Pip before the Frog is built.

    ``root`` is the asset root (the directory holding ``painted/``); by default
    the package assets, or ``LILYPAD_ART_DIR`` in dev. Selecting a mode drops
    every cached sprite and anything decoded for the previous one.
    """
    global _pip_art, _art_root, _manifest_cache
    if mode not in ("painted", "drawn"):
        raise ValueError(f"unknown pip art mode {mode!r}")
    _pip_art, _art_root, _manifest_cache = mode, root, None
    _painted.clear()
    _sprite_cache.clear()
    _pad_cache.clear()


def _art_directory() -> Path:
    return (_art_root if _art_root is not None else assets.asset_root()) / "painted"


def _manifest() -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        directory = _art_directory()
        data: dict = {}
        try:
            with (directory / "manifest.toml").open("rb") as stream:
                data = tomllib.load(stream)
            if type(data.get("schema")) is not int or data["schema"] != 1:
                raise ValueError("expected schema = 1")
        except (OSError, ValueError) as exc:
            log.warning("Ignoring painted manifest in %s: %s", directory, exc)
            data = {}
        _manifest_cache = data
    return _manifest_cache


def _frame_file(name: object) -> Path:
    relative = Path(str(name))
    if (relative.anchor or ".." in relative.parts
            or relative.suffix.lower() not in (".png", ".webp")):
        raise ValueError(f"invalid painted frame path {name!r}")
    return _art_directory() / relative


def _rgba(frame: pygame.Surface) -> pygame.Surface:
    if frame.get_bitsize() == 32 and frame.get_masks()[3]:
        return frame
    out = pygame.Surface(frame.get_size(), pygame.SRCALPHA)
    out.blit(frame, (0, 0))
    return out


def _load_painted_pip() -> _PaintedPip | None:
    row = _manifest().get("pip")
    if row is None:
        log.info("pip_art is painted but the manifest has no [pip] entry; drawing Pip")
        return None
    try:
        native = row["native_height"]
        if type(native) is not int or native <= 0:
            raise ValueError("invalid native_height")
        files = row["frames"]
        frames = {}
        for pose in PAINTED_POSES:
            if pose in files:
                frames[pose] = _rgba(assets.load_image(_frame_file(files[pose])))
            elif pose in ("idle", "blink"):
                raise KeyError(pose)
        size = frames["idle"].get_size()
        if size[1] != native or any(f.get_size() != size for f in frames.values()):
            raise ValueError("frames must share the declared native canvas")
        eye = row["eye_at"]
        if (not isinstance(eye, list) or len(eye) != 2
                or not all(type(v) in (int, float) and 0 <= v <= 1 for v in eye)):
            raise ValueError("invalid eye_at coordinates")
        return _PaintedPip(frames, (float(eye[0]), float(eye[1])))
    except (KeyError, TypeError, OSError, ValueError, pygame.error,
            NotImplementedError) as exc:
        log.warning("Ignoring painted Pip, drawing him instead: %s", exc)
        return None


def _load_painted_pad() -> pygame.Surface | None:
    row = _manifest().get("pad")
    if row is None:
        log.info("pip_art is painted but the manifest has no [pad] entry; drawing the pad")
        return None
    try:
        native = row["native_height"]
        if type(native) is not int or native <= 0:
            raise ValueError("invalid native_height")
        image = _rgba(assets.load_image(_frame_file(row["file"])))
        if image.get_height() != native:
            raise ValueError("pad must match its native_height")
        return image
    except (KeyError, TypeError, OSError, ValueError, pygame.error,
            NotImplementedError) as exc:
        log.warning("Ignoring painted pad, drawing it instead: %s", exc)
        return None


def _painted_pip() -> _PaintedPip | None:
    """The painted Pip when that route is selected and valid, else None."""
    if _pip_art != "painted":
        return None
    if "pip" not in _painted:
        _painted["pip"] = _load_painted_pip()
    return _painted["pip"]    # type: ignore[return-value]


def _painted_pad() -> pygame.Surface | None:
    if _pip_art != "painted":
        return None
    if "pad" not in _painted:
        _painted["pad"] = _load_painted_pad()
    return _painted["pad"]    # type: ignore[return-value]


def painted_pip_active() -> bool:
    """True when Pip is currently painted rather than drawn."""
    return _painted_pip() is not None


def _fit_height(native: pygame.Surface, height: int) -> pygame.Surface:
    w, h = native.get_size()
    if h != height:
        native = pygame.transform.smoothscale(
            native, (max(1, round(w * height / h)), height))
    return native


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
    art = _painted_pip()
    if art is not None:
        # Absent optional frames alias idle before the key is formed, so one
        # cache entry serves them all.
        if pose not in art.frames:
            pose = "idle"
    elif pose not in POSES:
        pose = "idle"
    key = (r, pose)
    hit = _sprite_cache.get(key)
    if hit is not None:
        return hit
    if art is not None:
        s = _finish(_fit_height(art.frames[pose], int(r * _SPRITE_HEIGHT)))
        _sprite_cache[key] = s
        return s

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
    for side in (-1, 1):
        limb(BODY, cx + side * r * 0.92, cy + r * 0.10, r * 0.48, r * 0.84)

    # ---- eyes -------------------------------------------------------------
    for side in (-1, 1):
        ex = cx + side * r * 0.60
        if pose == "blink":
            # A closed lid: a fat arc where the eye was, which reads far better
            # at small sizes than a squashed white sliver.
            rect = pygame.Rect(0, 0, int(eye_r * 1.8), int(eye_r * 1.8))
            rect.center = (int(ex), int(eye_y))
            pygame.draw.arc(s, OUTLINE, rect, math.pi * 1.10, math.pi * 1.90,
                            max(2, line))
        else:
            _ellipse(s, EYE_WHITE, ex, eye_y, eye_r * 1.66, eye_r * 1.66)
            _ellipse(s, OUTLINE, ex, eye_y, eye_r * 1.66, eye_r * 1.66,
                     max(1, line - 1))
            _ellipse(s, PUPIL, ex + side * eye_r * 0.10, eye_y + eye_r * 0.12,
                     eye_r * 0.94, eye_r * 1.04)
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
    art = _painted_pad()
    if art is not None:
        s = _finish(_fit_height(art, max(1, int(r * _PAD_HEIGHT))))
        _pad_cache[r] = s
        return s

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


def pad_reach(r: int) -> float:
    """How far below the waterline the pad's lowest bob reaches."""
    return lily_pad_sprite(r).get_height() * (_PAD_SINK + 0.5) + r * _PAD_BOB


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
    def y(self) -> float:
        sprite_h = lily_pad_sprite(self.r).get_height()
        bob = math.sin(self.age * 1.3) * self.r * _PAD_BOB
        return self.surface_y + sprite_h * _PAD_SINK + bob

    def draw(self, surface: pygame.Surface) -> None:
        sprite = lily_pad_sprite(self.r)
        surface.blit(sprite, sprite.get_rect(center=(int(self.x), int(self.y))))


class Frog:
    """Persistent — update() always returns True; the engine owns exactly one."""

    def __init__(self, size: tuple[int, int]) -> None:
        self.w, self.h = size
        self.r = max(30, int(self.h * 0.06))
        self.x = self.w * 0.5
        self.y = self.h * 0.82
        self.vx = 0.0
        self.vy = 0.0
        self.squash = 0.0        # 0..1, decays; squashes the draw
        self.age = 0.0
        self.hop_impulse = self.h * 0.9
        self.just_bounced = False    # set each update; engine spawns ripples
        self._excited_until = 0.0    # celebration joy-hops while age < this
        self.dancing = False         # reward dance party — hops until told to stop
        self.gaze: tuple[float, float] | None = None   # painted Pip's pupils

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

    def celebrate(self, seconds: float = 3.0) -> None:
        """Milestone joy: keep hopping on its own for a few seconds."""
        self._excited_until = self.age + seconds

    def dance(self, on: bool = True) -> None:
        """Dance party: joy-hop for as long as the music lasts.

        Same mechanism as ``celebrate`` — a hop relaunched on every landing —
        but open-ended rather than timed, because the reward track decides
        when the party is over, not a countdown here.
        """
        self.dancing = bool(on)

    def update(self, dt: float) -> bool:
        self.age += dt
        self.squash = max(0.0, self.squash - dt * 3)
        # Gravity + drag
        self.vy += self.h * 1.4 * dt
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
            # A resting frog re-enters the floor by a sub-pixel every frame
            # (gravity), so only a real impact counts as a bounce — otherwise
            # he'd stay squashed forever and rain ripples while sitting still.
            # That "sub-pixel" only stays sub-40px/s at ~60fps though — the
            # velocity gravity adds in one frame is dt * h * 1.4, so a fixed
            # 40 threshold reads plain resting gravity as a real landing on
            # any frame that runs under ~38fps. On hardware that dips below
            # that under load (confirmed on the Pi 3 test board), *every*
            # frame while sitting still crossed it — a permanent phantom
            # bounce, not a decaying tail, so he never actually stopped
            # shaking or throwing off ripples. Scale the cutoff with dt so it
            # stays ahead of gravity alone at whatever frame rate is actually
            # happening; a real hop's impulse (``hop_impulse``, in the
            # hundreds) is nowhere near this even at very low fps, so genuine
            # landings still register.
            impact = abs(self.vy)
            self.y = self.floor_y
            settle_threshold = max(40.0, self.h * 1.4 * dt * 1.5)
            if impact < settle_threshold:
                self.vy = 0.0
            else:
                # 0.7 restitution used to take up to 8 decaying bounces (~2.5s)
                # to fall back under the settle threshold above — each one
                # re-triggering squash and a fresh ripple, so a single hop
                # left him visibly shaking with rings piling on top of each
                # other well after he'd actually stopped moving. 0.45 settles
                # the same hop in ~4 bounces inside a second: still springy,
                # not a lingering shudder.
                self.vy = -impact * 0.45
                bounced = True
            # Joy-hop: while excited and touching the floor, launch again.
            if self.dancing:
                # Dance party. Hop height breathes on a slow sine so a
                # two-minute track reads as dancing rather than one hop on
                # repeat, and the sway is wider than a joy-hop's — he works
                # his way across the pond and back.
                beat = 0.75 + 0.25 * math.sin(self.age * 1.7)
                self.vy = -self.hop_impulse * 0.8 * beat
                self.vx += (1 if (int(self.age * 3.5) % 2) else -1) * self.hop_impulse * 0.45
            elif self.age < self._excited_until:
                self.vy = -self.hop_impulse * 0.8
                self.vx += (1 if (int(self.age * 7) % 2) else -1) * self.hop_impulse * 0.3
        if bounced:
            self.squash = 1.0
        self.just_bounced = bounced
        self.pad.update(dt, self.x)
        return True

    def look(self, dx: float | None, dy: float = 0.0) -> None:
        """Aim the pupils (painted Pip only); ``look(None)`` stops looking.

        ``dx`` and ``dy`` run from -1 to 1 across the pupils' range of travel.
        Nothing calls this yet: it is the hook for eye tracking.
        """
        if dx is None:
            self.gaze = None
        else:
            self.gaze = (max(-1.0, min(1.0, dx)), max(-1.0, min(1.0, dy)))

    @property
    def cheering(self) -> bool:
        """Dancing at a party, or joy-hopping after a milestone."""
        return self.dancing or self.age < self._excited_until

    @property
    def pose(self) -> str:
        if (self.age % 4.0) > 3.85:
            # A blink only shows on a Pip who is not mid-cheer.
            if not (self.cheering and painted_pip_active()):
                return "blink"
        if painted_pip_active():
            if self.cheering:
                return "cheer"
            if self.gaze is not None:
                return "eyes_white"
        return "idle"

    def _draw_pupils(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        art = _painted_pip()
        if art is None or "eyes_white" not in art.frames or self.gaze is None:
            return
        ex, ey = art.eye_at
        travel = self.r * _PUPIL_TRAVEL
        radius = max(2, round(self.r * _PUPIL_R))
        for fx in (ex, 1.0 - ex):
            centre = (round(rect.x + fx * rect.w + self.gaze[0] * travel),
                      round(rect.y + ey * rect.h + self.gaze[1] * travel))
            pygame.draw.circle(surface, PUPIL, centre, radius)

    def draw(self, surface: pygame.Surface) -> None:
        self.pad.draw(surface)

        pose = self.pose
        sprite = frog_sprite(self.r, pose)
        if self.squash > 0.01:
            # Continuous, so it cannot be a cached pose. `scale` rather than
            # `smoothscale` — this runs for a handful of frames after every
            # bounce and the difference is invisible at that speed.
            sw, sh = sprite.get_size()
            sprite = pygame.transform.scale(
                sprite, (max(2, int(sw * (1 + 0.22 * self.squash))),
                         max(2, int(sh * (1 - 0.22 * self.squash)))))
        # Bottom-anchored so a squashing frog settles onto his pad rather than
        # shrinking toward his own middle.
        rect = sprite.get_rect(midbottom=(int(self.x), int(self.y + self._feet)))
        surface.blit(sprite, rect)
        if pose == "eyes_white":
            self._draw_pupils(surface, rect)

    def __len__(self) -> int:
        return 8
