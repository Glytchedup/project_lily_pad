"""Frame-by-frame checks against the single-buffer renderer at e6d7d6c."""

import random
from types import SimpleNamespace

import pygame
import pytest

from lilypad.effects import animals
from lilypad.effects.ambient import CelebrationPulse
from lilypad.effects.animals import AnimalCrossing, PeekabooAnimal
from lilypad.effects.bubbles import BubbleField
from lilypad.effects.comet import Comet
from lilypad.effects.engine import EffectEngine
from lilypad.effects.letters import GiantLetter
from lilypad.effects.numbers import CountAlong
from lilypad.effects.particles import Rings
from lilypad.input.mapper import Action, classify


SIZE = (224, 128)


@pytest.fixture
def synthetic_cast(monkeypatch):
    def sprite(name, height, pose, going_left, screen_width):
        image = pygame.Surface((height // 2, height), pygame.SRCALPHA)
        pygame.draw.ellipse(image, (232, 98, 11, 255), image.get_rect())
        return image
    monkeypatch.setattr(animals, "_scene_sprite", sprite)


def _old_draw(e, screen):
    # Frozen oracle. Keep its frame counter, veil and draw order independent
    # of the production passes so a change to either renderer is observable.
    if e.asleep:
        screen.fill((0, 0, 0))
        return
    e._frame_no += 1
    e.pond.draw(e._scene)
    if e.trails:
        if e._trails_live and e.ctx.scale <= 0.4:
            e._trails_live = False
        elif not e._trails_live and e.ctx.scale >= 0.6:
            e._trails_live = True
    if e.trails and e._trails_live and e.chaos is None:
        e._scene.set_alpha(80)
        screen.blit(e._scene, (0, 0))
        if e._frame_no % 4 == 0:
            screen.fill((9, 9, 9), special_flags=pygame.BLEND_RGB_SUB)
            e._scene.set_alpha(None)
            screen.blit(e._scene, (0, 0), special_flags=pygame.BLEND_RGB_MAX)
    else:
        e._scene.set_alpha(None)
        screen.blit(e._scene, (0, 0))
    if e.attract is not None:
        e.attract.draw(screen)
    pulses = []
    for effect in e.effects:
        if isinstance(effect, CelebrationPulse):
            pulses.append(effect)
        else:
            effect.draw(screen)
    e.frog.draw(screen)
    for pulse in pulses:
        pulse.draw(screen)
    if e.chaos is not None:
        e.chaos.draw(screen)


def _pixels(surface):
    return pygame.image.tobytes(surface, "RGBA")


@pytest.mark.parametrize(("clean", "trails"), [(False, True), (True, False), (False, False)])
def test_disabled_paths_match_original_every_frame(clean, trails, synthetic_cast):
    actual, reference = [EffectEngine(SIZE, trails=trails, clean_sprites=clean,
                                      rng=random.Random(733), idle_timeout=0.4)
                         for _ in range(2)]
    screen, expected = [pygame.Surface(SIZE) for _ in range(2)]
    for surface in (screen, expected):
        surface.fill((49, 97, 151))
    actions = {0: classify("G"), 3: classify("C"), 9: classify("5"),
               12: classify("ENTER"), 29: Action("mash_start"), 42: Action("mash_end")}
    for frame in range(120):
        now = frame / 60
        for engine in (actual, reference):
            if frame in actions:
                engine.spawn(actions[frame], now)
            if frame == 55:
                engine.start_party(now)
            if frame == 75:
                engine.end_party(now)
            engine.ctx.scale = 0.3 if 78 <= frame < 86 else 1.0
            engine.update(1 / 60, now)
        state = actual.ctx.rng.getstate()
        actual.draw(screen)
        _old_draw(reference, expected)
        assert _pixels(screen) == _pixels(expected), frame
        assert state == actual.ctx.rng.getstate() == reference.ctx.rng.getstate()
        assert actual._fx is None


def test_crossing_clears_every_vacated_pixel_immediately(synthetic_cast):
    engine = EffectEngine(SIZE, clean_sprites=True, rng=random.Random(2))
    screen, expected = [pygame.Surface(SIZE) for _ in range(2)]
    pond = (8, 14, 27)
    engine.pond.draw = lambda target: target.fill(pond)
    engine.frog.draw = lambda target: None
    animal = AnimalCrossing(engine.ctx, "giraffe")
    engine.effects.append(animal)
    visible = 0
    for frame in range(215):  # includes the entire 3.4 s crossing and its aftermath
        alive = animal.update(1 / 60)
        if not alive:
            engine.effects.clear()
        engine.draw(screen)
        expected.fill(pond)
        if alive:
            animal.draw(expected)
            if 0 < animal.x < SIZE[0]:
                visible += 1
                assert screen.get_at((int(animal.x), int(animal.y - animal.height / 2)))[:3] != pond
        # Every vacated pixel matches the scene on the very next frame.
        assert _pixels(screen) == _pixels(expected), frame
    assert visible > 90


def test_fx_trails_persist_without_picking_up_screen_overlays():
    engine = EffectEngine(SIZE, clean_sprites=True, rng=random.Random(12))
    screen = pygame.Surface(SIZE)
    engine.pond.draw = lambda target: target.fill((0, 0, 0))
    engine.effects.append(SimpleNamespace(draw=lambda target: target.set_at((3, 3), "white")))
    engine.draw(screen)
    fx = engine._fx
    assert fx is not None and fx.get_alpha() is None
    assert screen.get_at((3, 3))[:3] == (255, 255, 255)
    engine.effects.clear()
    screen.fill("red")  # mimics an external overlay drawn after engine.draw
    engine.draw(screen)
    assert engine._fx is fx
    assert 0 < screen.get_at((3, 3)).r < 255
    assert screen.get_at((3, 3)) == fx.get_at((3, 3))
    assert screen.get_at((2, 2))[:3] == (0, 0, 0)
    engine._fall_asleep()
    engine.draw(screen)
    engine.wake(3.0)
    engine.draw(screen)
    assert screen.get_at((3, 3))[:3] == (0, 0, 0)


def test_clean_pass_order_and_destinations():
    engine = EffectEngine(SIZE, clean_sprites=True, rng=random.Random(27))
    screen = pygame.Surface(SIZE)
    calls = []

    def painter(name):
        return lambda surface: calls.append((name, surface))

    def effect(cls, name, gait=None):
        obj = cls.__new__(cls)
        obj.draw = painter(name)
        obj.gait = gait
        return obj

    engine.pond.draw = painter("pond")
    engine.frog.draw = painter("pip and pad")
    engine.attract = SimpleNamespace(draw=painter("attract"))
    engine.chaos = SimpleNamespace(draw=painter("chaos"))
    engine.effects = [
        effect(GiantLetter, "letter"), effect(PeekabooAnimal, "farm"),
        effect(AnimalCrossing, "swimmer", "swim"), effect(CelebrationPulse, "pulse"),
        effect(AnimalCrossing, "hopper", "hop"), effect(CountAlong, "digit"),
        effect(AnimalCrossing, "flyer", "fly"), effect(AnimalCrossing, "walker", "walk"),
        effect(Rings, "rings"), effect(BubbleField, "bubbles"), effect(Comet, "comet"),
        SimpleNamespace(draw=painter("particles")),
    ]
    engine.draw(screen)
    assert calls == [
        ("pond", engine._scene), ("particles", engine._fx), ("comet", engine._fx),
        ("bubbles", engine._fx), ("rings", engine._fx), ("attract", engine._fx),
        ("flyer", screen), ("hopper", screen), ("walker", screen), ("swimmer", screen),
        ("pip and pad", screen), ("farm", screen), ("letter", screen), ("digit", screen),
        ("pulse", screen), ("chaos", screen),
    ]
