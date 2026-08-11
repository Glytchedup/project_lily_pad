"""Traced-outline animals — every side-on creature in the cast.

Two things make this worth its own suite. The art comes from files, so it can
go missing in a way generated art cannot. And it is *optional* — a machine
whose SDL_image lacks SVG support has to fall back rather than crash, and the
fallback is exactly the sort of path nobody exercises by hand.

Most of these are parametrised over the whole cast rather than spot-checking a
few, because the per-animal data (`eye_at`, `faces_left`) is hand-found by
looking at pictures, and that is precisely the kind of data where one row is
quietly wrong.
"""

import pygame
import pytest

from lilypad.config import load as load_config
from lilypad.effects import animal_art, animal_stencil
from lilypad.effects.animal_specs import SPECS, STENCILS
from lilypad.effects.animals import (
    ANIMAL_LETTERS,
    DINOSAURS,
    GAITS,
    PEEKABOO_CAST,
    prewarm,
)

CAST = tuple(sorted(STENCILS))


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
def test_every_side_on_animal_has_an_outline():
    """The conversion is meant to be complete, not partial.

    A half-converted cast is the worst outcome: traced and drawn animals side
    by side look like two different games.
    """
    missing = sorted(set(SPECS) - set(STENCILS))
    assert missing == [], f"still drawn from primitives: {missing}"


def test_the_front_on_farm_animals_are_deliberately_left_alone():
    """cow, duck, pig and sheep peek up from the bottom instead of crossing.

    They are drawn front-on, so there is no side view to trace and no way to
    mirror them. Converting them would mean rebuilding their performance, not
    just their art — see PLAN.md D16.
    """
    for name in PEEKABOO_CAST:
        assert name not in STENCILS


@pytest.mark.parametrize("name", CAST)
def test_every_stencil_creature_is_a_real_member_of_the_cast(name):
    """A typo here would ship art for an animal nobody can summon."""
    assert name in SPECS, "needs an AnimalSpec for its colours"
    assert name in set(ANIMAL_LETTERS.values()) | set(DINOSAURS)


def test_every_letter_and_dinosaur_still_has_a_creature():
    for letter, name in ANIMAL_LETTERS.items():
        assert name in STENCILS or name in PEEKABOO_CAST, letter
    for dino in DINOSAURS:
        assert dino in STENCILS, dino


@pytest.mark.parametrize("name", CAST)
def test_the_artwork_is_actually_present(name):
    path = animal_stencil.ASSET_DIR / STENCILS[name].file
    assert path.is_file(), f"{path} missing — did package-data drop it?"
    assert path.read_bytes().lstrip().startswith(b"<?xml")


def test_no_two_creatures_share_an_outline_file():
    """Horse, unicorn and zebra all come from horse photographs; if two of them
    ever pointed at the same file they would be the same animal in two colours."""
    files = [s.file for s in STENCILS.values()]
    assert len(files) == len(set(files)), "duplicate outline file"


@pytest.mark.parametrize("name", CAST)
def test_every_outline_is_credited(name):
    """Licences are per-image, not per-site. An uncredited file is unaudited."""
    credits = (animal_stencil.ASSET_DIR / "CREDITS.md").read_text(encoding="utf-8")
    assert STENCILS[name].file in credits


def test_the_credits_claim_public_domain_for_everything():
    """Only the table rows are checked — the prose above it names the licences
    we refuse on purpose, and matching that would fail on our own warning."""
    credits = (animal_stencil.ASSET_DIR / "CREDITS.md").read_text(encoding="utf-8")
    rows = [ln for ln in credits.splitlines()
            if ln.startswith("| `") and ln.endswith("`|") is False and ".svg`" in ln]
    assert len(rows) == len(STENCILS), f"{len(rows)} credit rows for {len(STENCILS)} files"
    for row in rows:
        assert "CC0 1.0" in row, row
        for bad in ("NonCommercial", "CC-BY-NC", "ShareAlike", "CC-BY-SA", "CC-BY-3"):
            assert bad not in row, f"{bad} licence must never enter this repo: {row}"


# ------------------------------------------------------------------ geometry
@pytest.mark.parametrize("name", CAST)
def test_sprite_is_exactly_the_height_asked_for(traced, name):
    for height in (64, 180, 301):
        assert animal_art.animal_sprite(name, height).get_height() == height


@pytest.mark.parametrize("name", CAST)
def test_sprite_fills_its_box_with_no_dead_margin(traced, name):
    """The SVG canvas may pad the animal; the sprite box must be the animal.

    Everything that positions a creature on screen — the ground line, the fly
    band, the off-screen start — treats the sprite box as the creature. A
    transparent margin reads as an animal floating above the bank.
    """
    sprite = animal_art.animal_sprite(name, 240)
    bounds = sprite.get_bounding_rect()
    # A horn or a tusk is a polygon with an anti-aliased point, so its very tip
    # does not reach the reserved edge exactly. A few pixels on two of
    # twenty-six sprites; the strict version still guards the other twenty-four.
    slack = 6 if STENCILS[name].accessory else 2
    assert bounds.width >= sprite.get_width() - slack
    assert bounds.height >= sprite.get_height() - slack


@pytest.mark.parametrize("name", CAST)
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


@pytest.mark.parametrize("name", CAST)
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


ACCESSORIED = tuple(n for n in CAST if STENCILS[n].accessory)


def test_the_two_creatures_that_need_an_invented_part_have_one():
    """A unicorn is a horse plus a horn and a narwhal is a whale plus a tusk.

    Both outlines come from real animals — there is no unicorn to trace, and
    every public-domain narwhal is either tuskless or drawn from above. Without
    the accessory these are a white horse and a small whale, and the app
    already has a horse and a whale.
    """
    assert STENCILS["unicorn"].accessory == "horn"
    assert STENCILS["narwhal"].accessory == "tusk"


@pytest.mark.parametrize("name", ACCESSORIED)
def test_accessories_attach_to_the_body(traced, name):
    height = 240
    stroke = animal_stencil._stroke_px(height)
    shape = animal_stencil._shape(name, height - 2 * stroke)
    w, h = shape.get_size()
    ax, ay = STENCILS[name].accessory_at
    assert shape.get_at((min(w - 1, int(w * ax)), min(h - 1, int(h * ay))))[3] > 0, \
        f"{name} accessory floats free of the animal"


@pytest.mark.parametrize("name", ACCESSORIED)
def test_the_whole_accessory_fits_inside_the_sprite(traced, name):
    """The tip is the whole point, and the tip is what gets clipped.

    Sprites are cropped tight to the outline, so anything drawn beyond it is
    silently sliced off at the surface edge. Both accessories shipped as stubs
    that way — about a third of each gone, including the point — and every test
    still passed, because they only asked whether *something* had been drawn.
    """
    height = 240
    painted = animal_stencil._painted(name, height)
    st = STENCILS[name]
    ax, ay = st.accessory_at
    left, top, right, bottom = animal_stencil._accessory_box(
        st.accessory, painted.sw * ax, painted.sh * ay, height)
    box = pygame.Rect(int(painted.ox + left), int(painted.oy + top),
                      max(1, int(right - left)), max(1, int(bottom - top)))
    assert painted.surface.get_rect().contains(box), (
        f"{name}'s {st.accessory} runs outside its sprite: "
        f"{box} does not fit {painted.surface.get_rect()}")


@pytest.mark.parametrize("name", ACCESSORIED)
def test_the_accessory_is_actually_painted_at_its_tip(traced, name):
    """Reserving the space is not the same as filling it."""
    height = 240
    painted = animal_stencil._painted(name, height)
    st = STENCILS[name]
    ax, ay = st.accessory_at
    tx, ty = animal_stencil._accessory_tip(
        st.accessory, painted.sw * ax, painted.sh * ay, height)
    tip = (int(painted.ox + tx), int(painted.oy + ty))

    assert painted.surface.get_rect().collidepoint(tip), (
        f"{name}'s {st.accessory} points at {tip}, outside "
        f"{painted.surface.get_rect()}")
    near = pygame.Rect(tip[0] - 4, tip[1] - 4, 9, 9).clip(
        painted.surface.get_rect())
    opaque = sum(1 for x in range(near.left, near.right)
                 for y in range(near.top, near.bottom)
                 if painted.surface.get_at((x, y))[3] > 0)
    assert opaque > 3, f"{name}'s {st.accessory} tip is empty"


@pytest.mark.parametrize("name", ACCESSORIED)
def test_the_accessory_reserves_room(traced, name):
    """Guards against a silently-ignored accessory name.

    An unknown kind returns a zero-size box, which reserves nothing, which is
    exactly how both of these ended up cropped. Paired with the tip test above:
    this one catches a name the geometry doesn't know, that one catches a name
    the drawing doesn't know.
    """
    st = STENCILS[name]
    painted = animal_stencil._painted(name, 240)
    margins = animal_stencil._accessory_margin(st, 240, painted.sw, painted.sh)
    assert any(m > 0 for m in margins), \
        f"{name}'s {st.accessory} reserved no room: {margins}"


#: Radially symmetric — a jellyfish has no front, so its eye sits on the bell.
NO_FACING = frozenset({"jellyfish"})


@pytest.mark.parametrize("name", tuple(n for n in CAST if n not in NO_FACING))
def test_the_eye_is_forward_of_centre(traced, name):
    """Catches the one mistake this data actually invites.

    PhyloPic outlines point either way, so each row carries a ``faces_left``
    flag and an ``eye_at`` found by looking at the *flipped* image. Change one
    without the other and the eye lands on the animal's backside — which
    happened twice while this cast was being assembled, and looks fine in the
    table. Since the sprite always ends up facing right, a head is always in
    the forward half.
    """
    ex = STENCILS[name].eye_at[0]
    assert ex >= 0.55, f"{name} eye at x={ex} is behind the middle — flipped?"


# --------------------------------------------------------------------- poses
@pytest.mark.parametrize("name", CAST)
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


@pytest.mark.parametrize("name", CAST)
def test_squash_is_shorter_and_still_bottom_aligned(traced, name):
    idle = animal_art.animal_sprite(name, 200, "idle")
    squash = animal_art.animal_sprite(name, 200, "squash")
    assert squash.get_size() == idle.get_size()
    assert squash.get_bounding_rect().height < idle.get_bounding_rect().height
    # A few pixels of slack: squash is a smoothscale, and where a sprite ends
    # in a hairline (the narwhal's tail fluke) the averaged bottom rows can
    # come out fully transparent. Invisible in play, and swimmers never squash
    # anyway — only hops use this pose.
    assert squash.get_bounding_rect().bottom >= squash.get_height() - 6


@pytest.mark.parametrize("name", CAST)
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


@pytest.mark.parametrize("name", sorted(PEEKABOO_CAST))
def test_the_farm_four_are_untouched_by_the_switch(traced, name):
    """Whatever happens to the side-on cast, the peekaboo animals are the same
    hand-drawn art they always were."""
    animal_art.set_silhouettes(False)
    drawn = animal_art.animal_sprite(name, 200)
    animal_art.set_silhouettes(True)
    traced_mode = animal_art.animal_sprite(name, 200)
    assert drawn.get_size() == traced_mode.get_size()
    assert drawn.get_at((drawn.get_width() // 2, drawn.get_height() // 2)) == \
        traced_mode.get_at((drawn.get_width() // 2, drawn.get_height() // 2))


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
