"""Traced-outline animals: the trial covering giraffe, triceratops and whale.

Two things make this worth its own suite. The art comes from files, so it can
go missing in a way generated art cannot. And it is *optional* — a machine
whose SDL_image lacks SVG support has to fall back rather than crash, and the
fallback is exactly the sort of path nobody exercises by hand.
"""

import pygame
import pytest

from lilypad.config import load as load_config
from lilypad.effects import animal_art, animal_stencil
from lilypad.effects.animal_specs import SPECS, STENCILS
from lilypad.effects.animals import ANIMAL_LETTERS, DINOSAURS, GAITS, prewarm

TRIO = ("giraffe", "triceratops", "whale")


@pytest.fixture(autouse=True)
def _restore_mode():
    """``set_silhouettes`` is process-global; never leak it into another test."""
    before = animal_art.silhouettes_enabled()
    yield
    animal_art.set_silhouettes(before)


@pytest.fixture
def traced():
    assert animal_art.set_silhouettes(True), "SVG support expected on the dev box"
    return True


# ------------------------------------------------------------------ the cast
def test_the_trial_covers_exactly_the_three_agreed_creatures():
    assert tuple(sorted(STENCILS)) == TRIO


@pytest.mark.parametrize("name", TRIO)
def test_every_stencil_creature_is_a_real_member_of_the_cast(name):
    """A typo here would ship art for an animal nobody can summon."""
    assert name in SPECS, "needs an AnimalSpec for its colours"
    assert name in set(ANIMAL_LETTERS.values()) | set(DINOSAURS)


@pytest.mark.parametrize("name", TRIO)
def test_the_artwork_is_actually_present(name):
    path = animal_stencil.ASSET_DIR / STENCILS[name].file
    assert path.is_file(), f"{path} missing — did package-data drop it?"
    assert path.read_bytes().lstrip().startswith(b"<?xml")


@pytest.mark.parametrize("name", TRIO)
def test_every_outline_is_credited(name):
    """Licences are per-image, not per-site. An uncredited file is unaudited."""
    credits = (animal_stencil.ASSET_DIR / "CREDITS.md").read_text(encoding="utf-8")
    assert STENCILS[name].file in credits
    assert "CC0" in credits


# ------------------------------------------------------------------ geometry
@pytest.mark.parametrize("name", TRIO)
def test_sprite_is_exactly_the_height_asked_for(traced, name):
    for height in (64, 180, 301):
        assert animal_art.animal_sprite(name, height).get_height() == height


@pytest.mark.parametrize("name", TRIO)
def test_sprite_fills_its_box_with_no_dead_margin(traced, name):
    """The SVG canvas may pad the animal; the sprite box must be the animal.

    Everything that positions a creature on screen — the ground line, the fly
    band, the off-screen start — treats the sprite box as the creature. A
    transparent margin reads as an animal floating above the bank.
    """
    sprite = animal_art.animal_sprite(name, 240)
    bounds = sprite.get_bounding_rect()
    assert bounds.width >= sprite.get_width() - 2
    assert bounds.height >= sprite.get_height() - 2


@pytest.mark.parametrize("name", TRIO)
def test_aspect_ratio_holds_at_every_size(traced, name):
    """Guards the crop, which is where this can go wrong silently.

    Note these sprites *do* touch their own edges, unlike the drawn cast —
    ``test_nothing_in_the_cast_is_clipped_by_its_own_sprite`` in
    ``test_animals.py`` is the opposite invariant and deliberately does not
    apply here. A traced sprite is cropped to its content, so the box is the
    animal and the feet sit exactly on the bottom edge, which is what puts
    them on the ground line.

    What can still break is the crop itself: a misparsed viewBox letterboxes
    the animal inside its own rasterisation, and the giveaway is the aspect
    ratio drifting between sizes rather than anything looking obviously wrong
    at one size.
    """
    ratios = []
    for height in (48, 120, 240, 400):
        s = animal_art.animal_sprite(name, height)
        ratios.append(s.get_width() / s.get_height())
    assert max(ratios) - min(ratios) < max(ratios) * 0.04, ratios


@pytest.mark.parametrize("name", TRIO)
def test_the_eye_lands_on_the_animal_and_not_in_thin_air(traced, name):
    """The one number per creature that can only be found by looking.

    ``eye_at`` is a fraction of the sprite box, so a plausible-looking value
    can still sit in the empty corner beside a long neck. This checks it
    against the outline itself.
    """
    height = 240
    stroke = animal_stencil._stroke_px(height)
    shape = animal_stencil._shape(name, height - 2 * stroke)
    w, h = shape.get_size()
    ex, ey = STENCILS[name].eye_at
    px = shape.get_at((int(w * ex), int(h * ey)))
    assert px[3] > 0, f"{name} eye_at={STENCILS[name].eye_at} is off the body"


@pytest.mark.parametrize("name", TRIO)
def test_animals_face_right_like_the_rest_of_the_cast(traced, name):
    """Mass forward of centre — every side-on creature must agree on this.

    PhyloPic does not: some outlines point left, some right, and a creature
    facing backwards while it walks is the most obvious bug there is.
    """
    height = 200
    shape = animal_stencil._shape(name, height)
    w, h = shape.get_size()
    head_band = shape.subsurface(
        pygame.Rect(int(w * 0.72), 0, w - int(w * 0.72), int(h * 0.6)))
    tail_band = shape.subsurface(
        pygame.Rect(0, 0, int(w * 0.28), int(h * 0.6)))
    assert head_band.get_bounding_rect().height > 0
    assert (head_band.get_bounding_rect().height
            >= tail_band.get_bounding_rect().height * 0.5)


# --------------------------------------------------------------------- poses
@pytest.mark.parametrize("name", TRIO)
def test_blink_differs_from_idle_but_only_around_the_eye(traced, name):
    idle = animal_art.animal_sprite(name, 200, "idle")
    blink = animal_art.animal_sprite(name, 200, "blink")
    assert idle.get_size() == blink.get_size()
    diff = sum(1 for x in range(0, idle.get_width(), 3)
               for y in range(0, idle.get_height(), 3)
               if idle.get_at((x, y)) != blink.get_at((x, y)))
    assert diff > 0, "blink is indistinguishable from idle"
    total = (idle.get_width() // 3) * (idle.get_height() // 3)
    assert diff < total * 0.10, "blink changed far more than an eye"


@pytest.mark.parametrize("name", TRIO)
def test_squash_is_shorter_and_still_bottom_aligned(traced, name):
    idle = animal_art.animal_sprite(name, 200, "idle")
    squash = animal_art.animal_sprite(name, 200, "squash")
    assert squash.get_size() == idle.get_size()
    assert squash.get_bounding_rect().height < idle.get_bounding_rect().height
    assert squash.get_bounding_rect().bottom == squash.get_height()


@pytest.mark.parametrize("name", TRIO)
def test_markings_are_identical_every_run(traced, name):
    """Seeded from the name via CRC32, not ``hash()``.

    String hashing is salted per process, so a giraffe seeded that way would
    have different spots after every reboot.
    """
    first = animal_art.animal_sprite(name, 160, "idle")
    copy = first.copy()
    animal_stencil._body_cache.clear()
    animal_art._animal_cache.clear()
    second = animal_art.animal_sprite(name, 160, "idle")
    for x in range(0, copy.get_width(), 7):
        for y in range(0, copy.get_height(), 7):
            assert copy.get_at((x, y)) == second.get_at((x, y))


# ------------------------------------------------------------------ the switch
def test_the_two_art_routes_do_not_share_a_cache_entry(traced):
    """Same name, same height, different art — and different widths."""
    animal_art.set_silhouettes(True)
    traced_sprite = animal_art.animal_sprite("giraffe", 200)
    animal_art.set_silhouettes(False)
    drawn = animal_art.animal_sprite("giraffe", 200)
    assert traced_sprite.get_size() != drawn.get_size() or \
        traced_sprite.get_at((0, 0)) != drawn.get_at((0, 0))
    animal_art.set_silhouettes(True)
    assert animal_art.animal_sprite("giraffe", 200).get_size() == traced_sprite.get_size()


def test_creatures_without_an_outline_are_untouched_by_the_switch(traced):
    """The trial must not change the other 27 animals in any way."""
    animal_art.set_silhouettes(False)
    drawn = animal_art.animal_sprite("elephant", 200)
    animal_art.set_silhouettes(True)
    traced_mode = animal_art.animal_sprite("elephant", 200)
    assert drawn.get_size() == traced_mode.get_size()


def test_switching_off_restores_the_drawn_aspect_ratios():
    animal_art.set_silhouettes(False)
    assert animal_art.aspect("giraffe") == SPECS["giraffe"].aspect
    animal_art.set_silhouettes(True)
    assert animal_art.aspect("giraffe") != SPECS["giraffe"].aspect


# -------------------------------------------------------------------- fallback
def test_a_machine_without_svg_support_falls_back_instead_of_crashing(monkeypatch):
    """SVG is an SDL_image build option, so this is a real deployment risk.

    The Pi is the machine that matters and it was never checked before this
    ran; a hard failure there would be a black screen on every giraffe.
    """
    monkeypatch.setattr(animal_stencil, "_supported", lambda: False)
    assert animal_art.set_silhouettes(True) is False
    assert animal_art.silhouettes_enabled() is False
    sprite = animal_art.animal_sprite("giraffe", 200)
    assert sprite.get_height() == 200, "still draws the old way"


def test_unavailable_is_reported_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(animal_stencil, "_supported", lambda: False)
    with caplog.at_level("WARNING", logger="lilypad.effects.animal_art"):
        animal_art.set_silhouettes(True)
    assert any("unavailable" in r.message for r in caplog.records)


def test_a_broken_asset_disqualifies_the_whole_feature(monkeypatch, tmp_path):
    """One unreadable file must not leave half the cast traced and half drawn."""
    monkeypatch.setattr(animal_stencil, "ASSET_DIR", tmp_path)
    animal_stencil._shape_cache.clear()
    animal_stencil._svg_cache.clear()
    animal_stencil._aspect_cache.clear()
    try:
        assert animal_stencil.available() is False
        assert animal_art.set_silhouettes(True) is False
    finally:
        animal_stencil._shape_cache.clear()
        animal_stencil._svg_cache.clear()
        animal_stencil._aspect_cache.clear()


# --------------------------------------------------------------------- prewarm
def test_prewarm_builds_every_pose_and_both_facings(traced):
    animal_art._animal_cache.clear()
    animal_art._flip_cache.clear()
    assert prewarm(1080) == len(STENCILS) * 3 * 2


def test_prewarm_does_nothing_when_the_feature_is_off():
    animal_art.set_silhouettes(False)
    assert prewarm(1080) == 0


def test_prewarm_uses_the_size_the_crossing_will_ask_for(traced):
    """A prewarm at the wrong height is worse than none — it doubles the work
    and still hitches on the first keypress."""
    from lilypad.effects.animals import AnimalCrossing

    animal_art._animal_cache.clear()
    prewarm(1080)
    for name in STENCILS:
        gait = GAITS.get(name, "walk")
        height = max(48, int(1080 * AnimalCrossing._SIZE.get(gait, 0.34)))
        assert (name, height, "idle", True) in animal_art._animal_cache


# ---------------------------------------------------------------------- config
def test_silhouettes_default_on_and_the_shipped_config_agrees():
    import tomllib
    from pathlib import Path

    assert load_config(None).effects.silhouettes is True
    shipped = tomllib.loads(Path("config.toml").read_text(encoding="utf-8"))
    assert shipped["effects"]["silhouettes"] is True


def test_silhouettes_can_be_turned_off_in_config(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[effects]\nsilhouettes = false\n", encoding="utf-8")
    assert load_config(cfg).effects.silhouettes is False


def test_the_app_sets_the_mode_before_prebuilding_anything():
    import inspect

    from lilypad import __main__ as entry
    src = inspect.getsource(entry.main)
    assert "set_silhouettes(cfg.effects.silhouettes)" in src
    assert src.index("set_silhouettes(") < src.index("prewarm("), \
        "prewarming before the mode is set would cache the wrong art"
