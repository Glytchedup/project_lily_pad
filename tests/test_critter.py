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


def test_a_big_hop_settles_quickly_instead_of_shaking_for_seconds():
    """A high-restitution bounce decays slowly — 8 re-triggering landings over
    2.5s for a single shove, each one re-flashing squash and spawning another
    ripple, so he visibly kept shaking with rings piling up well after he'd
    actually stopped moving. He should be done settling in well under a
    second and a handful of bounces, not a dozen."""
    frog = Frog(SIZE)
    for _ in range(120):
        frog.update(1 / 60)
    frog.shove((1, -1))

    bounces = []
    t = 0.0
    dt = 1 / 60
    for _ in range(400):
        frog.update(dt)
        t += dt
        if frog.just_bounced:
            bounces.append(t)

    assert bounces, "he never came down"
    settle_span = bounces[-1] - bounces[0]
    assert settle_span < 1.5, f"took {settle_span:.2f}s from first landing to rest"
    assert len(bounces) <= 5, f"{len(bounces)} separate landings for one hop"


def test_resting_does_not_phantom_bounce_at_low_framerate():
    """The old settle cutoff was a fixed 40px/s velocity, but gravity alone
    adds dt * h * 1.4 to vy every frame — on real hardware that drops under
    load (confirmed on the Pi 3 test board), that crossed 40 on *every*
    frame while sitting perfectly still, not just occasionally: a permanent
    phantom bounce, re-flashing squash and spawning a fresh ripple forever,
    so he never actually looked like he'd stopped moving."""
    frog = Frog(SIZE)
    for _ in range(120):
        frog.update(1 / 60)          # settle at a normal frame rate first
    assert frog.just_bounced is False

    phantom_bounces = 0
    for _ in range(60):
        frog.update(1 / 20)          # simulate a sustained frame-rate dip
        if frog.just_bounced:
            phantom_bounces += 1
    assert phantom_bounces == 0, (
        f"{phantom_bounces}/60 frames falsely counted as landings while resting"
    )


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


# ------------------------------------------------------------ painted route
PIP_COLOURS = {"idle": (200, 0, 0), "blink": (0, 200, 0), "cheer": (0, 0, 200),
               "eyes_white": (250, 250, 250)}
PAD_COLOUR = (200, 200, 0)
PIP_NATIVE = (40, 50)       # canvas w, h
PAD_NATIVE = (60, 20)


def write_art(root, *, frames=("idle", "blink", "cheer", "eyes_white"), pip=True, pad=True):
    """A synthetic ``painted/`` directory of flat opaque frames."""
    directory = root / "painted"
    directory.mkdir(exist_ok=True)
    text = "schema = 1\n"
    if pip:
        for pose in frames:
            image = pygame.Surface(PIP_NATIVE, pygame.SRCALPHA)
            image.fill((*PIP_COLOURS[pose], 255))
            (directory / "pip").mkdir(exist_ok=True)
            pygame.image.save(image, directory / "pip" / f"{pose}.png")
        listing = ", ".join(f'{p} = "pip/{p}.png"' for p in frames)
        text += (f"[pip]\nnative_height = {PIP_NATIVE[1]}\nframes = {{ {listing} }}\n"
                 'anchor = [0.5, 1.0]\neye_at = [0.33, 0.22]\n')
    if pad:
        image = pygame.Surface(PAD_NATIVE, pygame.SRCALPHA)
        image.fill((*PAD_COLOUR, 255))
        (directory / "pip").mkdir(exist_ok=True)
        pygame.image.save(image, directory / "pip" / "pad.png")
        text += f'[pad]\nfile = "pip/pad.png"\nnative_height = {PAD_NATIVE[1]}\n'
    (directory / "manifest.toml").write_text(text, encoding="utf-8")


@pytest.fixture
def painted_pip(tmp_path, monkeypatch):
    monkeypatch.setenv("LILYPAD_ART_DIR", str(tmp_path))
    write_art(tmp_path)
    critter.set_pip_art("painted")
    yield tmp_path
    critter.set_pip_art("drawn")


def centre(surface):
    return tuple(surface.get_at((surface.get_width() // 2, surface.get_height() // 2)))[:3]


def settled(size=SIZE):
    frog = Frog(size)
    for _ in range(300):
        frog.update(1 / 60)
    frog.squash = 0.0
    return frog


def test_default_route_is_the_drawn_pip_with_nothing_to_load():
    assert critter.painted_pip_active() is False
    assert frog_sprite(40, "cheer") is frog_sprite(40, "idle")      # unknown pose -> idle


def test_painted_poses_fill_the_drawn_box_and_share_the_cache(painted_pip):
    idle = frog_sprite(40, "idle")
    assert idle.get_height() == int(40 * 3.0)
    assert idle.get_width() == round(PIP_NATIVE[0] * idle.get_height() / PIP_NATIVE[1])
    for pose, colour in PIP_COLOURS.items():
        sprite = frog_sprite(40, pose)
        assert centre(sprite) == colour
        assert frog_sprite(40, pose) is sprite
    assert frog_sprite(41, "idle") is not idle
    assert critter._sprite_cache[(40, "idle")] is idle      # the same (radius, pose) cache


def test_switching_back_to_drawn_drops_the_painted_sprites(painted_pip):
    painted = frog_sprite(40, "idle")
    critter.set_pip_art("drawn")
    drawn = frog_sprite(40, "idle")
    assert drawn is not painted
    assert drawn.get_size() == (int(40 * 3.4), int(40 * 3.0))
    assert centre(drawn) != PIP_COLOURS["idle"]


def test_optional_frames_alias_idle_before_the_cache_key(tmp_path, monkeypatch):
    monkeypatch.setenv("LILYPAD_ART_DIR", str(tmp_path))
    write_art(tmp_path, frames=("idle", "blink"))
    critter.set_pip_art("painted")
    try:
        assert frog_sprite(40, "cheer") is frog_sprite(40, "idle")
        assert frog_sprite(40, "eyes_white") is frog_sprite(40, "idle")
        assert (40, "cheer") not in critter._sprite_cache
        frog = settled()
        frog.dance(True)
        assert frog.pose == "cheer"               # asks for it; the sprite is idle
        frog.dance(False)
        frog.look(1, 0)
        surf = pygame.Surface(SIZE)
        frog.draw(surf)                           # no eyes_white frame: no pupils, no crash
    finally:
        critter.set_pip_art("drawn")


@pytest.mark.parametrize("problem", ["no manifest rows", "missing file", "wrong canvas"])
def test_missing_or_bad_art_draws_pip_and_logs_once(tmp_path, monkeypatch, caplog, problem):
    monkeypatch.setenv("LILYPAD_ART_DIR", str(tmp_path))
    if problem == "no manifest rows":
        (tmp_path / "painted").mkdir()
        (tmp_path / "painted" / "manifest.toml").write_text("schema = 1\n", encoding="utf-8")
    else:
        write_art(tmp_path)
        if problem == "missing file":
            (tmp_path / "painted" / "pip" / "blink.png").unlink()
            (tmp_path / "painted" / "pip" / "pad.png").unlink()
        else:
            odd = pygame.Surface((10, 10), pygame.SRCALPHA)
            pygame.image.save(odd, tmp_path / "painted" / "pip" / "cheer.png")
            pygame.image.save(odd, tmp_path / "painted" / "pip" / "pad.png")
    caplog.set_level("INFO", logger="lilypad.effects.critter")
    critter.set_pip_art("painted")
    try:
        for _ in range(3):
            sprite = frog_sprite(40, "idle")
            lily_pad_sprite(40)
        assert sprite.get_size() == (int(40 * 3.4), int(40 * 3.0))      # the drawn one
        assert critter.painted_pip_active() is False
        assert len([r for r in caplog.records if "Pip" in r.message or "[pip]" in r.message]) == 1
        assert len([r for r in caplog.records if "pad" in r.message]) == 1
        assert lily_pad_sprite(40).get_width() == int(40 * 4.6)
    finally:
        critter.set_pip_art("drawn")


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        critter.set_pip_art("watercolour")


def test_painted_pad_goes_through_lily_pad_sprite_and_pad_reach_measures_it(painted_pip):
    frog = settled()
    pad = lily_pad_sprite(frog.r)
    assert centre(pad) == PAD_COLOUR
    assert pad.get_height() == int(frog.r * 1.40)
    assert pad.get_width() == round(PAD_NATIVE[0] * pad.get_height() / PAD_NATIVE[1])
    assert pad.get_width() != int(frog.r * 4.6)         # its own shape, not the drawn ellipse
    reach = critter.pad_reach(frog.r)
    assert reach == pytest.approx(pad.get_height() * (critter._PAD_SINK + 0.5)
                                  + frog.r * critter._PAD_BOB)
    assert frog.floor_y == pytest.approx(SIZE[1] - reach - frog._feet)
    surf = pygame.Surface(SIZE)
    frog.draw(surf)
    assert tuple(surf.get_at((int(frog.pad.x) - pad.get_width() // 2 + 3,
                              int(frog.pad.y))))[:3] == PAD_COLOUR


def test_painted_pip_leaves_physics_and_floor_untouched(painted_pip):
    painted = settled()
    critter.set_pip_art("drawn")
    drawn = settled()
    assert (painted.r, painted.floor_y, painted.hop_impulse) == (
        drawn.r, drawn.floor_y, drawn.hop_impulse)
    assert (painted.x, painted.y) == pytest.approx((drawn.x, drawn.y))


def test_cheer_during_the_party_dance_and_celebrations(painted_pip):
    frog = settled()
    assert frog.pose == "idle"
    frog.dance(True)
    assert frog.pose == "cheer"
    frog.age = 3.9                                  # a blink never interrupts the cheer
    assert frog.pose == "cheer"
    frog.dance(False)
    assert frog.pose == "blink"
    frog.age = 100.0
    frog.celebrate(2.0)
    assert frog.pose == "cheer"
    frog.age += 2.5
    assert frog.pose == "idle"
    surf = pygame.Surface(SIZE)
    frog.dance(True)
    frog.draw(surf)
    top = frog.y + frog._feet - int(frog.r * 3.0)
    assert tuple(surf.get_at((int(frog.x), int(top) + 20)))[:3] == PIP_COLOURS["cheer"]


def test_the_engine_runs_a_party_with_painted_pip(painted_pip):
    from lilypad.effects.engine import EffectEngine

    eng = EffectEngine(SIZE, sleep_timeout=0.0)
    assert critter.painted_pip_active()
    surf = pygame.Surface(SIZE)
    eng.start_party()
    for i in range(120):
        eng.update(1 / 60, now=float(i) / 60)
        eng.draw(surf)
    assert eng.frog.pose == "cheer"
    eng.end_party(2.0)
    for i in range(30):
        eng.update(1 / 60, now=3.0 + i / 60)
        eng.draw(surf)


def test_drawn_pip_never_cheers_or_looks_around():
    frog = settled()
    frog.dance(True)
    frog.look(1, 1)
    assert frog.pose == "idle"
    frog.age = 3.9
    assert frog.pose == "blink"


def test_pupils_are_two_discs_on_the_eyes_white_frame(painted_pip):
    frog = settled()
    frog.look(0.5, -0.5)
    assert frog.pose == "eyes_white"
    surf = pygame.Surface(SIZE)
    frog.draw(surf)
    sprite = frog_sprite(frog.r, "eyes_white")
    rect = sprite.get_rect(midbottom=(int(frog.x), int(frog.y + frog._feet)))
    travel = frog.r * critter._PUPIL_TRAVEL
    dark = []
    for fx in (0.33, 1 - 0.33):
        spot = (round(rect.x + fx * rect.w + 0.5 * travel),
                round(rect.y + 0.22 * rect.h - 0.5 * travel))
        assert tuple(surf.get_at(spot))[:3] == critter.PUPIL
        dark.append(spot)
    assert dark[0][0] < frog.x < dark[1][0]             # one pupil per side of the face
    frog.look(None)
    assert frog.pose == "idle"
    frog.look(9, -9)
    assert frog.gaze == (1.0, -1.0)                     # clamped


@pytest.mark.parametrize("end", ["deadline", "despawn", "timeout", "offscreen"])
def test_ride_tracks_moving_feet_then_hops_home(end, painted_pip):
    frog = settled()
    start = frog.age
    anchor = [360, 190]
    frog.ride(lambda: anchor, until=start + (0.5 if end == "deadline" else 80))
    assert frog.riding
    for _ in range(10):
        anchor[0] += 2
        anchor[1] += 1
        frog.update(0.025)
        assert (frog.x, frog.y + frog._feet) == pytest.approx(anchor)
        assert not frog.just_bounced
    if end == "despawn":
        anchor = None
    elif end == "offscreen":
        anchor[0] = -200
    else:
        duration = 0.5 if end == "deadline" else 8.0
        while frog.age + 0.01 < start + duration:
            frog.update(0.01)
            assert frog.riding
    frog.update(0.011)
    assert not frog.riding
    assert frog.vy < 0
    for _ in range(300):
        frog.update(1 / 60)
        assert frog.r <= frog.x <= frog.w - frog.r
    assert frog.y == frog.floor_y and frog.vy == 0
    assert abs(frog.pad.x - frog.x) < 1


@pytest.mark.parametrize("direction", [(1, 0), (-1, 0), (0, 1), (0, -1)])
def test_arrow_cancels_ride_in_the_input_frame(direction, painted_pip):
    from lilypad.effects.engine import EffectEngine
    from lilypad.input.mapper import Action

    engine = EffectEngine(SIZE)
    frog = engine.frog
    frog.ride(lambda: (400, 150), until=frog.age + 2)
    frog.update(1 / 60)
    engine.spawn(Action("arrow", direction=direction), now=0)
    assert not frog.riding
    frog.cancel_ride()  # also safe for an explicit call in the input handler
    frog.update(1 / 60)
    assert (frog.x - 400) * direction[0] + (frog.y + frog._feet - 150) * direction[1] > 0


def test_duck_lowers_painted_head_but_keeps_feet_on_pad_and_expires(painted_pip):
    frog = settled()

    def top():
        frame = pygame.Surface(SIZE, pygame.SRCALPHA)
        frog.draw(frame)
        return frame.get_bounding_rect().top

    standing = top()
    frog.duck(0.4)
    frog.update(0.39)
    assert top() - standing > frog.r
    assert frog.floor_y == frog.y
    frog.update(0.02)
    assert top() == standing
    frog.duck(100)
    for _ in range(180):
        frog.update(1 / 60)
    assert top() == standing


def test_look_at_aims_the_pupils_in_screen_space_and_expires(painted_pip):
    frog = settled()
    frog.look_at(frog.x - 200, frog.y + 100)
    assert frog.pose == "eyes_white"
    assert frog.gaze[0] < 0 < frog.gaze[1]
    for _ in range(180):
        frog.update(1 / 60)
    assert frog.gaze is None


def test_ride_puts_visible_padded_feet_on_back(painted_pip):
    from lilypad.effects.engine import EffectEngine

    # Bottom five native rows are empty, as on a registered pose canvas.
    idle = pygame.Surface(PIP_NATIVE, pygame.SRCALPHA)
    idle.fill((*PIP_COLOURS["idle"], 255), (0, 0, PIP_NATIVE[0], 45))
    pygame.image.save(idle, painted_pip / "painted/pip/idle.png")
    critter.set_pip_art("painted")
    frog = EffectEngine(SIZE).frog
    frog.ride(lambda: (480, 170), until=2)
    frog.update(0.1)
    screen = pygame.Surface(SIZE, pygame.SRCALPHA)
    frog.draw(screen)
    # Up to one scaled antialiasing pixel at the sole.
    visible = screen.subsurface((0, 0, SIZE[0], 220)).get_bounding_rect()
    assert visible.bottom == pytest.approx(170, abs=1)


def test_painted_wave_raises_arms_twice_then_relaxes_on_the_pad(painted_pip):
    frog = settled()
    frog.wave()
    poses = []
    for _ in range(6):
        poses.append(frog.pose)
        frog.update(0.15)
    assert poses[:5] == ["cheer", "idle", "cheer", "idle", "idle"]
    assert frog.y == frog.floor_y and frog.vy == 0


def test_drawn_wave_moves_a_foreleg_and_reuses_its_sprite():
    frog = settled()
    idle = frog_sprite(frog.r)
    frog.wave()
    lifted = frog_sprite(frog.r, frog.pose)
    assert lifted is not idle
    assert lifted.get_at((int(lifted.get_width() * 0.90), lifted.get_height() // 2)).a > 0
    assert idle.get_at((int(idle.get_width() * 0.90), idle.get_height() // 2)).a == 0
    frog.update(0.30)
    assert frog_sprite(frog.r, frog.pose) is lifted
    frog.update(0.5)
    assert frog_sprite(frog.r, frog.pose) is idle


@pytest.mark.parametrize("steps", [(1/24,), (1/60,), (1/24, 1/72, 1/38, 1/60)])
def test_dance_lands_on_mapped_beats_with_an_irregular_tempo_and_lead_in(steps):
    from lilypad.audio.tracks import BeatClock, BeatMap

    beats = (2.80, 3.24, 4.12, 4.53, 5.18, 5.70)
    clock = BeatClock(BeatMap(120, beats[0], beats, (beats[0],), ()))
    frog = settled()
    frog.dance(beat_clock=clock)
    landings = []
    frame, elapsed = 0, 0.0
    while elapsed < beats[-1] + 0.1:
        dt = steps[frame % len(steps)]
        elapsed += dt
        frame += 1
        was_above = frog.y < frog.floor_y
        clock.advance(dt)
        frog.update(dt)
        if was_above and frog.y == frog.floor_y:
            landings.append((elapsed, dt))
    assert len(landings) == len(beats)
    for (landing, dt), beat in zip(landings, beats):
        assert landing == pytest.approx(beat, abs=dt + 1e-9)
    frog.dance(False)
    for _ in range(240):
        frog.update(1 / 60)
    assert frog.y == frog.floor_y and frog.vy == 0
