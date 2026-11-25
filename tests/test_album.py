"""Sticker album: first sightings, strip timing, attract collection, portraits."""

import random

import pygame
import pytest

from lilypad.effects import album, animal_art, animals, assets, painted
from lilypad.effects.album import Album, create_album, head_rect

SIZE = (640, 360)          # strip 36 px high, stickers 32 px: cheap and still scaled


@pytest.fixture
def art(tmp_path, monkeypatch):
    """A synthetic painted cast in a temp asset root. Nothing real is read."""
    monkeypatch.setenv("LILYPAD_ART_DIR", str(tmp_path))
    directory = tmp_path / "painted"
    directory.mkdir()
    (directory / "manifest.toml").write_text("schema = 1\n", encoding="utf-8")
    previous = animal_art._art_mode
    album.clear_cache()
    animal_art.set_art_mode("painted", root=tmp_path)
    yield tmp_path
    album.clear_cache()
    painted.configure(assets.asset_root(kiosk=True))
    animal_art.set_art_mode(previous, root=assets.asset_root(kiosk=True))


@pytest.fixture
def drawn():
    previous = animal_art._art_mode
    album.clear_cache()
    animal_art.set_art_mode("drawn")
    yield
    album.clear_cache()
    animal_art.set_art_mode(previous)


def add_animal(root, name, *, width=80, height=40, eye=(0.8, 0.2)):
    """Paint the head square solid red, everything else transparent."""
    folder = root / "painted" / name
    folder.mkdir()
    rect = head_rect((width, height), eye)
    for pose in ("idle", "blink"):
        image = pygame.Surface((width, height), pygame.SRCALPHA)
        image.fill((250, 20, 10, 255), rect)
        pygame.image.save(image, folder / f"{pose}.png")
    view = "side" if animal_art.faces_right(name) else "front"
    with (root / "painted" / "manifest.toml").open("a", encoding="utf-8") as stream:
        stream.write(
            f'\n[animals.{name}]\nview = "{view}"\nnative_height = {height}\n'
            f'frames = {{ idle = "{name}/idle.png", blink = "{name}/blink.png" }}\n'
            f'anchor = [0.5, 1.0]\neye_at = [{eye[0]}, {eye[1]}]\nback_at = [0.4, 0.3]\n'
            'source_hash = "sha256:fixture"\nprompt_id = "fixture"\n'
        )


def run(a, seconds, dt=1 / 30):
    for _ in range(round(seconds / dt)):
        a.update(dt)


def pixels(surface):
    return pygame.image.tobytes(surface, "RGBA")


def blank(size=SIZE):
    surface = pygame.Surface(size, pygame.SRCALPHA)
    surface.fill((5, 5, 5, 255))
    return surface


# ----------------------------------------------------------------- portraits

@pytest.mark.parametrize("canvas,eye", [
    ((80, 40), (0.8, 0.2)), ((80, 40), (0.0, 0.0)), ((80, 40), (1.0, 1.0)),
    ((273, 367), (0.708, 0.177)), ((10, 400), (0.5, 0.5)), ((400, 10), (0.9, 0.1)),
    ((1, 1), (0.5, 0.5)),
])
def test_head_square_stays_inside_the_canvas(canvas, eye):
    rect = head_rect(canvas, eye)
    assert rect.w == rect.h >= 1
    assert 0 <= rect.left and rect.right <= canvas[0]
    assert 0 <= rect.top and rect.bottom <= canvas[1]
    assert rect.w <= min(canvas)


def test_head_square_is_sized_from_canvas_height_and_centred_on_the_eye():
    rect = head_rect((1000, 400), (0.5, 0.5), 0.5)
    assert rect.size == (200, 200) and rect.center == (500, 200)


def test_painted_portrait_is_the_head_crop_at_the_asked_size(art, monkeypatch):
    add_animal(art, "giraffe")
    monkeypatch.setattr(painted, "build",
                        lambda *a, **k: pytest.fail("portrait resized shared art"))
    p = album.portrait("giraffe", 96)
    assert p.get_size() == (96, 96)
    assert album.portrait("giraffe", 96) is p                       # cached
    assert p.get_at((48, 48)) == (250, 20, 10, 255)                 # the red head square
    assert p.get_at((0, 0)).a == 0                                  # rounded corner is clear


def test_portrait_does_not_disturb_the_engines_frames(art):
    add_animal(art, "giraffe")
    before = painted.build("giraffe", 40)
    album.portrait("giraffe", 96)
    assert painted.build("giraffe", 40) is before


def test_no_painted_art_gives_a_drawn_fallback(drawn):
    p = album.portrait("giraffe", 96)
    assert p.get_size() == (96, 96)
    assert any(p.get_at((x, y)).a for x in range(96) for y in range(96))
    assert album._mode("giraffe") == "drawn"


def test_a_missing_painted_entry_falls_back_per_animal(art):
    add_animal(art, "giraffe")
    assert album._mode("giraffe") == "painted" and album._mode("lion") == "drawn"
    assert album.portrait("lion", 64).get_size() == (64, 64)


def test_unknown_creature_still_gets_a_letter_tile(drawn):
    p = album.portrait("notananimal", 64)
    assert p.get_size() == (64, 64) and p.get_at((32, 32)).a == 255


def test_corrupt_painted_frame_still_gives_a_sticker(art, monkeypatch):
    add_animal(art, "giraffe")

    def boom(name):
        raise OSError("bad frame")

    monkeypatch.setattr(album, "_painted_crop", boom)
    assert album.portrait("giraffe", 64).get_size() == (64, 64)


def test_dim_portrait_is_darker_and_fainter(drawn):
    lit, dim = album.portrait("lion", 64), album.dim_portrait("lion", 64)
    assert dim is not lit and dim.get_size() == lit.get_size()
    assert dim.get_at((32, 32)).a < lit.get_at((32, 32)).a
    assert sum(dim.get_at((32, 32))[:3]) < sum(lit.get_at((32, 32))[:3])


# --------------------------------------------------------------------- album

def test_first_sighting_adds_a_sticker_and_repeats_do_not(drawn):
    a = Album(SIZE)
    assert a.note_animal("lion", (100, 100)) is True
    assert a.note_animal("lion", (300, 200)) is False
    assert a.note_animal("owl", (300, 200)) is True
    assert a.seen == ["lion", "owl"]
    run(a, 1.0)
    assert a.landed == ["lion", "owl"] and not a._fliers


def test_sticker_flies_for_half_a_second_before_landing(drawn):
    a = Album(SIZE)
    a.note_animal("lion", (100, 100))
    run(a, 0.4)
    assert a.landed == [] and len(a._fliers) == 1
    run(a, 0.2)
    assert a.landed == ["lion"]


def test_flier_is_drawn_between_the_animal_and_its_slot(drawn):
    a = Album(SIZE)
    a.note_animal("lion", (500, 300))
    surf = blank()
    a.draw(surf)
    at_start = pixels(surf)
    run(a, 0.25)
    mid = blank()
    a.draw(mid)
    assert pixels(mid) != at_start
    sx, sy, edge = a._slot_for(0)
    assert a._fliers[0].start == (500, 300) and sx + edge / 2 < 500 and sy + edge / 2 < 300
    # Half way through the ease the sticker is exactly half way along its path.
    k = album._ease(a._t / album.FLIGHT_SECONDS)
    cx = 500 + (sx + edge / 2 - 500) * k
    cy = 300 + (sy + edge / 2 + a._offset - 300) * k
    assert mid.get_at((round(cx), round(cy))) != (5, 5, 5, 255)


def test_strip_shows_for_two_seconds_then_tucks_up(drawn):
    a = Album(SIZE)
    assert not a.visible
    a.note_animal("lion", (100, 100))
    run(a, 0.3)
    assert a.visible and a._offset == 0
    run(a, 1.6)                                    # t = 1.9 s: still down
    assert a._offset == 0
    run(a, 0.2)                                    # t = 2.1 s: tucking away
    assert a.visible and a._offset < 0
    run(a, 0.5)
    assert not a.visible and a._offset == -a.strip_h


def test_a_new_sticker_restarts_the_two_second_hold(drawn):
    a = Album(SIZE)
    a.note_animal("lion", (100, 100))
    run(a, 1.5)
    a.note_animal("owl", (200, 100))
    run(a, 1.9)
    assert a._offset == 0
    run(a, 1.0)
    assert not a.visible


def test_hidden_strip_draws_nothing(drawn):
    a = Album(SIZE)
    a.note_animal("lion", (100, 100))
    run(a, 4.0)
    surf = blank()
    before = pixels(surf)
    a.draw(surf)
    assert pixels(surf) == before


def test_attract_mode_shows_the_whole_collection_and_hides_when_it_ends(drawn):
    a = Album(SIZE)
    for i, name in enumerate(("lion", "owl", "fox")):
        a.note_animal(name, (100 * i, 100))
        run(a, 0.6)
    run(a, 3.0)
    assert not a.visible
    a.set_attract(True)
    run(a, 10.0)
    assert a.visible and a._offset == 0
    shown, edge, step, y = a._layout()
    assert shown == ["lion", "owl", "fox"]
    a.set_attract(False)
    run(a, 1.0)
    assert not a.visible


def test_attract_with_an_empty_collection_stays_hidden(drawn):
    a = Album(SIZE)
    a.set_attract(True)
    run(a, 5.0)
    assert not a.visible
    surf = blank()
    before = pixels(surf)
    a.draw(surf)
    assert pixels(surf) == before


def test_whole_cast_fits_the_strip_in_attract_mode(drawn):
    a = Album((1920, 1080))
    for name in list(animals.ANIMAL_LETTERS.values()) + ["stegosaurus", "triceratops",
                                                         "brachiosaurus", "pterodactyl"]:
        a.landed.append(name)
        a._known.add(name)
    a.set_attract(True)
    shown, edge, step, y = a._layout()
    assert len(shown) == 30
    assert a.margin + (len(shown) - 1) * step + edge <= 1920 - a.margin
    assert y + edge <= a.strip_h and edge >= 8


def test_recent_layout_caps_at_what_fits(drawn):
    a = Album((1920, 1080))
    assert (a.strip_h, a.px) == (110, 96)
    assert a.cap == 17                              # 17 * 96 + 16 * 10 <= 1872
    names = list(animals.ANIMAL_LETTERS.values())
    a.landed = names[:25]
    shown, edge, step, y = a._layout()
    assert shown == names[8:25] and edge == 96
    assert a.margin + 16 * step + edge <= 1920 - a.margin


def test_strip_scales_with_the_screen(drawn):
    small = Album((960, 540))
    assert (small.strip_h, small.px) == (55, 48)


def test_drawn_bar_when_there_is_no_painted_strip(drawn, tmp_path):
    a = Album(SIZE, root=tmp_path)                  # no album folder at all
    assert a.painted_strip is False and a._bg.get_size() == (SIZE[0], a.strip_h)


def test_painted_strip_is_used_when_the_manifest_names_it(drawn, tmp_path):
    folder = tmp_path / "album"
    folder.mkdir()
    image = pygame.Surface((20, 4))
    image.fill((200, 30, 30))
    pygame.image.save(image, folder / "strip.png")
    (folder / "manifest.toml").write_text('schema = 1\nstrip = "strip.png"\n', encoding="utf-8")
    a = Album(SIZE, root=tmp_path)
    assert a.painted_strip is True
    a.landed = ["lion"]
    a._offset = 0
    surf = blank()
    a.draw(surf)
    assert surf.get_at((SIZE[0] - 5, 5))[:3] == (200, 30, 30)


@pytest.mark.parametrize("body", [
    "schema = 2\nstrip = 'strip.png'\n",
    "this is = not [toml",
    'schema = 1\nstrip = "../escape.png"\n',
    'schema = 1\nstrip = "missing.png"\n',
])
def test_bad_or_missing_album_manifests_fall_back_to_the_drawn_bar(drawn, tmp_path, body):
    folder = tmp_path / "album"
    folder.mkdir()
    (folder / "manifest.toml").write_text(body, encoding="utf-8")
    a = Album(SIZE, root=tmp_path)
    assert a.painted_strip is False and a._bg.get_width() == SIZE[0]


def test_unreadable_painted_strip_falls_back(drawn, tmp_path):
    folder = tmp_path / "album"
    folder.mkdir()
    (folder / "strip.webp").write_bytes(b"not an image")
    (folder / "manifest.toml").write_text('schema = 1\nstrip = "strip.webp"\n', encoding="utf-8")
    assert Album(SIZE, root=tmp_path).painted_strip is False


def test_shipped_album_manifest_is_header_only():
    assert album.album_assets() == {}


def test_legacy_config_creates_nothing(drawn):
    assert create_album(False, SIZE) is None
    assert isinstance(create_album(True, SIZE), Album)


def test_album_is_deterministic_and_never_uses_the_random_module(drawn, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("album must not draw random numbers")

    for fn in ("random", "uniform", "choice", "randint", "shuffle", "gauss"):
        monkeypatch.setattr(random, fn, forbidden)

    def make():
        a = Album(SIZE)
        a.note_animal("lion", (300, 200))
        run(a, 0.45)
        surf = blank()
        a.draw(surf)
        return pixels(surf)

    assert make() == make()


def test_huge_frame_hitch_does_not_teleport_the_animation(drawn):
    a = Album(SIZE)
    a.note_animal("lion", (100, 100))
    a.update(30.0)                                  # a long stall counts as one short frame
    assert a.landed == [] and len(a._fliers) == 1


def test_prewarm_builds_portraits_without_a_sighting(drawn):
    a = Album(SIZE)
    a.prewarm(["lion", "owl"])
    assert ("lion", a.px, "drawn") in album._portraits and a.seen == []
