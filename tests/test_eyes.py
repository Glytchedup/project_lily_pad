"""Pixel, cache and motion contracts for the painted eye kit."""

import math
import random
from unittest.mock import Mock

import pygame
import pytest

from lilypad.effects import critter, eyes, letters
from lilypad.effects.base import EffectContext


@pytest.fixture
def kit(tmp_path):
    folder = tmp_path / "eyes"
    folder.mkdir()
    for i, width in enumerate((40, 32, 46)):
        for kind, color in (("white", (242, 224 - 5 * i, 199)),
                            ("iris", (48 + 10 * i, 32, 26))):
            image = pygame.Surface((width if kind == "white" else 40, 40), pygame.SRCALPHA)
            pygame.draw.ellipse(image, color, image.get_rect())
            if kind == "iris":
                pygame.draw.circle(image, (255, 255, 255), (13, 12), 5)
            pygame.image.save(image, folder / f"{kind}{i}.png")
    (folder / "manifest.toml").write_text(
        'schema=1\nwhites=["white0.png","white1.png","white2.png"]\n'
        'irises=["iris0.png","iris1.png","iris2.png"]\n', encoding="utf-8")
    eyes.set_eye_art("painted", tmp_path)
    yield tmp_path
    eyes.set_eye_art("drawn", tmp_path)
    letters.set_letter_art("drawn", tmp_path)
    critter.set_pip_art("drawn", tmp_path)


def test_variants_and_bounded_size_cache(kit, monkeypatch):
    monkeypatch.setattr(eyes.assets, "load_image", Mock(side_effect=AssertionError("reloaded kit")))
    first = eyes.prepare_eye(23, 0)
    assert eyes.prepare_eye(23, 0).white is first.white
    assert eyes.prepare_eye(23, 0).iris is first.iris
    assert first.white is not eyes.prepare_eye(23, 1).white
    assert first.iris is not eyes.prepare_eye(23, 3).iris
    for radius in range(2, 65):
        for variant in range(3):
            eyes.prepare_eye(radius, variant)
    cache = eyes._layers.cache_info()
    assert 0 < cache.currsize == cache.maxsize < cache.misses


@pytest.mark.parametrize("variant", [0, 1, 2])
def test_every_blink_is_prebuilt_and_clamps_iris_in_white(kit, variant, monkeypatch):
    art = eyes.prepare_eye(24, variant)
    w, h = art.white[0].get_size()
    assert len(art.white) == len(art.iris) == 4
    assert art.iris[0].get_width() == pytest.approx(min(w, h) * .55, abs=1)
    assert [s.get_height() for s in art.white] == sorted({s.get_height() for s in art.white}, reverse=True)
    monkeypatch.setattr(pygame.transform, "smoothscale", Mock(side_effect=AssertionError("scaled in draw")))
    cx, cy = 42, 42
    for step, white in enumerate(art.white):
        left_and_right = []
        for dx, dy in ((-999, 0), (999, 0), (0, -999), (0, 999), (999, 999), (-999, -999)):
            surface = pygame.Surface((84, 84), pygame.SRCALPHA)
            eyes.draw_eye(surface, (cx, cy), 24, dx, dy, step / 3, art=art)
            mask = pygame.mask.from_surface(surface, threshold=0)
            backing = pygame.mask.from_surface(white, threshold=0)
            assert mask.count() == mask.overlap_area(backing, white.get_rect(center=(cx, cy)).topleft)
            # The opaque dark iris moves left and right, even mid-blink.
            dark = pygame.mask.from_threshold(surface, (55, 32, 26, 255), (30, 15, 15, 10))
            assert dark.count() > 0
            if dy == 0:
                left_and_right.append(dark.centroid()[0])
        assert left_and_right[0] < cx < left_and_right[1]


def test_painted_pop_and_blink_use_spawn_frames_after_cache_eviction(kit, monkeypatch):
    letters.set_letter_art("painted", kit)
    ctx = EffectContext((640, 360), random.Random(4))
    letter = letters.GiantLetter(ctx, "A", hold_time=8.)
    rng_after_spawn = ctx.rng.getstate()
    eyes._layers.cache_clear()  # force a miss if draw looks a pose up again
    monkeypatch.setattr(pygame.transform, "smoothscale", Mock(side_effect=AssertionError("scaled in draw")))
    monkeypatch.setattr(pygame.transform, "scale", Mock(side_effect=AssertionError("scaled in draw")))
    draw = Mock(wraps=eyes.draw_eye)
    monkeypatch.setattr(letters, "draw_eye", draw)
    target = pygame.Surface(ctx.size)
    peaks = []
    saw_bounce = False
    for tick in range(1, 480):
        letter.age = tick / 60
        letter.draw(target)
        args = draw.call_args.args
        if letter.age < letter.POP_TIME:
            wander = letter.age * 2.6 + letter.eye_phase
            saw_bounce |= args[4] != int(math.sin(wander * .7) * args[2] * .35)
        if args[5] > .9 and (not peaks or tick - peaks[-1] > 10):
            peaks.append(tick)
    assert saw_bounce
    assert len(peaks) >= 2 and 2 * 60 <= peaks[1] - peaks[0] <= 5 * 60
    assert ctx.rng.getstate() == rng_after_spawn


@pytest.mark.parametrize("mode", ["painted", "traced", "drawn"])
def test_fallback_and_legacy_eye_frames_match_original_rgba(kit, mode):
    if mode == "painted":
        (kit / "eyes" / "iris2.png").unlink()  # discard the whole previously loaded kit
    eyes.set_eye_art(mode, kit)
    letters.set_letter_art(mode, kit)
    assert eyes.prepare_eye(24) is None
    ctx = EffectContext((520, 320), random.Random(102))
    glyph = letters.GiantLetter(ctx, "O")
    rng = ctx.rng.getstate()
    for age in (.21, .30, .71, 1.24):
        glyph.age = age
        output = pygame.Surface(ctx.size, pygame.SRCALPHA)
        output.fill((44, 31, 16, 161))
        expected = output.copy()
        glyph.draw(output)
        # Start with the same glyph without eyes; the baseline eye geometry
        # below is independent of the renderer in eyes.py.
        glyph.eyes = False
        glyph.draw(expected)
        glyph.eyes = True
        if age >= glyph.POP_TIME:
            ox, oy = glyph._wobble()
            rect = glyph.glyph.get_rect(center=(int(glyph.pos[0]) + ox, int(glyph.pos[1]) + oy))
            r = max(6, rect.h // 14)
            y = rect.top + int(rect.h * .10)
            phase = age * 2.6 + glyph.eye_phase
            dx = int(math.cos(phase) * r * .35)
            dy = int(math.sin(phase * .7) * r * .35)
            for sign in (-1, 1):
                x = rect.centerx + sign * int(rect.w * .16)
                pygame.draw.circle(expected, (25, 25, 30), (x, y), r + 2)
                pygame.draw.circle(expected, "white", (x, y), r)
                pygame.draw.circle(expected, (25, 25, 30), (x + dx, y + dy), max(3, r // 2))
        assert pygame.image.tobytes(output, "RGBA") == pygame.image.tobytes(expected, "RGBA")
    assert ctx.rng.getstate() == rng


def test_pip_gaze_stays_on_measured_whites_through_squash_and_duck(kit, monkeypatch):
    folder = kit / "painted"
    folder.mkdir()
    face = pygame.Surface((100, 80), pygame.SRCALPHA)
    face.fill((65, 139, 71))
    # The right white is smaller and off-centre around its manifest anchor.
    # Both differences matter when the eye region is scaled down to a duck.
    pygame.draw.ellipse(face, "white", (10, 10, 28, 23))
    pygame.draw.ellipse(face, "white", (67, 13, 19, 18))
    pygame.image.save(face, folder / "face.png")
    (folder / "manifest.toml").write_text(
        'schema=1\n[pip]\nnative_height=80\neye_at=[0.24,0.275]\n'
        'frames={idle="face.png",blink="face.png",eyes_white="face.png"}\n', encoding="utf-8")
    critter.set_pip_art("painted", kit)
    frog = critter.Frog((980, 720))
    target = pygame.Surface((frog.w, frog.h))
    assert frog._look_irises is not None
    eyes._layers.cache_clear()
    monkeypatch.setattr(pygame.transform, "smoothscale", Mock(side_effect=AssertionError("scaled an iris")))
    for pose in ("idle", "squash", "duck"):
        frog.squash = .9 if pose == "squash" else 0.
        if pose == "duck":
            frog.duck(1)
        frog.look(None)
        target.fill((0, 0, 0))
        frog.draw(target)
        before = target.copy()  # identical synthetic idle and eyes_white frames
        positions = []
        for dx, dy in ((-1, 0), (1, 0), (-1, -1), (1, 1), (1, -1), (-1, 1)):
            frog.look(dx, dy)
            target.fill((0, 0, 0))
            frog.draw(target)
            dark = pygame.mask.from_threshold(target, (48, 32, 26), (20, 10, 10))
            pupils = sorted(dark.get_bounding_rects(), key=lambda b: b.centerx)
            assert len(pupils) == 2
            # Check every changed pixel, including antialiased edges and highlights.
            changed = pygame.mask.from_threshold(target, (0, 0, 0), (1, 1, 1), before)
            changed.invert()
            white = pygame.mask.from_threshold(before, (255, 255, 255), (31, 31, 31))
            assert changed.count() > 0
            assert changed.count() == white.overlap_area(changed, (0, 0))
            positions.append(pupils[0].centerx)
        assert positions[0] < positions[1]
