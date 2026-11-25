"""Lily in the pond: synthetic manifests only, no real art."""

import itertools
import logging
import random

import pygame
import pytest

from lilypad.effects import critter
from lilypad.effects import lily as lily_module
from lilypad.effects.layout import CLASSIC, POND
from lilypad.effects.lily import (
    BLINK_EVERY,
    BLINK_SECONDS,
    FADE_SECONDS,
    WAVE_SECONDS,
    load_lily,
)

SIZE = (1280, 720)
NATIVE = 300
# pose -> (canvas size, colour). Heights follow the manifest's `heights` table.
CANVAS = {
    "sit": ((100, 234), (200, 30, 30)),
    "sit_blink": ((100, 234), (200, 30, 31)),
    "wave": ((130, 300), (30, 200, 30)),
    "tummy": ((220, 165), (30, 30, 200)),
    "point": ((110, 300), (200, 200, 30)),
    "cheer": ((130, 300), (30, 200, 200)),
}


def make_art(root, *, skip=(), schema=1, lily=True, canvas=None, anchor="[0.5, 1.0]"):
    """Write a tiny [lily] manifest and its frames under root/painted/."""
    painted = root / "painted"
    (painted / "lily").mkdir(parents=True)
    files = []
    for pose, (size, colour) in {**CANVAS, **(canvas or {})}.items():
        art = pygame.Surface(size, pygame.SRCALPHA)
        art.fill((*colour, 255))
        if pose in ("point", "tummy"):   # asymmetric, so mirroring is observable
            art.fill((255, 0, 0, 255), (0, 0, size[0] // 2, size[1]))
            art.fill((0, 0, 255, 255), (size[0] // 2, 0, size[0] - size[0] // 2, size[1]))
        if pose not in skip:
            pygame.image.save(art, painted / "lily" / f"{pose}.png")
        files.append(f'{pose} = "lily/{pose}.png"')
    text = f"schema = {schema}\n"
    if lily:
        text += (f"[lily]\nnative_height = {NATIVE}\nanchor = {anchor}\n"
                 f"frames = {{ {', '.join(files)} }}\n"
                 "heights = { sit = 0.78, sit_blink = 0.78, wave = 1.0, tummy = 0.55,"
                 " point = 1.0, cheer = 1.0 }\n")
    (painted / "manifest.toml").write_text(text, encoding="utf-8")
    return root


def build(tmp_path, size=SIZE, **options):
    art = {k: options.pop(k) for k in ("canvas", "anchor") if k in options}
    return load_lily(make_art(tmp_path, **art), size, POND, **options)


def run(lily, seconds, dt=1 / 60):
    for _ in range(round(seconds / dt)):
        lily.update(dt)


def go_to(lily, name):
    lily.index = next(i for i, s in enumerate(lily.spots) if s.name == name)
    lily.phase, lily.phase_time, lily.move_time = "hold", 0.0, 0.0
    lily.wave_left = lily.cheer_left = lily.blink_left = 0.0


class Beat:
    def __init__(self, phase, index=0):
        self.beat_phase, self.beat_index = phase, index


def close(pixel, colour, tol=8):
    return all(abs(a - b) <= tol for a, b in zip(tuple(pixel)[:3], colour))


def pad_band_top(size):
    """Highest edge Pip's pad reaches while it drifts, from the real Frog."""
    frog = critter.Frog(size)
    height = critter.lily_pad_sprite(frog.r).get_height()
    return frog.pad.surface_y + height * critter._PAD_SINK - height / 2 - frog.r * critter._PAD_BOB


# -- loading -----------------------------------------------------------------

def test_loads_and_prescales_every_pose_once(tmp_path):
    lily = build(tmp_path)
    assert lily is not None and len(lily.spots) == 6
    assert {s.name for s in lily.spots} == {
        "far_shore_left", "far_shore_right", "bank_near_pip", "lily_pad",
        "tummy_on_bank", "under_the_moon"}
    for spot in lily.spots:
        standing = spot.poses["cheer"][0]
        assert abs(standing.get_height() - spot.size_px) <= 1
        # Poses keep one scale: a sitting pose is 0.78 of the standing height.
        if "sit" in spot.poses:
            assert abs(spot.poses["sit"][0].get_height() / standing.get_height() - 0.78) < 0.02
        assert 0.22 * SIZE[1] - 1 <= spot.size_px <= 0.28 * SIZE[1] + 1
        assert spot.size_px < 0.30 * SIZE[1]     # smaller than the crossing animals


def test_prescaled_surfaces_are_reused_not_rebuilt(tmp_path):
    lily = build(tmp_path)
    before = {(s.name, p): id(v[0]) for s in lily.spots for p, v in s.poses.items()}
    surface = pygame.Surface(SIZE)
    run(lily, 3)
    lily.draw(surface)
    assert before == {(s.name, p): id(v[0]) for s in lily.spots for p, v in s.poses.items()}


@pytest.mark.parametrize("variant", ["no_file", "bad_schema", "no_lily", "missing_frame"])
def test_missing_or_bad_art_gives_none_and_no_rng_draws(tmp_path, variant):
    if variant == "bad_schema":
        make_art(tmp_path, schema=2)
    elif variant == "no_lily":
        make_art(tmp_path, lily=False)
    elif variant == "missing_frame":
        make_art(tmp_path, skip=("cheer",))
    ctx_rng = random.Random(9)
    state, global_state = ctx_rng.getstate(), random.getstate()
    assert load_lily(tmp_path, SIZE, POND) is None
    assert ctx_rng.getstate() == state and random.getstate() == global_state


def test_classic_world_draws_nothing(tmp_path):
    make_art(tmp_path)
    assert load_lily(tmp_path, SIZE, CLASSIC) is None


def test_loading_and_running_never_touch_global_random(tmp_path):
    state = random.getstate()
    lily = build(tmp_path)
    surface = pygame.Surface(SIZE)
    for _ in range(600):
        lily.update(0.5)
        lily.draw(surface)
    assert random.getstate() == state


def test_bad_move_seconds_is_clamped_not_fatal(tmp_path):
    assert build(tmp_path, move_seconds=0.0).move_seconds >= 1.0


# -- placement ---------------------------------------------------------------

@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080), (1024, 600)])
def test_spots_clear_the_stage_pip_and_the_screen(tmp_path, size):
    lily = build(tmp_path / f"s{size[0]}", size)
    assert len(lily.spots) == 6
    w, h = size
    stage = pygame.Rect(0.30 * w, 0, 0.40 * w, h)
    frog = critter.Frog(size)
    pad = critter.lily_pad_sprite(frog.r).get_rect(center=(frog.pad.x, frog.pad.y))
    top = pad_band_top(size)
    for name, rect in lily.spot_rects.items():
        assert pygame.Rect(0, 0, w, h).contains(rect), name
        assert not rect.colliderect(stage), name
        assert not rect.colliderect(pad), name
        assert rect.bottom <= top, name      # clear wherever his pad drifts


def test_a_spot_that_would_cross_the_stage_is_dropped(tmp_path, caplog):
    # A very wide pose cannot fit beside the stage on a narrow screen.
    caplog.set_level(logging.INFO)
    lily = load_lily(make_art(tmp_path), (400, 720), POND)
    assert lily is None or all(
        not r.colliderect(pygame.Rect(120, 0, 160, 720)) for r in lily.spot_rects.values())


def test_mirroring_by_side_for_tummy_and_point(tmp_path):
    lily = build(tmp_path)
    by_name = {s.name: s for s in lily.spots}
    # Art faces right: left-side spots keep it (the moon is to the right of her),
    # right-side spots flip it so she faces the centre.
    moon = by_name["under_the_moon"].poses["point"][0]
    left, right = moon.get_at((2, 50)), moon.get_at((moon.get_width() - 3, 50))
    assert left.r > 240 and left.b < 15 and right.b > 240 and right.r < 15
    tummy = by_name["tummy_on_bank"].poses["tummy"][0]
    left, right = tummy.get_at((2, 20)), tummy.get_at((tummy.get_width() - 3, 20))
    assert left.b > 240 and left.r < 15 and right.r > 240 and right.b < 15
    keep = by_name["bank_near_pip"].poses["sit"][0]       # facing the viewer: never flipped
    assert close(keep.get_at((5, 5)), CANVAS["sit"][1])
    assert by_name["tummy_on_bank"].cx > SIZE[0] / 2 > by_name["under_the_moon"].cx


# -- schedule ----------------------------------------------------------------

def test_moves_on_schedule_to_a_different_spot_each_time(tmp_path):
    lily = build(tmp_path, move_seconds=10)
    seen, times, last = [lily.spot_name], [], lily.index
    for step in range(round(400 / 0.05)):
        lily.update(0.05)
        if lily.index != last:
            times.append(step * 0.05)
            seen.append(lily.spot_name)
            last = lily.index
    assert len(times) >= 15
    assert all(a != b for a, b in itertools.pairwise(seen))        # never the same twice in a row
    gaps = [b - a for a, b in itertools.pairwise(times)]
    # arrive (0.4) + wait (10) + fade out (0.4) between spot changes
    assert all(10.6 < g < 11.1 for g in gaps), gaps
    assert len(set(seen)) == 6


def test_fade_sequence_timing(tmp_path):
    lily = build(tmp_path, move_seconds=5)
    assert lily.phase == "in" and lily.alpha == 0
    lily.update(FADE_SECONDS / 2)
    assert lily.phase == "in" and 120 <= lily.alpha <= 135
    lily.update(FADE_SECONDS / 2 + 0.01)
    assert lily.phase == "hold" and lily.alpha == 255
    first = lily.index
    lily.update(4.9)
    assert lily.phase == "hold" and lily.index == first
    lily.update(0.2)
    assert lily.phase == "out"
    lily.update(FADE_SECONDS / 2)
    assert lily.phase == "out" and lily.index == first and 55 <= lily.alpha <= 140
    lily.update(FADE_SECONDS / 2 + 0.05)
    assert lily.phase == "in" and lily.index != first and lily.alpha < 128


def test_fading_blends_with_the_scene_and_hold_is_opaque(tmp_path):
    lily = build(tmp_path)
    go_to(lily, "far_shore_left")
    spot = lily.spot
    x, y = spot.poses["sit"][1]
    probe = (x + 40, y + 100)
    surface = pygame.Surface(SIZE)
    surface.fill((0, 0, 0))
    lily.draw(surface)
    assert close(surface.get_at(probe), CANVAS["sit"][1])
    lily.phase, lily.phase_time = "out", FADE_SECONDS / 2
    surface.fill((0, 0, 0))
    lily.draw(surface)
    assert 0 < surface.get_at(probe)[0] < CANVAS["sit"][1][0]
    assert spot.poses["sit"][0].get_alpha() == 255     # the shared cache stays untouched


def test_poof_sparkles_only_while_fading(tmp_path):
    lily = build(tmp_path)
    go_to(lily, "far_shore_left")
    calm, busy = pygame.Surface(SIZE), pygame.Surface(SIZE)
    for surface in (calm, busy):
        surface.fill((0, 0, 0))
    lily.draw(calm)
    lily.phase, lily.phase_time = "out", 0.05
    lily.draw(busy)
    spot = lily.spot
    ring = pygame.Rect(0, 0, spot.size_px * 2, spot.size_px * 2)
    ring.center = (spot.cx, spot.feet - spot.size_px // 2)
    ring = ring.clip(pygame.Rect(0, 0, *SIZE))
    assert (pygame.image.tobytes(calm.subsurface(ring), "RGB")
            != pygame.image.tobytes(busy.subsurface(ring), "RGB"))


# -- poses and reactions -----------------------------------------------------

def test_blink_cadence_on_a_sitting_spot(tmp_path):
    lily = build(tmp_path, move_seconds=1e6)
    go_to(lily, "far_shore_left")
    starts, was, now = [], False, 0.0
    held = []
    for _ in range(120 * 60):
        lily.update(1 / 60)
        now += 1 / 60
        blinking = lily.pose == "sit_blink"
        if blinking and not was:
            starts.append(now)
            held.append(0.0)
        if blinking:
            held[-1] += 1 / 60
        was = blinking
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert len(starts) >= 15
    assert all(BLINK_EVERY[0] - 0.05 <= g <= BLINK_EVERY[1] + 0.05 for g in gaps), gaps
    assert all(abs(h - BLINK_SECONDS) < 0.04 for h in held)


@pytest.mark.parametrize("name", ["tummy_on_bank", "under_the_moon"])
def test_no_blink_or_wave_on_tummy_and_point_spots(tmp_path, name):
    lily = build(tmp_path, move_seconds=1e6)
    go_to(lily, name)
    lily.on_animal_start()
    poses = set()
    for _ in range(60 * 30):
        lily.update(1 / 60)
        poses.add(lily.pose)
    assert poses == {lily.spot.base}


def test_waves_for_a_moment_when_an_animal_starts(tmp_path):
    lily = build(tmp_path, move_seconds=1e6)
    go_to(lily, "bank_near_pip")
    lily.update(0.01)
    assert lily.pose in ("sit", "sit_blink")
    lily.on_animal_start()
    lily.update(0.01)
    assert lily.pose == "wave"
    lily.update(WAVE_SECONDS - 0.1)
    assert lily.pose == "wave"
    lily.update(0.2)
    assert lily.pose in ("sit", "sit_blink")


def test_event_name_also_waves(tmp_path):
    lily = build(tmp_path, move_seconds=1e6)
    go_to(lily, "far_shore_right")
    lily.update(0.01, ["animal_start"])
    assert lily.pose == "wave"


def test_party_cheers_and_returns_to_rest(tmp_path):
    lily = build(tmp_path, move_seconds=1e6)
    go_to(lily, "far_shore_left")
    lily.set_party(True)
    lily.update(0.1)
    assert lily.pose == "cheer"
    lily.set_party(False)
    lily.update(0.1)
    assert lily.pose != "cheer"
    lily.cheer(1.0)                      # milestone / parade
    lily.update(0.5)
    assert lily.pose == "cheer"
    lily.update(0.6)
    assert lily.pose != "cheer"


def cheer_top(lily):
    """Row of the first coloured pixel while cheering, to measure the bob."""
    surface = pygame.Surface(SIZE)
    surface.fill((0, 0, 0))
    lily.draw(surface)
    x = lily.spot.cx
    column = [close(surface.get_at((x, y)), CANVAS["cheer"][1]) for y in range(SIZE[1])]
    return column.index(True)


def test_cheer_bobs_on_the_beat(tmp_path):
    lily = build(tmp_path, move_seconds=1e6)
    go_to(lily, "far_shore_left")
    rest = lily.spot.poses["cheer"][1][1]
    bob = lily._bob_px
    clock = Beat(0.0)
    lily.set_party(True, clock)
    lily.update(0.01)
    assert cheer_top(lily) == rest - bob          # up on the beat
    clock.beat_phase = 0.5
    assert rest - bob < cheer_top(lily) < rest
    clock.beat_phase = 0.999
    assert cheer_top(lily) == rest                # settled before the next one
    clock.beat_index = -1                         # lead-in: no bobbing yet
    clock.beat_phase = 0.0
    assert cheer_top(lily) == rest


def test_cheer_bobs_at_two_hertz_without_a_clock(tmp_path):
    lily = build(tmp_path, move_seconds=1e6)
    go_to(lily, "far_shore_left")
    rest = lily.spot.poses["cheer"][1][1]
    lily.set_party(True)
    tops = []
    for _ in range(60):
        lily.update(1 / 60)
        tops.append(cheer_top(lily))
    assert max(tops) == rest and min(tops) <= rest - lily._bob_px + 1
    up = [t <= rest - lily._bob_px * 2 // 3 for t in tops]
    bobs = sum(1 for k in range(len(up)) if up[k] and (k == 0 or not up[k - 1]))
    assert bobs == 2          # two bobs in one second

def test_only_integer_offsets(tmp_path):
    lily = build(tmp_path)
    lily.set_party(True, Beat(0.37))
    assert isinstance(lily._bob(), int)
    lily.set_party(True)
    lily.age = 0.123
    assert isinstance(lily._bob(), int)


# -- sleep -------------------------------------------------------------------

def test_asleep_is_not_drawn_and_time_stands_still(tmp_path):
    lily = build(tmp_path, move_seconds=5)
    run(lily, 1)
    surface = pygame.Surface(SIZE)
    surface.fill((7, 7, 7))
    lily.sleep()
    lily.draw(surface)
    assert pygame.image.tobytes(surface, "RGB") == pygame.image.tobytes(_filled(7), "RGB")
    spot, move_time = lily.index, lily.move_time
    run(lily, 60)
    assert lily.index == spot and lily.move_time == move_time
    lily.wake()
    assert lily.phase == "in" and lily.alpha == 0
    run(lily, 1)
    assert lily.alpha == 255 and not lily.asleep


def _filled(value):
    surface = pygame.Surface(SIZE)
    surface.fill((value,) * 3)
    return surface


def test_draw_is_deterministic_for_a_seed_and_differs_across_seeds(tmp_path):
    def trail(seed, root):
        lily = build(root, move_seconds=3, seed=seed)
        names = []
        for _ in range(400):
            lily.update(0.1)
            if not names or names[-1] != lily.spot_name:
                names.append(lily.spot_name)
        return names

    a = trail(5, tmp_path / "a")
    assert a == trail(5, tmp_path / "b")
    assert a != trail(6, tmp_path / "c")


def test_update_is_robust_to_bad_dt(tmp_path):
    lily = build(tmp_path)
    for dt in (0.0, -1.0, float("nan"), float("inf")):
        assert lily.update(dt) is True
    assert lily.update(500.0) is True      # one long hitch is one move, not a crash
    lily.draw(pygame.Surface(SIZE))


def test_module_exports_the_wiring_surface():
    for name in ("load_lily", "Lily", "POSES", "FADE_SECONDS"):
        assert hasattr(lily_module, name)
    for method in ("update", "draw", "on_animal_start", "set_party", "sleep", "wake", "cheer"):
        assert callable(getattr(lily_module.Lily, method))


# -- manifest honesty, wiring edge cases -------------------------------------

@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_spots_are_distinct_patches_of_screen_three_a_side(tmp_path, size):
    lily = build(tmp_path / str(size[0]), size)
    rects = lily.spot_rects
    assert len(rects) == 6
    for (a, ra), (b, rb) in itertools.combinations(rects.items(), 2):
        assert not ra.colliderect(rb), (a, b)
    centres = [s.cx for s in lily.spots]
    assert sum(c < size[0] / 2 for c in centres) == 3


def test_heights_table_wins_over_the_canvas_size(tmp_path):
    # A sit canvas twice as tall as the 0.78 the table promises is still 0.78 here.
    lily = build(tmp_path, canvas={"sit": ((200, 468), (200, 30, 30)),
                                   "sit_blink": ((200, 468), (200, 30, 31))})
    spot = next(s for s in lily.spots if s.base == "sit")
    assert abs(spot.poses["sit"][0].get_height() - round(spot.size_px * 0.78)) <= 1
    assert spot.poses["sit"][0].get_width() * 468 == pytest.approx(
        spot.poses["sit"][0].get_height() * 200, rel=0.02)    # aspect kept
    assert spot.poses["sit"][0].get_height() < spot.poses["cheer"][0].get_height()


def test_anchor_y_places_the_feet(tmp_path):
    flush = build(tmp_path / "a")
    lifted = build(tmp_path / "b", anchor="[0.5, 0.95]")
    for a, b in zip(flush.spots, lifted.spots, strict=True):
        art, (_, top_a) = a.poses["cheer"]
        art2, (_, top_b) = b.poses["cheer"]
        assert top_a + art.get_height() == a.feet                  # bottom row on the baseline
        assert top_b + round(0.95 * art2.get_height()) == b.feet    # alpha ends at 95% of canvas


def test_events_may_be_none_or_empty(tmp_path):
    lily = build(tmp_path)
    assert lily.update(0.1, None) is True
    assert lily.update(0.1, []) is True


def test_sleep_and_wake_keep_the_move_timer(tmp_path):
    lily = build(tmp_path, move_seconds=100)
    run(lily, 40)
    waited = lily.move_time
    assert 38 < waited < 41
    lily.sleep()
    lily.wake()
    run(lily, 1)
    assert lily.phase == "hold" and lily.move_time > waited


def test_one_huge_hitch_is_one_move_not_two(tmp_path):
    lily = build(tmp_path, move_seconds=10)
    run(lily, 1)
    start = lily.index
    lily.update(500.0)
    lily.update(1 / 60)
    lily.update(1 / 60)
    assert lily.phase == "out" or lily.phase == "in"
    for _ in range(60):
        lily.update(1 / 60)
    assert lily.index != start
    second = lily.index
    run(lily, 2)
    assert lily.index == second     # not hopping straight on again
