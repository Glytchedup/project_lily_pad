import hashlib
import math
import random
import tomllib
import weakref
from threading import Event

import pygame
import pytest

from lilypad.config import SceneConfig
from lilypad.effects import assets, scenery
from lilypad.effects.base import EffectContext
from lilypad.effects.scenery import PondBackground

SENTINEL = (1, 2, 3)


def ctx(size=(640, 480), seed=1234):
    return EffectContext(size=size, rng=random.Random(seed))


def test_construction_at_a_couple_sizes():
    for size in ((640, 480), (1280, 720)):
        pond = PondBackground(ctx(size=size))
        assert len(pond) > 0


def test_update_always_true():
    pond = PondBackground(ctx())
    for _ in range(10):
        assert pond.update(1 / 60) is True


def test_draw_fills_screen_opaquely():
    size = (640, 480)
    pond = PondBackground(ctx(size=size))
    surface = pygame.Surface(size)
    surface.fill(SENTINEL)
    pond.draw(surface)
    w, h = size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for corner in corners:
        assert surface.get_at(corner)[:3] != SENTINEL


def test_variant_crossfade_executes_without_crash():
    size = (320, 240)
    pond = PondBackground(ctx(size=size))
    surface = pygame.Surface(size)

    # Cross the 300s variant-cycle threshold in small steps so the
    # mid-crossfade draw path (extra alpha-blended blit) actually runs.
    for _ in range(310):
        pond.update(1.0)
        pond.draw(surface)

    # And a big single dt that jumps straight through a whole crossfade.
    pond.update(500.0)
    pond.draw(surface)


def test_len_positive():
    pond = PondBackground(ctx())
    assert len(pond) > 0


def test_deterministic_star_layout_with_seeded_rng():
    pond_a = PondBackground(ctx(seed=42))
    pond_b = PondBackground(ctx(seed=42))

    assert pond_a._sky == pond_b._sky
    assert pond_a._lily_pads == pond_b._lily_pads


def test_different_seed_gives_different_star_layout():
    pond_a = PondBackground(ctx(seed=1))
    pond_b = PondBackground(ctx(seed=2))
    assert pond_a._sky["stars"] != pond_b._sky["stars"]


def make_art(root, count=3):
    world = root / "world"
    world.mkdir()
    rows = []
    for index in reversed(range(count)):  # playback follows order, not TOML insertion
        plate = pygame.Surface((100, 50))
        plate.fill((10 + 20 * index, 10, 20))
        plate.set_at((50, 6), (160, 160, 160))  # a single registered moon
        plate.set_at((0, 36), (67, 66, 65))  # marker for plate shake
        pygame.image.save(plate, world / f"plate{index}.png")
        for name, height in (("far", 15), ("near", 11)):
            strip = pygame.Surface((104, height), pygame.SRCALPHA)
            for x in range(104):
                color = (x, 50 + 40 * index, 100, 255 if name == "far" else 128)
                pygame.draw.line(strip, color, (x, 0), (x, height - 1))
            pygame.image.save(strip, world / f"{name}{index}.png")
        rows.append(f'[moods.m{index}]\norder={index}\nplate="plate{index}.png"\n'
                    f'far_shore="far{index}.png"\nnear_water="near{index}.png"\n')
    (world / "manifest.toml").write_text("\n".join(rows), encoding="utf-8")
    return root


def painted(root, *, seed=42, size=(100, 50), **options):
    scene = SceneConfig(**{"fireflies": False, **options})
    return PondBackground(ctx(size, seed), scene, root=root)


def render(pond):
    surface = pygame.Surface(pond.ctx.size)
    surface.fill((255, 0, 255))
    pond.draw(surface)
    return surface


def rgb(surface):
    return pygame.image.tobytes(surface, "RGB")


@pytest.mark.parametrize("route", ["drawn", "missing", "empty", "broken"])
def test_fallback_matches_main_frames_and_rng(tmp_path, route):
    if route == "drawn":
        make_art(tmp_path)
    elif route in ("empty", "broken"):
        make_art(tmp_path, count=0 if route == "empty" else 1)
        if route == "broken":
            (tmp_path / "world/near0.png").write_bytes(b"bad image")
    scene = SceneConfig(world="drawn" if route == "drawn" else "painted")
    context = ctx((320, 240), 42)
    pond = PondBackground(context, scene, root=tmp_path)
    assert not pond.painted
    pond.shake(6, .5)
    pond.attract(10, 10)
    pond.set_card(pygame.Surface((1, 1)))
    # RGB digests from main e98b755, covering the two sides and midpoint of the fade.
    for dt, expected in (
        (1.25, "998ea5b258214b0c5c4cf9ea5ea0fdfe82bd5626ed38bc02c6ed33b66cd0400b"),
        (297.75, "762990084b49eafca3ed2585015e14f5551af881b7c1da289306bfcd0fd601d1"),
        (1, "59cd98b3cc3447c4720af35be13cf06e57eff5ff668de3799cb974a0f2f5f091"),
        (1, "d5ee4cc817e20fb9ee43aa9c0da43eeeba61c7eabe7b7490ed7ffbfa4c904356"),
        (2, "7575c2c02dd81d89d73b4ffd7e78eae0cf71926af0bbce5deb45818c7c85a51b"),
    ):
        pond.update(dt)
        image = render(pond)
        pond.draw_near_water(image)
        assert hashlib.sha256(rgb(image)).hexdigest() == expected
    assert context.rng.random() == 0.8780095992040405


def test_offsets_and_wrapped_source_columns(tmp_path):
    root = make_art(tmp_path, 1)
    pond = painted(root)
    still = painted(root, parallax=False)
    # Sample positive and negative extremes at 10 Hz and after a long frame.
    seen = []
    for steps in (0, 121, 50, 191, 162):
        for _ in range(steps):
            previous = pond._painted.near_x
            pond.update(.1)
            assert abs(pond._painted.near_x - previous) <= 1
        still.update(steps * .1)
        world = pond._painted
        seen.append((world.far_x, world.near_x))
        assert type(world.far_x) is type(world.near_x) is int
        assert abs(world.far_x) <= 40 and abs(world.near_x) <= 70
        assert still._painted.far_x == still._painted.near_x == 0
        image = render(pond)
        lip = pygame.Surface(pond.ctx.size)
        pond.draw_near_water(lip)
        assert lip.get_at((50, 38))[:3] == (0, 0, 0)
        expected_lip = pygame.Surface((104, 11))
        expected_lip.blit(world.current.near, (0, 0))
        for x in range(100):
            assert image.get_at((x, 30)).r == (x + 2 - world.far_x) % 104
            assert lip.get_at((x, 45)) == expected_lip.get_at(((x + 2 - world.near_x) % 104, 6))
    assert min(x for x, _ in seen) == -40 and max(x for x, _ in seen) == 40
    assert min(x for _, x in seen) == -70 and max(x for _, x in seen) == 70
    previous = world.near_x
    pond.update(90.)
    assert abs(world.near_x - previous) <= 1


def test_mood_order_complete_composite_fade_and_two_residents(tmp_path, monkeypatch):
    root = make_art(tmp_path, 4)
    residents = weakref.WeakSet()
    original = scenery._Mood.__init__

    def track(mood, *args):
        assert len(residents) < 2
        original(mood, *args)
        residents.add(mood)

    monkeypatch.setattr(scenery._Mood, "__init__", track)
    pond = painted(root, mood_minutes=.25, parallax=False)
    world = pond._painted
    sky = pond._sky
    # An independently blended pair of fully rendered scenes validates even
    # the partially transparent water; compare below the animated twinkles.
    first = render(pond)
    for i in range(4):
        assert world.current.files.name == f"m{i}"
        assert world.next.files.name == f"m{(i + 1) % 4}"
        pond.update(17. if i == 0 else 13.)  # 15 s period, 2 s into a 4 s fade
        midpoint = render(pond)
        assert world.alpha == 128
        assert pond._sky is sky
        assert midpoint.get_at((50, 6)) == first.get_at((50, 6))
        # Exact cross-fade above a swimmer too, with the P3 call independent of P0.
        lip = pygame.Surface(pond.ctx.size)
        lip.fill((231, 54, 81))
        pond.draw_near_water(lip)
        expected_lip = pygame.Surface(pond.ctx.size)
        expected_lip.fill((231, 54, 81))
        incoming_lip = expected_lip.copy()
        expected_lip.blit(world.current.near, (-2, 39))
        incoming_lip.blit(world.next.near, (-2, 39))
        incoming_lip.set_alpha(128)
        expected_lip.blit(incoming_lip, (0, 0))
        assert rgb(lip) == rgb(expected_lip)
        pond.update(2.)
        world.pending.result(timeout=3)  # only the test waits for the background read
        pond.update(0.)
        final = render(pond)
        blended = first.copy()
        final.set_alpha(128)
        blended.blit(final, (0, 0))
        assert rgb(midpoint.subsurface((0, 30, 100, 20))) == rgb(blended.subsurface((0, 30, 100, 20)))
        first = final
        assert len(residents) == 2


def test_unready_or_broken_lookahead_never_blocks_play(tmp_path, monkeypatch):
    root = make_art(tmp_path, 4)
    pond = painted(root, mood_minutes=.25, parallax=False)
    load = assets.load_image
    started, release = Event(), Event()

    def slow_read(path):
        if path.name == "plate2.png":
            started.set()
            assert release.wait(3)
            raise pygame.error("damaged plate")
        return load(path)

    monkeypatch.setattr(assets, "load_image", slow_read)
    pond.update(19.)
    pending = pond._painted.pending
    try:
        assert started.wait(3)
        pond.ctx.scale = .5
        assert pond.update(30.) and not pending.done()
        assert render(pond).get_at((12, 36))[:3] == (30, 10, 20)
    finally:
        release.set()
        pending.result(timeout=3)
    pond.update(0.)
    assert pond._painted.next.files.name == "m3"
    pond.update(2.)
    assert render(pond).get_at((12, 36)).r == 50


def test_scaled_flat_fade_and_recovery_match_layers(tmp_path):
    root = make_art(tmp_path, 2)
    full = painted(root, size=(239, 133), mood_minutes=.05, parallax=False)
    flat = painted(root, size=(239, 133), mood_minutes=.05, parallax=False)
    flat.ctx.scale = .45
    for dt in (0., 4.5, 3., 10., 1.):
        full.update(dt)
        flat.update(dt)
        assert rgb(render(flat)) == rgb(render(full))
    flat.ctx.scale = .6
    flat.update(0)
    assert rgb(render(flat)) == rgb(render(full))


def test_fireflies_seed_attraction_and_release(tmp_path):
    root = make_art(tmp_path, 1)
    left, right = (painted(root, fireflies=True) for _ in range(2))
    different = painted(root, seed=7, fireflies=True)
    off = painted(root)
    assert len(left._flies.positions) == 24 and len(left._flies.frames) == 2
    assert left._flies.positions != different._flies.positions
    assert rgb(render(left)) != rgb(render(off))
    rng_state = off.ctx.rng.getstate()
    off.attract(50, 20)
    off.update(.25)
    assert off.ctx.rng.getstate() == rng_state and off._flies is None
    for pond in (left, right):
        pond.attract(5, 5)
        for _ in range(10):
            pond.update(.1)
    assert rgb(render(left)) == rgb(render(right))
    assert all(math.dist(p, (5, 5)) < 14 for p in left._flies.positions)
    left.attract(95, 45)
    for _ in range(20):
        left.update(.1)
    assert all(math.dist(p, (95, 45)) < 3 for p in left._flies.positions)
    left.update(5.)
    assert sum(math.dist(p, (95, 45)) > 15 for p in left._flies.positions) > 15


def test_shake_card_degrade_and_recovery(tmp_path, monkeypatch):
    root = make_art(tmp_path, 2)
    pond = painted(root, parallax=False)
    initial = render(pond)
    pond.shake(6, .5)
    assert render(pond).get_at((6, 36)) == initial.get_at((0, 36))
    pond.update(.5)
    assert render(pond).get_at((0, 36)) == initial.get_at((0, 36))
    # The engine changes ctx.scale at runtime. Equality stays at full detail.
    pond.ctx.scale = .6
    pond.update(0)
    assert not pond._painted.flat
    pond.ctx.scale = .59
    pond.update(0)
    baked = render(pond)
    assert rgb(baked.subsurface((0, 30, 100, 20))) == rgb(initial.subsurface((0, 30, 100, 20)))
    card = pygame.Surface((20, 10))
    card.fill((28, 62, 91))
    pond.set_card(card)
    saved = rgb(card)
    with monkeypatch.context() as guard:
        def unexpected(*args):
            pytest.fail("steady degraded frames should only blit the cached flat plate")
        guard.setattr(scenery._Mood, "draw_strips", unexpected)
        guard.setattr(pygame.transform, "smoothscale", unexpected)
        guard.setattr(assets, "load_image", unexpected)
        for _ in range(3):
            pond.update(.1)
            image = render(pond)
            assert image.get_at((12, 36))[:3] == (28, 62, 91)
            assert image.get_at((12, 30)) == initial.get_at((12, 30))
            before = rgb(image)
            pond.draw_near_water(image)
            assert rgb(image) == before
    pond.set_card(None)
    assert render(pond).get_at((12, 36)) == initial.get_at((12, 36))
    pond.ctx.scale = 1.
    pond.update(0)
    lip = pygame.Surface(pond.ctx.size)
    pond.draw_near_water(lip)
    assert lip.get_at((12, 45))[:3] != (0, 0, 0)
    assert rgb(render(pond).subsurface((0, 30, 100, 20))) == rgb(initial.subsurface((0, 30, 100, 20)))
    pond.set_card(card)
    assert render(pond).get_at((12, 36))[:3] == (28, 62, 91)
    pond.set_card(None)
    assert rgb(card) == saved


def plate_meets_value_budget(surface):
    # SDL's inclusive RGB threshold counts pixels where ALL channels are <= 70.
    dark = pygame.transform.threshold(None, surface, (0, 0, 0), (70, 70, 70, 255),
                                      set_behavior=0)
    pixels = surface.get_width() * surface.get_height()
    return (pixels - dark) * 200 <= pixels


def test_plate_value_budget_allows_exactly_half_a_percent():
    plate = pygame.Surface((20, 10))
    plate.fill((70, 0, 0))
    plate.set_at((0, 0), (0, 0, 255))
    assert plate_meets_value_budget(plate)
    plate.set_at((1, 0), (0, 71, 0))
    assert not plate_meets_value_budget(plate)


def test_shipped_plate_values():
    directory = assets.asset_root(kiosk=True) / "world"
    with (directory / "manifest.toml").open("rb") as stream:
        moods = tomllib.load(stream).get("moods", {})
    if not moods:
        pytest.skip("no painted world plates have shipped")
    for name, mood in moods.items():
        plate = assets.load_image(directory / mood["plate"])
        assert plate.get_size() == (1920, 1080), name
        assert pygame.mask.from_surface(plate, threshold=254).count() == 1920 * 1080, name
        assert plate_meets_value_budget(plate), name
