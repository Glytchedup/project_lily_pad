"""Full-length replays with a tiny asymmetric RGBA cast and a recording screen."""

import random
import weakref
from types import SimpleNamespace

import pygame
import pytest

from lilypad.effects import animal_art as art
from lilypad.effects import animals, assets, critter
from lilypad.effects.animal_specs import SPECS
from lilypad.effects.base import EffectContext
from lilypad.effects.layout import POND
from lilypad.effects.parade import GrandParade


SIZE = (320, 180)


@pytest.fixture
def cast(tmp_path, monkeypatch):
    root = tmp_path / "painted"
    root.mkdir()
    poses = ("idle", "step", "blink", "cheer")
    for width in (24, 60):
        for index, pose in enumerate(poses):
            sprite = pygame.Surface((width, 24), pygame.SRCALPHA)
            sprite.fill((45, 50 + 50 * index, 45), (1, 11, width - 2, 12))
            sprite.fill((220, 50 + 50 * index, 45), (round(width * 0.72), 3, width // 4, 10))
            pygame.image.save(sprite, root / f"{width}-{pose}.png")
    rows = ["schema = 1"]
    for name in (*art.animal_names(), "pip"):
        pip = name == "pip"
        side = name in SPECS
        width = 60 if side else 24
        frames = [f'{p} = "{width}-{p}.png"' for p in poses if p != "cheer" or pip]
        rows.extend(("[pip]" if pip else f"[animals.{name}]", "native_height = 24",
                     'view = "side"' if side else 'view = "front"',
                     "eye_at = [0.84, 0.27]", "back_at = [0.5, 0.4]", "anchor = [0.5, 0.95]",
                     "frames = { " + ", ".join(frames) + " }"))
    (root / "manifest.toml").write_text("\n".join(rows), encoding="utf-8")
    previous_mode = art._art_mode
    previous_pip = critter._pip_art, critter._art_root
    monkeypatch.setattr(animals, "_layout", POND)
    monkeypatch.setattr(animals, "_max_sprite_width", 0.60)
    art.set_art_mode("painted", tmp_path)
    critter.set_pip_art("painted", tmp_path)
    animals.prewarm(SIZE[1], screen_width=SIZE[0], max_sprite_width=0.60, layout=POND)
    critter.Frog(SIZE)
    yield EffectContext(SIZE, random.Random(942))
    art.set_art_mode(previous_mode, assets.asset_root(kiosk=True))
    critter.set_pip_art(*previous_pip)
    animals._fit_size.cache_clear()


class Screen(pygame.Surface):
    def __init__(self):
        super().__init__(SIZE)
        self.calls = []

    def blit(self, source, dest):
        rect = pygame.Rect(dest)
        assert rect.colliderect(self.get_clip()), "submitted an invisible sprite"
        self.calls.append((source, rect))
        return super().blit(source, dest)


def fanfare(parade):
    for _ in range(90):
        assert parade.update(1 / 30)
    assert parade.age == pytest.approx(3)
    assert not parade._pending


def test_procession_crosses_once_with_culled_blits_and_four_stationary_cheers(cast):
    state = cast.rng.getstate()
    parade = GrandParade.create(cast)
    screen = Screen()
    fanfare(parade)
    keys = {image: key for key, image in parade._frames.items()}
    side = {}
    farms = {}
    shown_poses = set()
    while parade.update(1 / 30):
        screen.calls.clear()
        parade.draw(screen)
        assert len(screen.calls) <= 6
        farm_on_screen = 0
        for image, rect in screen.calls:
            name, pose = keys[image]
            shown_poses.add((name, pose))
            if name in animals.PEEKABOO_CAST:
                farm_on_screen += 1
                farms.setdefault(name, []).append((rect.centerx, rect.top))
            elif name != "pip":
                assert image.get_height() == int(SIZE[1] * 0.22)
                side.setdefault(name, []).append(rect)
        assert farm_on_screen <= 1
    assert set(side) == set(SPECS) and len(side) == 26
    for positions in side.values():
        assert positions[0].left > SIZE[0] * 0.95
        assert positions[-1].right < SIZE[0] * 0.05
        assert all(b.x < a.x for a, b in zip(positions, positions[1:]))
    assert list(farms) == ["cow", "duck", "pig", "sheep"]
    for sightings in farms.values():
        xs, ys = zip(*sightings)
        assert len(set(xs)) == 1
        assert min(ys) < min(ys[0], ys[-1]) - 20
    assert {("pip", "cheer"), ("rabbit", "squash"), ("rabbit", "step"), ("brachiosaurus", "blink"),
            ("bear", "step"), ("jellyfish", "step"), ("owl", "step"), ("whale", "step")} <= shown_poses
    assert cast.rng.getstate() == state


def test_build_budget_duration_and_actual_surface_release(cast, monkeypatch):
    transient = []
    scale = pygame.transform.smoothscale

    def observe(*args):
        sprite = scale(*args)
        transient.append(weakref.ref(sprite))
        return sprite

    monkeypatch.setattr(pygame.transform, "smoothscale", observe)
    monkeypatch.setattr(assets, "load_image", lambda *_: pytest.fail("decoded on the input path"))
    cached = set(art._animal_cache), set(art._flip_cache), set(critter._sprite_cache)
    finished = []
    parade = GrandParade(cast, on_finish=lambda: finished.append(parade.progress()))
    assert not transient and parade.progress() == 0 and parade.pip_anchor() is None
    screen = Screen()
    for frame in range(1, 661):
        before = len(transient)
        alive = parade.update(1 / 30)
        parade.draw(screen)
        if frame < 90:
            assert not screen.calls
        screen.calls.clear()
        assert len(transient) - before <= (2 if frame <= 90 else 0)
        assert alive == (frame < 660)
    assert transient and all(ref() is None for ref in transient)
    assert cached == (set(art._animal_cache), set(art._flip_cache), set(critter._sprite_cache))
    assert parade.done and parade.pip_anchor() is None and finished == [1]
    assert not parade.update(4) and finished == [1]
    parade.draw(screen)
    assert not screen.calls


def test_low_scale_draws_alternating_dancers_and_recovers_on_the_next_draw(cast):
    parade = GrandParade(cast)
    fanfare(parade)
    keys = {image: key for key, image in parade._frames.items()}
    screen = Screen()
    normal, reduced = {}, {}
    while parade.update(1 / 20):
        for scale, seen in ((0.50, normal), (0.49, reduced)):
            cast.scale = scale
            screen.calls.clear()
            parade.draw(screen)
            for image, _ in screen.calls:
                name = keys[image][0]
                if name in SPECS:
                    seen.setdefault(name, None)
    assert len(normal) == 26 and list(reduced) == list(normal)[::2]


def test_stalled_fanfare_catches_up_without_bulk_building_or_extending_the_show(cast):
    parade = GrandParade(cast)
    assert parade.update(3.1)
    assert len(parade._frames) == 2
    for _ in range(60):
        before = len(parade._frames)
        assert parade.update(1 / 60)
        assert 0 <= len(parade._frames) - before <= 2
    assert not parade._pending
    assert not parade.update(22 - parade.age)
    assert parade.age == 22


@pytest.mark.parametrize("real_ride", [False, True])
def test_pip_contact_tracks_the_mirrored_head_and_uses_exactly_one_rider(cast, real_ride):
    frog = SimpleNamespace(ride=lambda *_: None) if real_ride else object()
    parade = GrandParade(cast, frog=frog)
    fanfare(parade)
    screen = Screen()
    parade.update(0.8)
    parade.draw(screen)
    mount_frames = {s for (name, _), s in parade._frames.items() if name == "brachiosaurus"}
    image, rect = next((s, rect) for s, rect in screen.calls if s in mount_frames)
    x, y = parade.pip_anchor()
    assert rect.left < x < rect.left + rect.width / 3
    assert rect.top <= y < rect.top + rect.height / 3
    assert image.get_at((x - rect.left, y - rect.top)).a > 0
    assert parade.lead_x_frac() == pytest.approx(rect.centerx / SIZE[0])
    pip = parade._frames.get(("pip", "cheer"))
    if real_ride:
        assert pip is None
    else:
        assert next(r for s, r in screen.calls if s is pip).midbottom == (x, y)
    screen.calls.clear()
    screen.set_clip((0, 0, 1, 1))
    parade.draw(screen)
    assert not screen.calls
    parade.update(3.4)
    assert parade.pip_anchor() is None
    assert 0 <= parade.lead_x_frac() < 1


@pytest.mark.parametrize("missing", ["all", "owl", "sheep"])
def test_missing_painted_cast_keeps_the_old_celebration_available(cast, tmp_path, missing):
    if missing == "all":
        art.set_art_mode("painted", tmp_path / "absent")
    else:
        manifest = tmp_path / "painted" / "manifest.toml"
        manifest.write_text(manifest.read_text().replace(f"[animals.{missing}]", "[animals.other]"))
        art.set_art_mode("painted", tmp_path)
    state = cast.rng.getstate()
    assert GrandParade.create(cast) is None
    parade = GrandParade(cast, on_finish=lambda: pytest.fail("finished a missing parade"))
    screen = Screen()
    parade.draw(screen)
    assert parade.done and not parade.update(60) and not screen.calls
    assert cast.rng.getstate() == state


def test_party_trios_rotate_every_eight_bars_with_no_farm_or_rider(cast):
    assert all(GrandParade.create(cast, party_bar=bar) is None for bar in (-1, 0, 7, 9))
    previous = set()
    for bar in (8, 16):
        parade = GrandParade.create(cast, party_bar=bar)
        screen = Screen()
        seen = set()
        while parade.update(1 / 30):
            screen.calls.clear()
            parade.draw(screen)
            assert len(screen.calls) <= 3 and parade.pip_anchor() is None
            for sprite, _ in screen.calls:
                seen.update(name for (name, _), s in parade._frames.items() if s is sprite)
        assert len(seen) == 3 and seen <= set(SPECS) and not seen & previous
        previous = seen
