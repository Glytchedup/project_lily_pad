"""Colours and shapes: geometry, the tint cache, and the two effects."""

import random

import pygame
import pytest

from lilypad.effects import shapes
from lilypad.effects.base import EffectContext
from lilypad.effects.shapes import (
    NAMED_COLORS,
    SHAPE_KINDS,
    ColorSplash,
    GiantShape,
    master_sprite,
    prewarm,
    shape_sprite,
)
from lilypad.input.mapper import classify

SIZE = (1280, 720)


@pytest.fixture
def ctx():
    return EffectContext(size=SIZE, rng=random.Random(1234))


def run(effect, seconds=6.0, dt=1 / 60, surface=None):
    """Drive an effect to completion, drawing every frame. Returns frame count."""
    surface = surface or pygame.Surface(SIZE)
    frames = 0
    while effect.update(dt) and frames < int(seconds / dt):
        effect.draw(surface)
        frames += 1
    return frames


# --------------------------------------------------------------------------
# Sprites
# --------------------------------------------------------------------------

def test_every_kind_builds():
    for kind in SHAPE_KINDS:
        sprite = shape_sprite(kind, 120, (255, 0, 0))
        assert sprite.get_size() == (120, 120)


def test_sprites_are_cached_by_kind_size_and_colour():
    a = shape_sprite("star", 100, (255, 0, 0))
    assert shape_sprite("star", 100, (255, 0, 0)) is a
    assert shape_sprite("star", 101, (255, 0, 0)) is not a
    assert shape_sprite("heart", 100, (255, 0, 0)) is not a
    assert shape_sprite("star", 100, (0, 255, 0)) is not a


def test_one_master_serves_every_colour():
    """The point of the multiply tint: colour must not cost a fresh render."""
    before = master_sprite("circle", 96)
    for color in NAMED_COLORS.values():
        shape_sprite("circle", 96, color)
    assert master_sprite("circle", 96) is before


def test_tint_does_not_mutate_the_master():
    master = master_sprite("square", 90)
    sample = master.get_at((45, 45))
    shape_sprite("square", 90, (255, 0, 0))
    shape_sprite("square", 90, (0, 0, 255))
    assert master.get_at((45, 45)) == sample


def near(actual, expected, tol=6):
    """Downscaling is a smoothscale, so the master's interior is not exactly
    255 everywhere and the multiply inherits that. A couple of levels off is
    anti-aliasing, not a wrong colour."""
    return all(abs(a - e) <= tol for a, e in zip(actual, expected))


def test_fill_takes_the_requested_colour():
    """Centre of a circle is interior, so it should be the tint."""
    sprite = shape_sprite("circle", 160, (255, 59, 48))
    px = sprite.get_at((80, 80))
    assert px.a > 240
    assert near((px.r, px.g, px.b), (255, 59, 48))


def test_shapes_have_a_dark_keyline():
    """Five same-coloured shapes sit side by side in a ColorSplash; without a
    keyline they merge into one blob."""
    sprite = shape_sprite("square", 160, (255, 255, 255))
    edge = sprite.get_at((80, 3))       # top edge, inside the bounding box
    assert edge.a > 0
    assert max(edge.r, edge.g, edge.b) < 90


def test_corners_are_transparent():
    sprite = shape_sprite("circle", 120, (255, 255, 255))
    assert sprite.get_at((1, 1)).a == 0


def test_shapes_actually_differ_from_each_other():
    """A geometry bug that returned the same polygon for two kinds would
    otherwise pass every other test here."""
    seen = set()
    for kind in SHAPE_KINDS:
        sprite = shape_sprite(kind, 64, (255, 255, 255))
        seen.add(pygame.image.tobytes(sprite, "RGBA"))
    assert len(seen) == len(SHAPE_KINDS)


def test_tiny_sizes_do_not_crash():
    for kind in SHAPE_KINDS:
        assert shape_sprite(kind, 1, (255, 255, 255)).get_size() == (8, 8)


def test_prewarm_builds_masters_and_is_idempotent():
    count = prewarm(720)
    assert count >= len(SHAPE_KINDS)
    assert prewarm(720) == count


def test_unknown_polygon_kind_is_rejected():
    with pytest.raises(ValueError):
        shapes._polygon("dodecahedron", 100)


# --------------------------------------------------------------------------
# GiantShape
# --------------------------------------------------------------------------

def test_giant_shape_runs_to_completion(ctx):
    for kind in SHAPE_KINDS:
        effect = GiantShape(ctx, kind)
        assert run(effect) > 0
        assert effect.update(1 / 60) is False


def test_giant_shape_falls_back_on_an_unknown_kind(ctx):
    assert GiantShape(ctx, "rhombus").kind == SHAPE_KINDS[0]


def test_giant_shape_colour_varies_across_presses(ctx):
    """A circle that is always blue teaches 'blue circle' as one word."""
    colors = {GiantShape(ctx, "circle").color for _ in range(40)}
    assert len(colors) > 1


def test_giant_shape_honours_an_explicit_colour(ctx):
    assert GiantShape(ctx, "star", color=(1, 2, 3)).color == (1, 2, 3)


def test_giant_shape_does_not_poison_the_cache(ctx):
    """Fading sets alpha; doing that on the shared sprite would leave every
    later shape of that colour half-transparent."""
    shared = shape_sprite("heart", shapes._giant_size(ctx.height), (255, 0, 0))
    effect = GiantShape(ctx, "heart", color=(255, 0, 0))
    run(effect)
    assert shared.get_alpha() in (None, 255)


def test_giant_shape_draws_within_the_screen(ctx):
    for _ in range(30):
        effect = GiantShape(ctx, "square")
        assert 0 < effect.pos[0] < ctx.width
        assert 0 < effect.pos[1] < ctx.height


def test_giant_shape_reports_a_budget_cost(ctx):
    assert len(GiantShape(ctx, "circle")) > 0


# --------------------------------------------------------------------------
# ColorSplash
# --------------------------------------------------------------------------

def test_color_splash_runs_to_completion(ctx):
    for name in NAMED_COLORS:
        effect = ColorSplash(ctx, name)
        assert run(effect) > 0


def test_color_splash_is_monochrome(ctx):
    """The whole lesson: every shape on screen is the same hue."""
    for name, rgb in NAMED_COLORS.items():
        effect = ColorSplash(ctx, name)
        assert effect.color == rgb
        for item in effect.items:
            # Sample the centre of each sprite; interior should be the colour.
            sprite = item["sprite"]
            w = sprite.get_width()
            px = sprite.get_at((w // 2, w // 2))
            assert near((px.r, px.g, px.b), rgb) or px.a == 0


def test_color_splash_varies_the_shapes(ctx):
    """Colour constant, shapes varied — otherwise it teaches 'blue square'."""
    runs = set()
    for _ in range(20):
        effect = ColorSplash(ctx, "blue")
        runs.add(tuple(id(i["sprite"]) for i in effect.items))
    assert len(runs) > 1


def test_color_splash_uses_distinct_shapes_within_one_press(ctx):
    effect = ColorSplash(ctx, "green")
    assert len({id(i["sprite"]) for i in effect.items}) == len(effect.items)


def test_color_splash_falls_back_on_an_unknown_colour(ctx):
    assert ColorSplash(ctx, "chartreuse").name == "red"


def test_color_splash_count_is_clamped(ctx):
    assert len(ColorSplash(ctx, "red", count=99).items) == len(SHAPE_KINDS)
    assert len(ColorSplash(ctx, "red", count=0).items) == 1


def test_color_splash_confetti_matches_the_colour(ctx):
    effect = ColorSplash(ctx, "yellow")
    colors = {p.color for p in effect.confetti.particles}
    assert colors == {NAMED_COLORS["yellow"]}


def test_color_splash_does_not_poison_the_cache(ctx):
    effect = ColorSplash(ctx, "purple")
    sprites = [i["sprite"] for i in effect.items]
    run(effect)
    assert all(s.get_alpha() in (None, 255) for s in sprites)


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------

def test_every_shape_key_maps_to_a_real_kind():
    from lilypad.input.mapper import _SHAPE_KEYS
    for key, kind in _SHAPE_KEYS.items():
        assert kind in SHAPE_KINDS
        assert classify(key).kind == "shape"
        assert classify(key).letter == kind


def test_every_colour_key_maps_to_a_real_colour():
    from lilypad.input.mapper import _COLOR_KEYS
    for key, name in _COLOR_KEYS.items():
        assert name in NAMED_COLORS
        assert classify(key).kind == "color"
        assert classify(key).letter == name


def test_all_five_shapes_are_reachable_from_the_keyboard():
    from lilypad.input.mapper import _SHAPE_KEYS
    assert set(_SHAPE_KEYS.values()) == set(SHAPE_KINDS)


def test_all_named_colours_are_reachable_from_the_keyboard():
    from lilypad.input.mapper import _COLOR_KEYS
    assert set(_COLOR_KEYS.values()) == set(NAMED_COLORS)


def test_numpad_digits_still_count():
    """The shape keys share the KP prefix; digits must not be captured."""
    for digit in "0123456789":
        assert classify(f"KP{digit}").kind == "number"


def test_registry_builds_effects_for_both_kinds(ctx):
    from lilypad.effects.registry import effects_for, registered_kinds
    assert {"shape", "color"} <= registered_kinds()
    assert effects_for(ctx, classify("COMMA"))
    assert effects_for(ctx, classify("GRAVE"))


def test_the_voice_has_a_word_for_every_shape_and_colour():
    """`build_voice` imports these lists rather than repeating them, so a new
    shape can never ship without a word. Assert the contract holds."""
    import inspect

    from lilypad.audio import synth
    source = inspect.getsource(synth.build_voice)
    assert "NAMED_COLORS" in source and "SHAPE_KINDS" in source


def test_audio_engine_speaks_the_name(tmp_path):
    """The name is the entire point of these keys."""
    from lilypad.audio.engine import AudioEngine

    engine = AudioEngine(tmp_path, mute=True, autogen=False)
    played = []
    engine._play = lambda *names: played.append(names)
    engine.on_action(classify("COMMA"))
    engine.on_action(classify("GRAVE"))
    assert ("voice/circle", "pop") in played
    assert ("voice/red", "pop") in played
