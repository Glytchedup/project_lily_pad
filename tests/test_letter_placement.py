"""Spawn geometry is measured at keypress time, independently of the frame rate."""

import math
import random
from unittest.mock import Mock

import pygame
import pytest

from lilypad.config import SceneConfig
from lilypad.effects import animals, critter, letters
from lilypad.effects.base import EffectContext
from lilypad.effects.engine import EffectEngine
from lilypad.effects.layout import POND
from lilypad.effects.numbers import CountAlong
from lilypad.input.mapper import classify


@pytest.fixture(autouse=True)
def painted(tmp_path, monkeypatch):
    letters.set_letter_art("painted", tmp_path)
    monkeypatch.setattr(animals, "_layout", POND)
    monkeypatch.setattr(animals, "_max_sprite_width", 0)
    monkeypatch.setattr(animals, "resolved_mode", lambda name: "drawn")

    def stand_in(name, height, pose, left, width):
        art = pygame.Surface((height // 2, height), pygame.SRCALPHA)
        art.fill((145, 200, 77))
        return art

    monkeypatch.setattr(animals, "_scene_sprite", stand_in)
    yield
    letters.set_letter_art("traced", tmp_path)


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_letter_and_digit_clear_walker_pip_lily_and_each_other(tmp_path, size):
    from test_lily import build

    w, h = size
    engine = EffectEngine(size, rng=random.Random(28))
    engine.lily = build(tmp_path, size, seed=41)
    engine.lily.update(.5)
    frog = engine.frog
    frog.x, frog.y = .65 * w, .28 * h  # Pip mid-hop in the candidate band
    walker = animals.AnimalCrossing(engine.ctx, "bear")
    walker.update(.85)
    engine.effects.append(walker)
    frog_rect = critter.frog_sprite(frog.r, frog.pose).get_rect(midbottom=(int(frog.x), int(frog.y + frog._feet)))
    pad_rect = critter.lily_pad_sprite(frog.r).get_rect(center=(int(frog.pad.x), int(frog.pad.y)))
    art, at = engine.lily.spot.poses[engine.lily.pose]
    actors = (frog_rect, pad_rect, art.get_rect(topleft=at), walker._sprite_rect(walker._sprites[walker.pose]))
    view = pygame.Rect((0, 0), size)
    obstacles = engine.ctx.occupied()
    assert all(any(r.contains(actor.clip(view)) for r in obstacles) for actor in actors)
    letter = letters.GiantLetter(engine.ctx, "A")
    assert view.contains(letter.footprint)
    assert letter.footprint.collidelist(obstacles) == -1
    engine.effects.append(letter)
    engine.spawn(classify("5"), now=0.)
    number = next(effect for effect in engine.effects if isinstance(effect, CountAlong))
    assert view.contains(number.digit.footprint)
    assert number.digit.footprint.collidelist([*obstacles, letter.footprint]) == -1
    assert number.digit.footprint in engine.ctx.occupied()


@pytest.mark.parametrize("name", ["bear", "rabbit", "owl", "whale"])
@pytest.mark.parametrize("seed", [1, 2])
def test_sweep_covers_actual_next_90_frames_without_advancing_animal(name, seed):
    engine = EffectEngine((1280, 720), rng=random.Random(seed))
    animal = animals.AnimalCrossing(engine.ctx, name)
    engine.effects.append(animal)
    animal.update(.91)
    animal.pause(.32)
    animal.greet_bounce()
    rng_state = engine.ctx.rng.getstate()
    initial = animal.age, animal.x, animal.y, animal.pose, animal._pause_left
    obstacles = engine.ctx.occupied()
    assert engine.ctx.rng.getstate() == rng_state
    assert (animal.age, animal.x, animal.y, animal.pose, animal._pause_left) == initial
    view = pygame.Rect((0, 0), engine.size)
    for tick in range(91):
        rect = animal._sprite_rect(animal._sprites[animal.pose]).clip(view)
        assert any(r.contains(rect) for r in obstacles), (tick, rect, obstacles)
        animal.update(1 / 60)


def test_shrinks_before_accepting_overlap_and_preserves_minimum_size():
    size = (1280, 720)
    full = letters.GiantLetter(EffectContext(size, random.Random(4)), "M")
    gap_bottom = math.ceil(full.footprint.h * .90)
    blocked = pygame.Rect(0, gap_bottom, size[0], size[1] - gap_bottom)
    ctx = EffectContext(size, random.Random(4), occupied=lambda: [blocked])
    small = letters.GiantLetter(ctx, "M")
    assert math.ceil(.85 * full.glyph.get_height()) <= small.glyph.get_height() < full.glyph.get_height()
    assert not small.footprint.colliderect(blocked)
    ctx.occupied = lambda: [pygame.Rect((0, 0), size)]
    crowded = letters.GiantLetter(ctx, "M")
    assert crowded.glyph.get_height() == math.ceil(.85 * full.glyph.get_height())


def test_least_overlap_when_all_candidates_blocked():
    # The full-screen obstacle charges every position the same base area.
    # Only the left margin avoids the second charge.
    screen = pygame.Rect(0, 0, 640, 360)
    right = pygame.Rect(100, 0, 540, 360)
    ctx = EffectContext(screen.size, random.Random(15), occupied=lambda: [screen, right])
    glyph = letters.GiantLetter(ctx, "1", height_frac=.28)
    assert not glyph.footprint.colliderect(right)


def test_shared_rng_draw_count_fixed_for_free_and_blocked_candidates():
    size = (640, 360)
    screen = pygame.Rect((0, 0), size)
    for seed in range(10):
        ref = random.Random(seed)
        for _ in range(3):  # appearance seed, placement tie, eye phase
            ref.random()
        for blockers in ([], [screen], [pygame.Rect(0, 120, 640, 240)]):
            ctx = EffectContext(size, random.Random(seed), occupied=lambda: blockers)
            letters.GiantLetter(ctx, "A", color=(255, 255, 255))
            assert ctx.rng.getstate() == ref.getstate()
    spots = {letters.GiantLetter(EffectContext(size, random.Random(i)), "A").pos for i in range(10)}
    assert len(spots) > 1


def test_current_key_reserves_its_own_flyer_and_burst_uses_chosen_spot():
    engine = EffectEngine((1280, 720), rng=random.Random(19))
    engine.ctx.occupied = Mock(wraps=engine.ctx.occupied)
    engine.spawn(classify("O"), now=0.)
    engine.ctx.occupied.assert_called_once_with()
    burst, glyph, flyer = engine.effects
    assert all((p.x, p.y) == glyph.pos for p in burst.particles)
    view = pygame.Rect((0, 0), engine.size)
    for _ in range(90):
        flyer.update(1 / 60)
        rect = flyer._sprite_rect(flyer._sprites[flyer.pose]).clip(view)
        assert not glyph.footprint.colliderect(rect)


def test_peekaboo_and_visible_sliding_album_are_reserved(tmp_path):
    engine = EffectEngine((1280, 720), rng=random.Random(8), root=tmp_path, album=True)
    album = engine.album
    assert not album.visible
    engine.spawn(classify("C"), now=0.)
    glyph = next(e for e in engine.effects if isinstance(e, letters.GiantLetter))
    cow = next(e for e in engine.effects if isinstance(e, animals.PeekabooAnimal))
    strip = pygame.Rect(0, 0, 1280, album.strip_h)
    assert not glyph.footprint.colliderect(strip)
    cow.update(.65)
    album.update(.10)
    assert album.visible and strip in engine.ctx.occupied()
    canvas = pygame.Surface(engine.size, pygame.SRCALPHA)
    cow.draw(canvas)
    rect = canvas.get_bounding_rect()
    assert rect and any(r.contains(rect) for r in engine.ctx.occupied())
    for _ in range(80):
        album.update(.1)
    assert not album.visible and strip not in engine.ctx.occupied()


def test_storybook_reserves_only_animal_third_through_dissolve(tmp_path):
    from test_scenery import make_art

    make_art(tmp_path, count=1)
    directory = tmp_path / "storybook"
    directory.mkdir()
    (directory / "manifest.toml").write_text(
        'schema = 1\n[cards.A]\nfile="A.png"\n[cards.B]\nfile="B.png"')
    size = (600, 360)
    card = pygame.Surface(size)
    engine = EffectEngine(size, scene=SceneConfig(reflections=False, lily=False), root=tmp_path,
                          storybook="both")
    book = engine.storybook
    left, right = pygame.Rect(0, 0, 200, 360), pygame.Rect(400, 0, 200, 360)
    try:
        for letter, occupied, clear in (("A", left, right), ("B", right, left)):
            book._cache[letter] = card
            book._begin(letter, "encore")
            book.draw(card.copy())
            book.update(.5)
            assert occupied in engine.ctx.occupied() and clear not in engine.ctx.occupied()
            book._end()
            book.draw(card.copy())
            assert occupied in engine.ctx.occupied()
            book.update(.5)
            assert occupied not in engine.ctx.occupied()
    finally:
        engine.close()
