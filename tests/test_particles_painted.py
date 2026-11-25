"""Painted FX use synthetic RGBA art. No asset pack or display hardware required."""

import hashlib
import logging
import random

import pygame
import pytest

from lilypad.effects import glow
from lilypad.effects.base import BRIGHT_PALETTE, EffectContext
from lilypad.effects.bubbles import BubbleField, bubble_sprite
from lilypad.effects.particles import Balloons, Fireworks, burst, confetti_rain, shaped_burst


FAMILIES = {
    "star": (True, "add"), "petal": (True, "alpha"), "leaf": (False, "alpha"),
    "heart": (True, "alpha"), "bubble": (False, "alpha"), "bokeh": (True, "add"),
    "balloon": (True, "alpha"), "glint": (False, "add"),
}
# Six RGB frames from the unmodified burst on main at 81f0998.
MAIN_BURST = "2a88830eb1df2164acec1232d61fcc07a28a4b39a0a02eb29fa6ecedef56f5d9"


def write_kit(root, kinds=FAMILIES, copies=1):
    directory = root / "fx"
    directory.mkdir()
    lines = ["schema = 1"]
    for kind in kinds:
        tint, blend = FAMILIES[kind]
        names = []
        for i in range(copies):
            # Hidden white catches an additive blit that forgot alpha coverage.
            image = pygame.Surface((20, 20), pygame.SRCALPHA)
            image.fill((255, 255, 255, 0))
            pygame.draw.rect(image, (255, 255, 255, 128), (6, 5, 10, 11))
            pygame.draw.rect(image, (208, 244, 176, 255), (1 + i % 3, 4, 4, 5))
            name = f"{kind}_{i}.png"
            pygame.image.save(image, directory / name)
            names.append(f'"{name}"')
        lines.extend((f"[sprites.{kind}]", f"files = [{', '.join(names)}]",
                      f"tint = {str(tint).lower()}", f'blend = "{blend}"'))
    (directory / "manifest.toml").write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture(autouse=True)
def restore_style():
    glow.set_fx_style("glow")
    yield
    glow.set_fx_style("glow")


def burst_digest():
    ctx = EffectContext((224, 176), random.Random(2308))
    effect = burst(ctx, (112, 88), count=37)
    canvas = pygame.Surface(ctx.size, depth=32)
    digest = hashlib.sha256()
    for _ in range(6):
        effect.update(1 / 24)
        canvas.fill((19, 31, 43))
        effect.draw(canvas)
        digest.update(pygame.image.tobytes(canvas, "RGB"))
    return digest.hexdigest()


def test_glow_matches_main_even_with_painted_files(tmp_path):
    write_kit(tmp_path)
    glow.set_fx_style("painted", tmp_path)
    assert burst_digest() != MAIN_BURST
    glow.set_fx_style("glow", tmp_path)
    assert burst_digest() == MAIN_BURST


@pytest.mark.parametrize("manifest", [None, "schema = 1", "schema = 3", "broken = ["])
def test_unavailable_kit_logs_once_and_matches_main(tmp_path, caplog, manifest):
    if manifest is not None:
        (tmp_path / "fx").mkdir()
        (tmp_path / "fx/manifest.toml").write_text(manifest, encoding="utf-8")
    with caplog.at_level(logging.INFO, logger=glow.__name__):
        glow.set_fx_style("painted", tmp_path)
        assert burst_digest() == MAIN_BURST
    assert len([r for r in caplog.records if r.name == glow.__name__]) == 1


@pytest.mark.parametrize("copies", [4, 8])
def test_variant_cache_fits_four_mb_including_rotations_and_all_tints(tmp_path, copies):
    write_kit(tmp_path, copies=copies)
    glow.set_fx_style("painted", tmp_path)
    total = 0
    cached_files = 0
    for kind, (tint, blend) in FAMILIES.items():
        colors = glow._painted[kind]
        assert set(colors) == (set(BRIGHT_PALETTE) if tint else {None})
        count = len(next(iter(colors.values())))
        assert 1 <= count <= copies
        if copies == 4:
            assert count == copies
        cached_files += count
        for variants in colors.values():
            assert len(variants) == count
            for art in variants:
                assert art.flags == (pygame.BLEND_ADD if blend == "add" else 0)
                assert 1 <= len(art.frames) <= 3
                for angles in art.frames:
                    assert len(angles) == (4 if kind in ("petal", "leaf") else 1)
                    total += sum(f.get_pitch() * f.get_height() for f in angles)
    assert 0 < total <= 4_000_000
    if copies == 8:
        assert cached_files < len(FAMILIES) * copies  # exercised the budget gate


def test_add_uses_coverage_and_alpha_preserves_painted_color(tmp_path):
    write_kit(tmp_path)
    glow.set_fx_style("painted", tmp_path)
    bg = (26, 38, 52)
    color = BRIGHT_PALETTE[4]
    target = pygame.Surface((24, 24))
    for kind in ("star", "heart"):
        target.fill(bg)
        glow.painted_sprite(kind, 0, color).draw(target, 12, 12, 20)
        assert target.get_at((3, 3))[:3] == bg
        if kind == "star":
            expected = [min(255, c / 2 + b) for c, b in zip(color, bg)]
        else:
            expected = [(c + b) / 2 for c, b in zip(color, bg)]
        assert target.get_at((12, 12))[:3] == pytest.approx(expected, abs=2)
    for kind in ("leaf", "bubble", "glint"):
        assert glow.painted_sprite(kind, 0, color) is glow.painted_sprite(kind, 0)


def test_confetti_uses_both_families_and_rotates_prebuilt_frames(tmp_path, monkeypatch):
    write_kit(tmp_path, copies=2)
    glow.set_fx_style("painted", tmp_path)

    def unexpected_build(*args, **kwargs):
        pytest.fail("FX decoded or transformed art after startup")

    monkeypatch.setattr(pygame.image, "load", unexpected_build)
    for name in ("rotate", "rotozoom", "scale", "smoothscale"):
        monkeypatch.setattr(pygame.transform, name, unexpected_build)
    ctx = EffectContext((160, 120), random.Random(123))
    sys = confetti_rain(ctx, count=32)
    leaf_frames = glow._painted["leaf"][None]
    leaves = [p for p in sys.particles if any(p.sprite is v for v in leaf_frames)]
    assert len(leaves) == 8
    assert all(p.sprite in glow._painted["petal"][p.color] for p in sys.particles if p not in leaves)
    assert len({id(p.sprite) for p in leaves}) == 2
    p = leaves[0]
    p.x, p.y, p.size, p.life = 40, 40, 8, 2
    sys.particles = [p]
    canvas = pygame.Surface(ctx.size)
    frames = set()
    for turn in range(4):
        p.age = turn / 8
        canvas.fill("black")
        sys.draw(canvas)
        frames.add(pygame.image.tobytes(canvas, "RGB"))
    assert len(frames) == 4


def test_partial_kit_keeps_valid_files_and_uses_remaining_confetti_family(tmp_path):
    write_kit(tmp_path, ("leaf",))
    manifest = tmp_path / "fx/manifest.toml"
    manifest.write_text(manifest.read_text().replace('"leaf_0.png"', '"missing.png", "leaf_0.png"')
                        + '\n[sprites.petal]\nfiles=["../outside.png"]\ntint=true\nblend="alpha"\n',
                        encoding="utf-8")
    glow.set_fx_style("painted", tmp_path)
    ctx = EffectContext((200, 160), random.Random(12))
    leaf = glow.painted_sprite("leaf", 0)
    assert leaf is not None and all(p.sprite is leaf for p in confetti_rain(ctx).particles)
    assert burst_digest() == MAIN_BURST


def test_bubbles_fade_independently_and_balloons_keep_strings(tmp_path):
    write_kit(tmp_path)
    glow.set_fx_style("painted", tmp_path)
    ctx = EffectContext((320, 200), random.Random(128))
    field = BubbleField(ctx, 3)
    field.bubbles = field.bubbles[:2]
    first, second = field.bubbles
    first.x, second.x = 60, 180
    first.y = second.y = 60
    first.radius = second.radius = 32
    first.age = first.life - 0.125
    frame = bubble_sprite(32)
    assert frame is glow.painted_sprite("bubble", 0).frame(64)
    canvas = pygame.Surface(ctx.size)
    field.draw(canvas)
    assert 0 < canvas.get_at((60, 60)).r < canvas.get_at((180, 60)).r
    assert frame.get_alpha() == 255

    balloons = Balloons(ctx, 6)
    balloon = balloons.parts[0]
    balloons.parts = [balloon]
    balloon.x, balloon.y = 100, 80
    canvas.fill("black")
    balloons.draw(canvas)
    body = balloon.sprite.frame(2.3 * int(balloon.size))
    expected = pygame.Surface(body.get_size())
    expected.blit(body, (0, 0))
    assert canvas.get_at((100, 80)) == expected.get_at(body.get_rect().center)
    assert canvas.get_at((100, 80 + body.get_height() // 2 + 15))[:3] == (200, 200, 200)


def test_fading_glow_bubbles_match_main_on_rgb_and_alpha_targets():
    field = BubbleField(EffectContext((160, 120), random.Random(2308)), count=3)
    for i, bubble in enumerate(field.bubbles):
        bubble.x, bubble.y, bubble.radius = 50 + i * 18, 60, 28
        bubble.age = bubble.life - (i + 1) / 8
    for flags in (0, pygame.SRCALPHA):
        canvas = pygame.Surface((160, 120), flags, 32)
        canvas.fill((19, 31, 43, 164))
        expected = canvas.copy()
        # The main renderer copied the cached bubble before applying each fade.
        for bubble in field.bubbles:
            sprite = bubble_sprite(28).copy()
            sprite.set_alpha(int(255 * ((bubble.life - bubble.age) / 0.5)))
            expected.blit(sprite, sprite.get_rect(center=(bubble.x, bubble.y)))
        field.draw(canvas)
        assert pygame.image.tobytes(canvas, "RGBA") == pygame.image.tobytes(expected, "RGBA")


def test_firework_bokeh_sits_under_original_sparks_then_disappears(tmp_path):
    write_kit(tmp_path, ("bokeh",))
    ctx = EffectContext((400, 280), random.Random(46))
    glow.set_fx_style("painted", tmp_path)
    show = Fireworks(ctx, rockets=1)
    while not show.bursts:
        show.update(1 / 60)
    event = show.bursts[0]
    assert all(p.sprite is None for p in event.sys.particles)
    assert event.bokeh is not None
    canvas = pygame.Surface(ctx.size)
    show.draw(canvas)
    expected = pygame.Surface(ctx.size)
    event.bokeh.draw(expected, *event.origin, 56 * (1 - event.age / show.CRACKLE_AT))
    show.trail.draw(expected)
    event.sys.draw(expected)
    assert pygame.image.tobytes(canvas, "RGB") == pygame.image.tobytes(expected, "RGB")
    expected.fill("black")
    show.trail.draw(expected)
    event.sys.draw(expected)
    assert pygame.image.tobytes(canvas, "RGB") != pygame.image.tobytes(expected, "RGB")
    event.age = show.CRACKLE_AT
    canvas.fill("black")
    show.draw(canvas)
    assert pygame.image.tobytes(canvas, "RGB") == pygame.image.tobytes(expected, "RGB")


@pytest.mark.parametrize("scale", [0.25, 0.5, 1.0])
def test_counts_lifetimes_and_rng_match_through_death_and_pop(tmp_path, scale):
    write_kit(tmp_path)

    def replay(style):
        glow.set_fx_style(style, tmp_path)
        ctx = EffectContext((320, 240), random.Random(23), scale)
        field = BubbleField(ctx)
        balloons = Balloons(ctx, 12)
        show = Fireworks(ctx, rockets=3)
        systems = [burst(ctx, (100, 100)), confetti_rain(ctx), shaped_burst(ctx, (80, 80), "heart")]
        effects = [*systems, field, balloons, show]
        canvas = pygame.Surface(ctx.size)
        trace = []
        for i in range(100):
            if i == 4:
                b = field.bubbles[0]
                field.pop_near((b.x, b.y), 16)
            alive = tuple(effect.update(0.1) for effect in effects)
            if i % 5 == 0:
                for effect in effects:
                    effect.draw(canvas)
            counts = tuple(map(len, effects))
            assert counts == (*[len(s.particles) for s in systems],
                              len(field.bubbles) + len(field.droplets.particles), len(balloons.parts),
                              len(show.trail.particles) + len(show.rockets)
                              + sum(len(b.sys.particles) for b in show.bursts))
            trace.append((alive, counts))
            if not any(alive):
                break
        assert not any(alive)
        return trace, ctx.rng.getstate()

    assert replay("painted") == replay("glow")
