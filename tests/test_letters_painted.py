"""Painted letter routing, cache ownership and the original font route."""

import math
import random
from unittest.mock import Mock

import pygame
import pytest

from lilypad.effects import letters
from lilypad.effects.base import EffectContext, random_bright


@pytest.fixture
def sticker(tmp_path):
    directory = tmp_path / "letters"
    directory.mkdir()
    art = pygame.Surface((46, 62), pygame.SRCALPHA)
    # Asymmetric ink with a transparent hole and padding on every side.
    art.fill((224, 78, 122), (4, 3, 14, 52))
    art.fill((224, 78, 122), (4, 40, 35, 15))
    pygame.image.save(art, directory / "L.png")
    (directory / "broken.webp").write_bytes(b"not an image")
    (directory / "manifest.toml").write_text(
        'schema = 1\n[letters.L]\nfile="L.png"\n[letters.C]\nfile="broken.webp"\n'
        '[letters.B]\nfile="absent.webp"\n[letters.Z]\nfile="../L.png"\n'
        '[letters."5"]\nfile="L.png"\n', encoding="utf-8")
    letters.set_letter_art("painted", tmp_path)
    yield tmp_path
    letters.set_letter_art("traced", tmp_path)


def context(seed=12):
    return EffectContext((640, 360), random.Random(seed))


def test_sticker_prescaled_once_per_height_and_never_in_draw(sticker, monkeypatch):
    smooth = Mock(wraps=pygame.transform.smoothscale)
    monkeypatch.setattr(pygame.transform, "smoothscale", smooth)
    first = letters.GiantLetter(context(), "L")
    second = letters.GiantLetter(context(), "L")
    small = letters.GiantLetter(context(), "L", height_frac=.28)
    assert smooth.call_count == 2
    assert first.glyph.get_parent() is second.glyph.get_parent()
    assert first.glyph.get_parent() is not small.glyph.get_parent()
    assert first.glyph.get_at((2, 2)).r > 200
    assert first.glyph.get_at((first.glyph.get_width() - 1, 0)).a == 0
    screen = pygame.Surface((640, 360), pygame.SRCALPHA)
    monkeypatch.setattr(pygame.transform, "scale", Mock(side_effect=AssertionError("scaled in draw")))
    for age in (.02, .14, .21, .27, .6, 1.65):
        screen.fill((0, 0, 0, 0))
        first.age = age
        first.draw(screen)
        assert screen.get_bounding_rect() and first.footprint.contains(screen.get_bounding_rect())
    assert smooth.call_count == 2
    assert 0 < first.glyph.get_alpha() < 255
    assert second.glyph.get_alpha() == second.glyph.get_parent().get_alpha() == 255


def test_eyes_sit_on_upper_opaque_stroke(sticker, monkeypatch):
    glyph = letters.GiantLetter(context(), "L")
    glyph.age = .6
    screen = pygame.Surface((640, 360))
    circles = Mock(wraps=pygame.draw.circle)
    monkeypatch.setattr(pygame.draw, "circle", circles)
    glyph.draw(screen)
    dx, dy = glyph._wobble()
    rect = glyph.glyph.get_rect(center=(glyph.pos[0] + dx, glyph.pos[1] + dy))
    whites = [c.args[2] for c in circles.call_args_list if c.args[1] == (255, 255, 255)]
    assert len(whites) == 2 and whites[0][0] < whites[1][0]
    for x, y in whites:
        assert .10 <= (y - rect.y) / rect.h <= .18
        assert glyph.glyph.get_at((x - rect.x, y - rect.y)).a >= 128


@pytest.mark.parametrize("text", ["5", "10", "?", "A", "B", "C", "Z"])
def test_nonletters_and_missing_or_unusable_rows_render_the_font(sticker, monkeypatch, text):
    render = Mock(wraps=letters.render_glyph)
    monkeypatch.setattr(letters, "render_glyph", render)
    glyph = letters.GiantLetter(context(), text)
    assert render.call_args.args[0] == text and render.call_count == 1
    assert glyph.glyph.get_bounding_rect() and glyph._eye_ink is None


@pytest.mark.parametrize("mode", ["traced", "drawn"])
def test_legacy_font_pixels_position_and_rng_match_original(sticker, mode):
    letters.set_letter_art(mode, sticker)
    ctx = context()
    ctx.occupied = Mock(side_effect=AssertionError("legacy queried the scene"))
    reference = context()
    color = random_bright(reference.rng)
    rainbow = reference.rng.random() < .25
    art = letters.render_glyph("L", int(.6 * ctx.height), color, reference.rng, rainbow)
    pos = (reference.rng.uniform(.3 * ctx.width, .7 * ctx.width),
           reference.rng.uniform(.35 * ctx.height, .65 * ctx.height))
    phase = reference.rng.uniform(0, math.tau)
    glyph = letters.GiantLetter(ctx, "L")
    assert glyph.pos == pos and glyph.eye_phase == phase
    assert ctx.rng.getstate() == reference.rng.getstate()
    assert pygame.image.tobytes(glyph.glyph, "RGBA") == pygame.image.tobytes(art, "RGBA")
    # Compare a full pop frame on a coloured background, including its placement.
    glyph.age = .21
    output = pygame.Surface(ctx.size)
    output.fill((44, 15, 31))
    expected = output.copy()
    scale = 1.15
    img = pygame.transform.scale(art, (int(art.get_width() * scale), int(art.get_height() * scale)))
    expected.blit(img, img.get_rect(center=tuple(map(int, pos))))
    glyph.draw(output)
    assert pygame.image.tobytes(output, "RGB") == pygame.image.tobytes(expected, "RGB")


@pytest.mark.parametrize("manifest", ["schema=2", "letters=7", "broken [toml", "schema=1\nletters=[]"])
def test_reconfiguration_discards_old_art_on_invalid_manifest(sticker, manifest):
    (sticker / "letters" / "manifest.toml").write_text(manifest, encoding="utf-8")
    letters.set_letter_art("painted", sticker)
    assert letters.GiantLetter(context(), "L")._eye_ink is None
