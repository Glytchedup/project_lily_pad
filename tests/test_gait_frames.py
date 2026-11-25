"""Per-gait frame schedules, the painted farm four and the painted minis.

Everything is built from tiny synthetic frames written into a temp art
directory (``LILYPAD_ART_DIR``); nothing here touches real art or the network.
"""

import random

import pygame
import pytest

from lilypad.effects import animal_art as art
from lilypad.effects import animal_stencil, animals, assets, painted
from lilypad.effects.animals import AnimalCrossing, PeekabooAnimal
from lilypad.effects.base import EffectContext
from lilypad.effects.layout import CLASSIC

SCREEN = (640, 480)
IDLE, BLINK, STEP = (200, 0, 0), (0, 200, 0), (0, 0, 200)
COLOURS = {"idle": IDLE, "blink": BLINK, "step": STEP}


def ctx(seed: int = 7) -> EffectContext:
    return EffectContext(size=SCREEN, rng=random.Random(seed))


@pytest.fixture
def trial(tmp_path, monkeypatch):
    monkeypatch.setenv("LILYPAD_ART_DIR", str(tmp_path))
    directory = tmp_path / "painted"
    directory.mkdir()
    (directory / "manifest.toml").write_text("schema = 1\n", encoding="utf-8")
    previous = art._art_mode
    monkeypatch.setattr(animals, "_layout", CLASSIC)
    monkeypatch.setattr(animals, "_max_sprite_width", 0.0)
    yield directory
    painted.configure(assets.asset_root(kiosk=True))
    art.set_art_mode(previous, root=assets.asset_root(kiosk=True))
    animals._fit_size.cache_clear()


def add_animal(directory, name, *, step, width=80, height=40):
    folder = directory / name
    folder.mkdir()
    poses = ["idle", "blink", "step"] if step else ["idle", "blink"]
    for pose in poses:
        image = pygame.Surface((width, height), pygame.SRCALPHA)
        image.fill((*COLOURS[pose], 255))
        pygame.image.save(image, folder / f"{pose}.png")
    frames = ", ".join(f'{p} = "{name}/{p}.png"' for p in poses)
    view = "side" if art.faces_right(name) else "front"
    with (directory / "manifest.toml").open("a", encoding="utf-8") as stream:
        stream.write(
            f'\n[animals.{name}]\nview = "{view}"\nnative_height = {height}\n'
            f'frames = {{ {frames} }}\nanchor = [0.5, 1.0]\neye_at = [0.8, 0.2]\n'
            'back_at = [0.4, 0.3]\n')


def add_mini(directory, kind, *, colour=(250, 160, 0), width=30, height=30, file=True):
    folder = directory / "minis"
    folder.mkdir(exist_ok=True)
    if file:
        image = pygame.Surface((width, height), pygame.SRCALPHA)
        image.fill((*colour, 255))
        pygame.image.save(image, folder / f"{kind}.png")
    with (directory / "manifest.toml").open("a", encoding="utf-8") as stream:
        stream.write(f'\n[minis.{kind}]\nfile = "minis/{kind}.png"\nnative_height = {height}\n')


def shown(effect) -> tuple[int, int, int]:
    """The colour actually blitted for the effect's current pose."""
    surface = pygame.Surface(SCREEN)
    surface.fill((0, 0, 0))
    effect.draw(surface)
    sprite = effect._sprites[effect.pose]
    if effect.airborne:
        spot = (int(effect.x), int(effect.y))
    else:
        spot = (int(effect.x), int(effect.y) - sprite.get_height() // 2)
    return tuple(surface.get_at(spot))[:3]


def at(effect: AnimalCrossing, age: float) -> str:
    """Put the effect at ``age`` on its own clock and return its pose."""
    effect.age = age
    effect.x = SCREEN[0] / 2                  # fully on screen so draws are visible
    effect.update(0.0)
    effect.x = SCREEN[0] / 2
    return effect.pose


# ------------------------------------------------------------ pure schedules
@pytest.mark.parametrize("age,pose", [
    (0.00, "idle"), (0.30, "idle"),       # first footfall window
    (0.39, "step"), (0.70, "step"),       # 0.385 s is the first bob trough
    (0.78, "idle"), (1.20, "step"), (1.60, "idle"),
])
def test_walk_alternates_on_every_bob_trough(age, pose):
    assert AnimalCrossing.pose_for("walk", age) == pose


def test_walk_switches_exactly_at_the_bob_troughs():
    """The bob is |sin(2 pi 1.3 t)|: troughs at multiples of 1 / 2.6 s."""
    for k in range(1, 5):
        trough = k / 2.6
        before = AnimalCrossing.pose_for("walk", trough - 0.01)
        after = AnimalCrossing.pose_for("walk", trough + 0.01)
        if not any(a <= trough <= b for a, b in AnimalCrossing._BLINKS):
            assert before != after


@pytest.mark.parametrize("age,pose", [
    (0.00, "squash"),   # phase 0: still landing
    (0.04, "idle"),     # takeoff, still low (sin = 0.20)
    (0.12, "step"),     # airborne
    (0.31, "step"),     # top of the arc
    (0.50, "step"),
    (0.58, "squash"),   # phase > 0.9: landing
])
def test_hop_shows_step_while_airborne_and_squashes_on_landing(age, pose):
    assert AnimalCrossing.pose_for("hop", age) == pose


def test_hop_step_threshold_is_the_quarter_arc():
    import math
    period = AnimalCrossing.HOP_PERIOD
    low = AnimalCrossing.pose_for("hop", period * 0.07)      # sin = 0.218
    high = AnimalCrossing.pose_for("hop", period * 0.09)     # sin = 0.279
    assert math.sin(math.pi * 0.07) < 0.25 < math.sin(math.pi * 0.09)
    assert (low, high) == ("idle", "step")


@pytest.mark.parametrize("age,pose", [
    (0.00, "idle"), (0.20, "step"), (0.40, "idle"), (0.50, "step"), (1.40, "idle"),
])
def test_fly_flaps_at_3_hz(age, pose):
    assert AnimalCrossing.pose_for("fly", age) == pose


@pytest.mark.parametrize("age,pose", [
    (0.0, "idle"), (0.2, "idle"), (0.5, "step"), (0.8, "step"),
    (1.5, "step"), (1.8, "idle"), (2.6, "idle"),
])
def test_swim_swishes_at_1_2_hz(age, pose):
    assert AnimalCrossing.pose_for("swim", age) == pose


@pytest.mark.parametrize("age,pose", [
    (0.0, "idle"), (0.2, "idle"), (0.4, "step"), (0.6, "step"),
    (0.7, "idle"), (1.3, "step"),
])
def test_floater_pulses_at_1_5_hz(age, pose):
    assert AnimalCrossing.pose_for("fly", age, floater=True) == pose


@pytest.mark.parametrize("gait,floater", [
    ("walk", False), ("hop", False), ("fly", False), ("swim", False), ("fly", True),
])
@pytest.mark.parametrize("age", [0.95, 1.0, 2.15, 2.2])
def test_blink_overrides_every_gait(gait, floater, age):
    assert AnimalCrossing.pose_for(gait, age, floater) == "blink"


def test_a_landing_squash_still_beats_a_blink_on_hops(monkeypatch):
    """Legacy hops squash on landing even inside a blink window."""
    monkeypatch.setattr(AnimalCrossing, "_BLINKS", ((0.0, 10.0),))
    period = AnimalCrossing.HOP_PERIOD
    assert AnimalCrossing.pose_for("hop", period * 0.95) == "squash"
    assert AnimalCrossing.pose_for("hop", period * 0.5) == "blink"


def test_jellyfish_is_the_floater_and_sharks_of_the_air_are_not():
    assert AnimalCrossing(ctx(), "jellyfish")._floater is True
    assert AnimalCrossing(ctx(), "owl")._floater is False
    assert AnimalCrossing(ctx(), "whale")._floater is False


def test_the_effect_follows_its_own_clock_through_update():
    owl = AnimalCrossing(ctx(), "owl")
    poses = []
    for _ in range(60):
        owl.update(1 / 60)
        poses.append(owl.pose)
    assert owl.age == pytest.approx(1.0)
    assert {"idle", "step", "blink"} <= set(poses)
    assert poses[0] == "idle"


# --------------------------------------------- traced / drawn: step == idle
@pytest.mark.parametrize("mode", ["traced", "drawn"])
@pytest.mark.parametrize("name,gait", [
    ("giraffe", "walk"), ("rabbit", "hop"), ("owl", "fly"),
    ("whale", "swim"), ("jellyfish", "fly"),
])
def test_traced_and_drawn_step_is_the_idle_object(mode, name, gait):
    art.set_art_mode(mode)
    try:
        for seed in (1, 2, 3, 4):                 # both facings
            effect = AnimalCrossing(ctx(seed), name, gait=gait)
            assert effect._sprites["step"] is effect._sprites["idle"]
    finally:
        art.set_art_mode("drawn")


@pytest.mark.parametrize("mode", ["traced", "drawn"])
def test_legacy_routes_draw_the_same_pixels_whether_idle_or_step(mode):
    art.set_art_mode(mode)
    try:
        walker = AnimalCrossing(ctx(), "giraffe")
        at(walker, 0.4)
        assert walker.pose == "step"
        step = pygame.image.tobytes(_frame(walker), "RGB")
        walker.pose = "idle"
        assert pygame.image.tobytes(_frame(walker), "RGB") == step
    finally:
        art.set_art_mode("drawn")


def _frame(effect):
    surface = pygame.Surface(SCREEN)
    surface.fill((5, 5, 5))
    effect.draw(surface)
    return surface


# --------------------------------------------------------------- painted art
@pytest.mark.parametrize("name,gait,age,expected", [
    ("giraffe", "walk", 0.1, IDLE), ("giraffe", "walk", 0.5, STEP),
    ("giraffe", "walk", 0.95, BLINK),
    ("owl", "fly", 0.05, IDLE), ("owl", "fly", 0.2, STEP), ("owl", "fly", 2.2, BLINK),
    ("rabbit", "hop", 0.31, STEP), ("rabbit", "hop", 0.04, IDLE),
])
def test_painted_gait_blits_the_scheduled_frame(trial, name, gait, age, expected):
    add_animal(trial, name, step=True)
    art.set_art_mode("painted")
    effect = AnimalCrossing(ctx(), name, gait=gait)
    at(effect, age)
    assert shown(effect) == expected


def test_painted_hop_squashes_on_landing(trial):
    add_animal(trial, "rabbit", step=True)
    art.set_art_mode("painted")
    effect = AnimalCrossing(ctx(), "rabbit", gait="hop")
    at(effect, AnimalCrossing.HOP_PERIOD * 0.95)
    assert effect.pose == "squash"
    assert effect._sprites["squash"] is not effect._sprites["idle"]
    squash, idle = effect._sprites["squash"], effect._sprites["idle"]
    assert squash.get_size() == idle.get_size()          # same canvas, squatter body
    top = (idle.get_width() // 2, 1)
    assert idle.get_at(top).a == 255 and squash.get_at(top).a == 0


def test_painted_without_a_step_frame_aliases_idle_for_walkers_and_flyers(trial):
    add_animal(trial, "giraffe", step=False)
    add_animal(trial, "owl", step=False)
    art.set_art_mode("painted")
    for name, gait in (("giraffe", "walk"), ("owl", "fly")):
        effect = AnimalCrossing(ctx(), name, gait=gait)
        assert effect._sprites["step"] is effect._sprites["idle"]
        assert shown(_at(effect, 0.5)) == IDLE


def _at(effect, age):
    at(effect, age)
    return effect


def test_painted_swimmer_and_floater_derive_a_distinct_step(trial):
    add_animal(trial, "whale", step=False)
    add_animal(trial, "jellyfish", step=False)
    art.set_art_mode("painted")
    for name, gait in (("whale", "swim"), ("jellyfish", "fly")):
        effect = AnimalCrossing(ctx(), name, gait=gait)
        assert effect._sprites["step"] is not effect._sprites["idle"]
        assert effect._sprites["step"].get_size() == effect._sprites["idle"].get_size()


def test_the_schedule_adds_no_rng_draws(trial):
    """The same seed leaves the same rng state on painted and traced art."""
    add_animal(trial, "giraffe", step=True)
    add_animal(trial, "rabbit", step=True)
    states = {}
    for mode in ("painted", "traced"):
        art.set_art_mode(mode)
        for name in ("giraffe", "rabbit"):
            context = ctx(99)
            effect = AnimalCrossing(context, name)
            while effect.update(1 / 60):
                pass
            states[(mode, name)] = context.rng.getstate()
    for name in ("giraffe", "rabbit"):
        assert states[("painted", name)] == states[("traced", name)]


def test_painted_farm_four_use_front_view_frames_and_never_step(trial):
    add_animal(trial, "cow", step=False, width=40, height=40)
    art.set_art_mode("painted")
    assert art.resolved_mode("cow") == "painted"
    cow = PeekabooAnimal(ctx(), "cow")
    assert cow._sprites["idle"].get_at((10, 10))[:3] == IDLE
    assert cow._sprites["blink"].get_at((10, 10))[:3] == BLINK
    assert cow._sprites["step"] is cow._sprites["idle"]
    assert cow._sprites["squash"] is not cow._sprites["idle"]
    # Unchanged performance: the same pose names as before, never "step".
    seen = set()
    for _ in range(int(cow.total * 60) + 5):
        cow.update(1 / 60)
        seen.add(cow.pose)
    assert {"idle", "blink", "squash"} <= seen and "step" not in seen
    # The unpainted farm animals keep their drawn front view.
    assert art.resolved_mode("pig") != "painted"


# -------------------------------------------------------------------- minis
def test_painted_mini_replaces_the_drawn_one(trial):
    add_mini(trial, "duck", width=30, height=30)
    art.set_art_mode("painted")
    duck = art.mini_sprite("duck", 90)
    assert duck.get_size() == (90, 90)
    assert duck.get_at((45, 45))[:3] == (250, 160, 0)
    assert art.mini_sprite("duck", 90) is duck                     # cached
    assert art.mini_sprite("duck", 60).get_height() == 60


def test_a_wide_painted_mini_keeps_its_aspect(trial):
    add_mini(trial, "star", width=60, height=30)
    art.set_art_mode("painted")
    assert art.mini_sprite("star", 90).get_size() == (180, 90)


def test_kinds_without_a_row_fall_back_to_the_drawn_mini(trial):
    add_mini(trial, "duck")
    art.set_art_mode("painted")
    apple = art.mini_sprite("apple", 80)
    assert apple.get_size() == (80, 80)
    assert apple.get_at((40, 40))[:3] != (250, 160, 0)
    art.set_art_mode("drawn")
    drawn = art.mini_sprite("apple", 80)
    assert pygame.image.tobytes(drawn, "RGBA") == pygame.image.tobytes(apple, "RGBA")


def test_minis_are_drawn_unless_the_art_mode_is_painted(trial):
    add_mini(trial, "duck", colour=(250, 160, 0))
    art.set_art_mode("traced")
    traced = art.mini_sprite("duck", 90)
    assert traced.get_at((45, 45))[:3] != (250, 160, 0)
    art.set_art_mode("painted")
    assert art.mini_sprite("duck", 90).get_at((45, 45))[:3] == (250, 160, 0)
    art.set_art_mode("drawn")
    assert art.mini_sprite("duck", 90).get_at((45, 45))[:3] != (250, 160, 0)


@pytest.mark.parametrize("problem", ["missing", "corrupt", "wrong height", "outside"])
def test_bad_mini_falls_back_and_logs_once(trial, caplog, problem):
    if problem == "missing":
        add_mini(trial, "star", file=False)
    elif problem == "corrupt":
        add_mini(trial, "star")
        (trial / "minis" / "star.png").write_bytes(b"not an image")
    elif problem == "wrong height":
        add_mini(trial, "star", height=30)
        image = pygame.Surface((30, 20), pygame.SRCALPHA)
        pygame.image.save(image, trial / "minis" / "star.png")
    else:
        with (trial / "manifest.toml").open("a", encoding="utf-8") as stream:
            stream.write('\n[minis.star]\nfile = "../escape.png"\nnative_height = 30\n')
    caplog.set_level("WARNING", logger="lilypad.effects.animal_art")
    art.set_art_mode("painted")
    for size in (80, 90, 100):
        sprite = art.mini_sprite("star", size)
        assert sprite.get_size() == (size, size)
    warnings = [r for r in caplog.records if "painted mini star" in r.message]
    assert len(warnings) == 1


def test_stencil_probe_is_irrelevant_to_painted_minis(trial, monkeypatch):
    monkeypatch.setattr(animal_stencil, "available", lambda: False)
    add_mini(trial, "flower")
    art.set_art_mode("painted")
    assert art.mini_sprite("flower", 70).get_at((35, 35))[:3] == (250, 160, 0)
