"""Tests for the key-hold rainbow comet effect (VISUAL_REVIEW.md #9)."""

from __future__ import annotations

import random

import pygame
import pytest

from lilypad.effects.base import EffectContext
from lilypad.effects.comet import Comet


def ctx(seed: int = 1234, scale: float = 1.0) -> EffectContext:
    return EffectContext(size=(640, 480), rng=random.Random(seed), scale=scale)


def test_stays_within_bounds_over_long_hold():
    c = Comet(ctx())
    w, h = 640, 480
    dt = 1 / 60
    for _ in range(60 * 30):  # 30 simulated seconds
        c.update(dt)
        assert 0.0 <= c.x <= w
        assert 0.0 <= c.y <= h


def test_update_returns_true_while_unreleased():
    c = Comet(ctx())
    for _ in range(600):
        assert c.update(1 / 60) is True


def test_head_radius_grows_monotonically_to_cap():
    from lilypad.effects.comet import _BIRTH_RADIUS, _CAP_RADIUS, _REF_HEIGHT
    c = Comet(ctx())
    k = ctx().height / _REF_HEIGHT  # radii scale with resolution
    prev = c.radius
    assert prev == pytest.approx(_BIRTH_RADIUS * k, rel=0.1)
    for _ in range(60 * 7):  # 7 s, past the ~6 s growth window
        c.update(1 / 60)
        r = c.radius
        assert r >= prev - 1e-9
        prev = r
    assert prev == pytest.approx(_CAP_RADIUS * k, abs=0.5)


def test_release_spawns_burst_then_eventually_finishes():
    c = Comet(ctx())
    for _ in range(30):
        c.update(1 / 60)
    pre_len = len(c)

    c.release()
    assert len(c) > pre_len  # finale burst particles appeared

    alive_frames = 0
    while c.update(1 / 60) and alive_frames < 60 * 10:
        alive_frames += 1
    assert alive_frames < 60 * 10, "comet never finished after release"


def test_double_release_is_safe():
    c = Comet(ctx())
    c.update(1 / 60)
    c.release()
    n_after_first_release = len(c)
    c.release()  # no-op: no second burst, no crash
    assert len(c) == n_after_first_release


def test_draw_never_crashes_before_or_after_release():
    surface = pygame.Surface((640, 480))
    c = Comet(ctx())
    for _ in range(10):
        c.update(1 / 60)
        c.draw(surface)
    c.release()
    for _ in range(10):
        c.update(1 / 60)
        c.draw(surface)


def test_deterministic_with_seed():
    c1 = Comet(ctx(seed=42))
    c2 = Comet(ctx(seed=42))
    for _ in range(120):
        c1.update(1 / 60)
        c2.update(1 / 60)
        assert (c1.x, c1.y) == (c2.x, c2.y)
        assert c1.radius == c2.radius


def test_shed_count_scales_with_ctx_scale():
    full = Comet(ctx(seed=7, scale=1.0))
    tiny = Comet(ctx(seed=7, scale=0.25))
    for _ in range(30):
        full.update(1 / 60)
        tiny.update(1 / 60)
    assert len(tiny.trail) < len(full.trail)
