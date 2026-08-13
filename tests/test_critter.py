"""Pip the frog and the lily pad he sits on.

He is the only thing permanently on screen, so his art is cached and his
resting position is load-bearing: it is what leaves room for the pad under
him. Everything here guards one of those two things.
"""


import pygame
import pytest

from lilypad.effects import critter
from lilypad.effects.critter import Frog, frog_sprite, lily_pad_sprite

SIZE = (960, 540)


@pytest.fixture(autouse=True)
def _clear_caches():
    critter._sprite_cache.clear()
    critter._pad_cache.clear()
    yield


# ---------------------------------------------------------------- the sprite
def test_the_sprite_is_built_once_and_reused():
    """He is drawn every frame at 60 fps; rebuilding him would be absurd."""
    first = frog_sprite(40, "idle")
    assert frog_sprite(40, "idle") is first
    assert frog_sprite(40, "blink") is not first


def test_blink_differs_from_idle():
    idle = frog_sprite(48, "idle")
    blink = frog_sprite(48, "blink")
    assert idle.get_size() == blink.get_size()
    diff = sum(1 for x in range(0, idle.get_width(), 2)
               for y in range(0, idle.get_height(), 2)
               if idle.get_at((x, y)) != blink.get_at((x, y)))
    assert diff > 0


def test_an_unknown_pose_falls_back_rather_than_raising():
    assert frog_sprite(40, "wat").get_size() == frog_sprite(40, "idle").get_size()


def test_he_is_actually_drawn():
    s = frog_sprite(50)
    assert s.get_bounding_rect().width > s.get_width() * 0.6
    opaque = sum(1 for x in range(0, s.get_width(), 3)
                 for y in range(0, s.get_height(), 3)
                 if s.get_at((x, y))[3] > 0)
    assert opaque > 40


def test_he_has_eye_whites_and_a_dark_keyline():
    """The two things the cel-shaded look depends on most.

    Whites are what make the eyes read as eyes at a distance, and without the
    keyline he dissolves into a near-black pond.
    """
    s = frog_sprite(60)
    px = [s.get_at((x, y)) for x in range(0, s.get_width(), 2)
          for y in range(0, s.get_height(), 2) if s.get_at((x, y))[3] > 0]
    assert any(p.r > 240 and p.g > 240 and p.b > 240 for p in px), "no eye whites"
    assert any(p.r < 60 and p.g < 80 and p.b < 60 for p in px), "no keyline"


def test_he_is_mostly_green():
    s = frog_sprite(60)
    px = [s.get_at((x, y)) for x in range(0, s.get_width(), 2)
          for y in range(0, s.get_height(), 2) if s.get_at((x, y))[3] > 0]
    greener = sum(1 for p in px if p.g > p.r and p.g > p.b)
    assert greener > len(px) * 0.5


@pytest.mark.parametrize("r", (12, 30, 64, 120))
def test_he_builds_at_any_size(r):
    assert frog_sprite(r).get_width() > 0
    assert lily_pad_sprite(r).get_width() > 0


# ------------------------------------------------------------------ the pad
def test_the_pad_is_wider_than_he_is():
    """Otherwise he looks perched on a coin rather than sitting on a pad."""
    r = 50
    assert lily_pad_sprite(r).get_width() > frog_sprite(r).get_width()


def test_he_rests_high_enough_to_show_the_pad_under_him():
    """The whole point of moving the floor.

    At the old resting height his feet were on the very bottom row of pixels,
    so anything drawn beneath him was off-screen.
    """
    frog = Frog(SIZE)
    assert frog.floor_y < SIZE[1] - frog.r, "no room under him for a pad"
    for _ in range(240):
        frog.update(1 / 60)
    assert frog.y == pytest.approx(frog.floor_y, abs=1.0)


def test_the_pad_sits_under_his_feet_and_stays_on_screen():
    frog = Frog(SIZE)
    for _ in range(240):
        frog.update(1 / 60)
    pad = lily_pad_sprite(frog.r)
    top = frog.pad.y - pad.get_height() * 0.43
    feet = frog.y + frog._feet
    assert top <= feet + frog.r * 0.2, "he is floating above his pad"
    assert top > SIZE[1] * 0.5, "the pad has slid off the bottom of the screen"


@pytest.mark.parametrize("size", [(1920, 1080), (1280, 720), (800, 600)])
def test_the_pads_front_notch_never_hangs_off_the_bottom(size):
    """The notch is the tell that says lily pad, and it is the lowest point.

    The resting height used to be a guessed multiple of his radius, which put
    the bottom few pixels of the pad past the bottom of the screen at every
    resolution — small enough to miss on a laptop, not on a TV.
    """
    frog = Frog(size)
    pad_h = lily_pad_sprite(frog.r).get_height()
    lowest = -1.0
    for _ in range(600):        # ten seconds, several full bob cycles
        frog.update(1 / 60)
        lowest = max(lowest, frog.pad.y + pad_h / 2)
    # Half a pixel of slack: pad_reach and _Pad.y share their constants, so the
    # sprite box lands on the last row exactly by construction, and the assert
    # would otherwise sit on a knife edge of float association. The drawn pad
    # keeps a real cushion — its ellipse stops at 0.95 of the sprite height.
    assert lowest <= size[1] + 0.5, (
        f"the pad reaches {lowest:.1f} on a {size[1]}px screen")
    assert lowest > size[1] - frog.r, "the pad is floating well clear of the bottom"


def test_the_pad_follows_him_but_not_instantly():
    """It drifts, because a pad that teleported would read as a bug."""
    frog = Frog(SIZE)
    for _ in range(240):
        frog.update(1 / 60)
    start = frog.pad.x
    frog.x = SIZE[0] * 0.9
    frog.update(1 / 60)
    moved = frog.pad.x - start
    assert 0 < moved < (SIZE[0] * 0.9 - start), "pad snapped instead of drifting"
    for _ in range(300):
        frog.update(1 / 60)
    assert frog.pad.x == pytest.approx(frog.x, abs=frog.r * 0.5)


def test_the_pad_bobs():
    frog = Frog(SIZE)
    ys = set()
    for _ in range(200):
        frog.update(1 / 60)
        ys.add(round(frog.pad.y, 2))
    assert len(ys) > 5, "the pad is sitting perfectly still on water"


# ------------------------------------------------------------- behaviour kept
def test_shoving_still_launches_him():
    frog = Frog(SIZE)
    for _ in range(120):
        frog.update(1 / 60)
    resting = frog.y
    frog.shove((0, -1))
    for _ in range(6):
        frog.update(1 / 60)
    assert frog.y < resting


def test_he_stays_inside_the_screen_however_hard_he_is_shoved():
    frog = Frog(SIZE)
    for i in range(600):
        if i % 20 == 0:
            frog.shove((1 if i % 40 else -1, -1))
        frog.update(1 / 60)
        assert 0 <= frog.x <= SIZE[0]
        assert 0 <= frog.y <= SIZE[1]


def test_a_landing_squashes_him_and_a_rest_does_not():
    """He re-enters the floor by a sub-pixel every frame under gravity; if that
    counted as a landing he would sit there squashed forever, raining ripples."""
    frog = Frog(SIZE)
    for _ in range(300):
        frog.update(1 / 60)
    assert frog.just_bounced is False
    assert frog.squash == pytest.approx(0.0)

    frog.shove((0, -1))
    landed = False
    for _ in range(240):
        frog.update(1 / 60)
        landed = landed or frog.just_bounced
    assert landed, "he never came down"


def test_drawing_paints_both_him_and_his_pad():
    frog = Frog(SIZE)
    for _ in range(240):
        frog.update(1 / 60)
    surf = pygame.Surface(SIZE)
    surf.fill((0, 0, 0))
    frog.draw(surf)

    def painted(y):
        return sum(1 for x in range(0, SIZE[0], 2) if surf.get_at((x, y))[:3] != (0, 0, 0))

    assert painted(int(frog.y)) > 0, "no frog"
    assert painted(int(frog.pad.y)) > 0, "no pad"


def test_drawing_while_squashed_does_not_crash():
    frog = Frog(SIZE)
    frog.squash = 1.0
    surf = pygame.Surface(SIZE)
    frog.draw(surf)


def test_landing_on_his_pad_still_makes_a_splash():
    """Hard-coding the bottom of the screen there is what broke the splash when
    his resting height moved: he lands on the pad, well above the last row of
    pixels, so a check against the screen bottom silently never fires.

    Behavioural rather than a grep of the engine source, so it also survives the
    check being rewritten — what matters is the ripple, not the expression.
    """
    from lilypad.effects.engine import EffectEngine
    from lilypad.effects.particles import Rings

    eng = EffectEngine(SIZE, sleep_timeout=0.0)
    for _ in range(240):                    # let him settle on the pad
        eng.update(1 / 60, now=0.0)
    eng.effects.clear()

    eng.frog.vy = -eng.frog.hop_impulse     # a real hop, not a resting jitter
    for _ in range(180):
        eng.update(1 / 60, now=0.0)
        if any(isinstance(e, Rings) for e in eng.effects):
            break
    else:
        pytest.fail("he landed back on his pad and made no ripples")


# --------------------------------------------------------------------------
# Resting — the frame-rate bug
# --------------------------------------------------------------------------

@pytest.mark.parametrize("fps", [60, 45, 37, 30, 20, 10])
def test_he_sits_still_at_every_frame_rate(fps):
    """A sitting frog must not register a landing every frame.

    Gravity adds ``h * GRAVITY * dt`` per frame, so the old fixed
    ``impact < 40`` threshold was only true above ~37 fps at 1080p. Below that
    a frog doing nothing at all squashed and spawned ripples on every single
    frame — and those are exactly the frame rates a loaded Pi drops to, which
    is where it is most visible and least excusable.
    """
    frog = Frog((1920, 1080))
    dt = 1.0 / fps
    for _ in range(fps * 3):            # let him settle
        frog.update(dt)
    assert frog.resting

    for _ in range(fps * 3):
        frog.update(dt)
        assert not frog.just_bounced, f"phantom landing at {fps} fps"
        assert frog.squash == 0.0, f"phantom squash at {fps} fps"


@pytest.mark.parametrize("fps", [60, 30, 10])
def test_a_real_hop_still_bounces(fps):
    """The rest test must not be so loose that genuine landings stop counting."""
    frog = Frog((1920, 1080))
    dt = 1.0 / fps
    for _ in range(fps * 3):
        frog.update(dt)

    frog.vy = -frog.hop_impulse
    for _ in range(fps * 4):
        frog.update(dt)
        if frog.just_bounced:
            return
    pytest.fail(f"a full-impulse hop never landed at {fps} fps")


def test_resting_frog_holds_one_position():
    frog = Frog(SIZE)
    for _ in range(300):
        frog.update(1 / 60)
    ys, xs = [], []
    for _ in range(120):
        frog.update(1 / 60)
        ys.append(frog.y)
        xs.append(frog.x)
    assert max(ys) - min(ys) == 0.0
    assert max(xs) - min(xs) == 0.0


def test_sideways_drift_actually_stops():
    """Exponential drag never reaches zero, so without a floor Pip slides a
    fraction of a pixel sideways forever and the pad chases him all day."""
    frog = Frog(SIZE)
    frog.shove((1, 0))
    for _ in range(60 * 20):
        frog.update(1 / 60)
    assert frog.vx == 0.0
    assert frog.resting


def test_a_resting_frog_rides_the_pad():
    """He floats *with* the pad rather than hovering while it slides through
    his feet — which is what made sitting still look glitchy."""
    frog = Frog(SIZE)
    for _ in range(300):
        frog.update(1 / 60)
    assert frog.resting

    drawn = []
    for _ in range(240):
        frog.update(1 / 60)
        drawn.append(frog.y + frog.pad.bob)
    # frog.y itself never moves; the drawn height varies by the bob alone.
    assert max(drawn) - min(drawn) > 1.0


def test_in_flight_he_ignores_the_pad_bob():
    frog = Frog(SIZE)
    for _ in range(300):
        frog.update(1 / 60)
    frog.shove((0, -1))
    frog.update(1 / 60)
    assert not frog.resting
