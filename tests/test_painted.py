"""Painted animal routing with locally generated, registered RGBA frames."""

import logging
import random
from pathlib import Path

import pygame
import pytest

from lilypad.config import load
from lilypad.effects import animal_art as art
from lilypad.effects import animal_stencil, animals, assets, painted
from lilypad.effects.base import EffectContext
from lilypad.effects.layout import CLASSIC, POND, layout_for


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


def add_animal(directory, name, *, step=False, width=80, height=40):
    folder = directory / name
    folder.mkdir()
    poses = ["idle", "blink", "step"] if step else ["idle", "blink"]
    for index, pose in enumerate(poses):
        image = pygame.Surface((width, height), pygame.SRCALPHA)
        image.fill((40 + index * 60, 120, 80, 255), (0, height // 3, width, height // 3))
        image.set_at((width - 3, height // 3), (250, 20, 10, 150))
        pygame.image.save(image, folder / f"{pose}.png")
    frames = ", ".join(f'{p} = "{name}/{p}.png"' for p in poses)
    view = "side" if art.faces_right(name) else "front"
    with (directory / "manifest.toml").open("a", encoding="utf-8") as stream:
        stream.write(
            f'\n[animals.{name}]\nview = "{view}"\nnative_height = {height}\nframes = {{ {frames} }}\n'
            'anchor = [0.5, 1.0]\neye_at = [0.8, 0.2]\nback_at = [0.4, 0.3]\n'
            'source_hash = "sha256:fixture"\nprompt_id = "fixture"\nextra = "ignored"\n'
        )


def test_native_frames_landmarks_mirror_and_scaled_cache(trial, monkeypatch):
    add_animal(trial, "giraffe", step=True)
    art.set_art_mode("painted")
    assert painted.has("giraffe") and painted.aspect("giraffe") == 2
    assert painted.eye_at("giraffe") == (0.8, 0.2) and painted.back_at("giraffe") == (0.4, 0.3)
    scale = pygame.transform.smoothscale
    with monkeypatch.context() as mp:
        mp.setattr(pygame.transform, "smoothscale", lambda *_: pytest.fail("scaled native art"))
        for index, pose in enumerate(("idle", "blink", "step")):
            sprite = art.animal_sprite("giraffe", 40, pose)
            assert sprite is painted.build("giraffe", 40, pose)
            assert sprite.get_at((2, 15)).r == 40 + index * 60
            assert sprite.get_at((0, 0)).a == 0
            left = art.animal_sprite_facing("giraffe", 40, pose, True)
            assert left.get_at((2, 13)) == sprite.get_at((77, 13)) == (250, 20, 10, 150)
    down = art.animal_sprite("giraffe", 20)
    assert down.get_size() == (40, 20)
    native = assets.load_image(trial / "giraffe/idle.png")
    for height in (20, 60, 40):
        expected = scale(native, (2 * height, height)) if height != 40 else native
        actual = art.animal_sprite("giraffe", height)
        assert pygame.image.tobytes(actual, "RGBA") == pygame.image.tobytes(expected, "RGBA")


@pytest.mark.parametrize("mode", ["traced", "drawn"])
@pytest.mark.parametrize("left", [False, True])
def test_step_is_the_idle_object_on_both_fallback_routes(mode, left):
    previous = art._art_mode
    try:
        art.set_art_mode(mode)
        idle = art.animal_sprite_facing("giraffe", 64, "idle", left)
        assert art.animal_sprite_facing("giraffe", 64, "step", left) is idle
        assert art.animal_sprite("giraffe", 64, "step") is art.animal_sprite("giraffe", 64)
        for cache in (art._animal_cache, art._flip_cache):
            assert ("giraffe", 64, "step", mode) not in cache
    finally:
        art.set_art_mode(previous)


@pytest.mark.parametrize("bad", ["missing", "corrupt", "different canvas", "outside"])
def test_bad_entry_logs_once_and_other_routes_still_work(trial, caplog, bad):
    add_animal(trial, "giraffe", step=True)
    add_animal(trial, "whale")
    blink = trial / "giraffe/blink.png"
    if bad == "missing":
        blink.unlink()
    elif bad == "corrupt":
        blink.write_bytes(b"this is not an image")
    elif bad == "different canvas":
        pygame.image.save(pygame.Surface((80, 39), pygame.SRCALPHA), blink)
    else:
        manifest = trial / "manifest.toml"
        manifest.write_text(manifest.read_text().replace("giraffe/blink.png", "../outside.png"))
    art.set_art_mode("painted")
    for left in (False, True):
        idle = art.animal_sprite_facing("giraffe", 40, "idle", left)
        assert art.animal_sprite_facing("giraffe", 40, "step", left) is idle
    assert art.resolved_mode("giraffe") == "traced"
    assert art.resolved_mode("sheep") == "drawn"
    assert art.resolved_mode("whale") == "painted"
    assert len([r for r in caplog.records if r.name == painted.__name__]) == 1
    art.set_art_mode("traced")
    assert art.animal_sprite_facing("giraffe", 40, "idle", True) is idle


@pytest.mark.parametrize("manifest", ["schema = 2", "schema = true", "bad = ["])
def test_invalid_manifest_logs_once(trial, caplog, manifest):
    (trial / "manifest.toml").write_text(manifest, encoding="utf-8")
    art.set_art_mode("painted")
    for name in ("giraffe", "whale", "sheep", "giraffe"):
        assert not painted.has(name)
    assert len([r for r in caplog.records if r.name == painted.__name__]) == 1


def test_painted_and_drawn_survive_without_svg(trial, monkeypatch):
    add_animal(trial, "cow")
    monkeypatch.setattr(animal_stencil, "available", lambda: False)
    art.set_art_mode("painted")
    assert art.resolved_mode("giraffe") == "drawn"
    assert art.resolved_mode("cow") == "painted"
    idle = art.animal_sprite("cow", 40)
    assert art.animal_sprite_facing("cow", 40, "step", True) is idle


def test_webp_frames_use_the_same_route(trial):
    add_animal(trial, "duck", width=1, height=1)
    for pose in ("idle", "blink"):
        (trial / "duck" / f"{pose}.webp").write_bytes(assets._WEBP_PIXEL)
    manifest = trial / "manifest.toml"
    manifest.write_text(manifest.read_text().replace(".png", ".webp"))
    art.set_art_mode("painted")
    assert painted.has("duck") == assets.webp_supported()
    if assets.webp_supported():
        native = art.animal_sprite("duck", 1)
        assert native.get_size() == (1, 1)
        assert native.get_at((0, 0)) == assets.load_image(trial / "duck/idle.webp").get_at((0, 0))
    else:
        assert art.resolved_mode("duck") == "drawn"


def test_indexed_pngs_can_be_resized_without_a_display(trial, monkeypatch):
    add_animal(trial, "duck")
    frame = pygame.Surface((80, 40), depth=8)
    frame.set_palette_at(1, (255, 0, 0))
    frame.fill(1)
    for pose in ("idle", "blink"):
        pygame.image.save(frame, trial / "duck" / f"{pose}.png")
    art.set_art_mode("painted")
    monkeypatch.setattr(pygame.display, "get_surface", lambda: None)
    result = painted.build("duck", 20)
    assert result.get_size() == (40, 20)
    assert result.get_at((0, 0)) == (255, 0, 0, 255)


def test_lost_trial_frame_at_new_size_retires_the_whole_entry(trial, caplog):
    add_animal(trial, "giraffe")
    art.set_art_mode("painted")
    assert art.animal_sprite("giraffe", 30).get_width() == 60
    (trial / "giraffe/blink.png").unlink()
    fallback = art.animal_sprite_facing("giraffe", 50, "step", True)
    assert art.resolved_mode("giraffe") == "traced"
    assert fallback is art.animal_sprite_facing("giraffe", 50, "idle", True)
    assert len([r for r in caplog.records if r.name == painted.__name__]) == 1


def test_kiosk_root_and_trial_root_do_not_share_painted_sprites(trial):
    add_animal(trial, "giraffe")
    art.set_art_mode("painted")
    marked = art.animal_sprite_facing("giraffe", 40, "idle", True)
    # Select a separate package-like root explicitly, as kiosk startup does.
    packaged = trial.parent / "package"
    (packaged / "painted").mkdir(parents=True)
    add_animal(packaged / "painted", "giraffe", width=60)
    manifest = packaged / "painted/manifest.toml"
    manifest.write_text("schema = 1\n" + manifest.read_text())
    art.set_art_mode("painted", root=packaged)
    replacement = art.animal_sprite_facing("giraffe", 40, "idle", True)
    assert replacement.get_width() == 60 and replacement is not marked


def test_derived_poses_keep_the_canvas_and_are_cached(trial):
    for name in ("whale", "jellyfish"):
        add_animal(trial, name, width=100, height=100)
    art.set_art_mode("painted")
    idle = painted.build("whale", 100)
    step = art.animal_sprite("whale", 100, "step")
    assert step is painted.build("whale", 100, "step")
    assert step.get_size() == idle.get_size()
    for x in range(35, 100):
        for y in range(100):
            assert step.get_at((x, y)) == idle.get_at((x, y))
    offsets = [step.subsurface((x, 0, 1, 100)).get_bounding_rect().y - 33 for x in range(35)]
    assert min(offsets) == -4 and max(offsets) == 4
    idle = art.animal_sprite("jellyfish", 100)
    step = art.animal_sprite("jellyfish", 100, "step")
    expected = pygame.Surface(idle.get_size(), pygame.SRCALPHA)
    expected.blit(pygame.transform.scale(idle, (100, 92)), (0, 8))
    assert pygame.image.tobytes(step, "RGBA") == pygame.image.tobytes(expected, "RGBA")
    squash = art.animal_sprite("jellyfish", 100, "squash")
    assert squash.get_size() == idle.get_size()
    assert squash.get_bounding_rect().height < idle.get_bounding_rect().height


def test_prewarm_uses_spawn_sizes_facings_and_resolved_counts(trial, caplog, monkeypatch):
    add_animal(trial, "giraffe", width=240, step=True)
    add_animal(trial, "duck")
    art.set_art_mode("painted")
    with caplog.at_level(logging.INFO, logger=animals.__name__):
        built = animals.prewarm(200, screen_width=300, max_sprite_width=0.5, layout=POND)
    assert built == 25 * 3 * 2 + 4 * 2 + 3
    assert "animal art: painted (2), traced (25), drawn (3)" in caplog.messages
    monkeypatch.setattr(art, "_build_sprite", lambda *_: pytest.fail("cold sprite at spawn"))
    monkeypatch.setattr(pygame.transform, "flip", lambda *_: pytest.fail("cold facing at spawn"))
    for seed in (0, 1):
        ctx = EffectContext(size=(300, 200), rng=random.Random(seed))
        crossing = animals.AnimalCrossing(ctx, "giraffe")
        assert crossing.going_left == (seed == 1)
        assert crossing.height == 25 and crossing._sprite_w == 150
        assert crossing._ground == 200 * POND.ground
        peek = animals.PeekabooAnimal(ctx, "duck")
        assert peek.height == 75 and peek._sprite_w == 150


@pytest.mark.parametrize("mode", ["painted", "traced", "drawn"])
def test_tiny_positive_cap_reaches_the_visible_sprites(trial, mode):
    add_animal(trial, "alligator", width=240)
    art.set_art_mode(mode)
    animals.prewarm(120, screen_width=100, max_sprite_width=0.01, layout=POND)
    animal = animals.AnimalCrossing(EffectContext((100, 120), random.Random(42)), "alligator")
    assert animal.height == 1
    assert all(frame.get_size() == (1, 1) for frame in animal._sprites.values())


@pytest.mark.parametrize("config,layout", [("config.toml", POND), ("config.legacy.toml", CLASSIC)])
def test_configured_bands_and_swimmer_height(trial, config, layout):
    cfg = load(Path(__file__).resolve().parents[1] / config)
    art.set_art_mode(cfg.effects.animal_art)
    animals.prewarm(360, screen_width=640, max_sprite_width=cfg.effects.max_sprite_width,
                    layout=layout_for(cfg.scene.world))
    ctx = EffectContext(size=(640, 360), rng=random.Random(42))
    swimmer = animals.AnimalCrossing(ctx, "whale")
    # At this screen size the swimmer fits at the gait's natural height.
    assert swimmer.height == int(360 * layout.swim_height)
    assert layout.swim_band[0] <= swimmer._swim_y / 360 <= layout.swim_band[1]
    flyer = animals.AnimalCrossing(ctx, "owl")
    assert layout.fly_band[0] <= flyer._air_y / 360 <= layout.fly_band[1]
    assert animals.AnimalCrossing(ctx, "giraffe")._ground == 360 * layout.ground
