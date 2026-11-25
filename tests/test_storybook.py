# ruff: noqa: RUF059
import logging
import threading
import time
from pathlib import Path

import pygame
import pytest

from lilypad.config import SceneConfig
from lilypad.effects import storybook as sb_mod
from lilypad.effects.base import EffectContext
from lilypad.effects.scenery import PondBackground
from lilypad.effects.storybook import (
    ATTRACT_PERIOD_S,
    DISSOLVE_S,
    HOLD_S,
    READY_TIMEOUT_S,
    Encore,
    Storybook,
    decode_card,
    load_manifest,
)

SIZE = (32, 18)
SHIPPED = Path(sb_mod.__file__).resolve().parents[1] / "assets" / "storybook" / "manifest.toml"


class FakePond:
    def __init__(self, painted=True):
        self.painted = painted
        self.calls = []

    def set_card(self, surface):
        self.calls.append(surface)


def card_surface(letter):
    surface = pygame.Surface(SIZE)
    surface.fill((10 + 9 * (ord(letter) - 65), 40, 80))
    return surface


class Loader:
    """Injected decoder. ``gate`` (an Event) holds every decode until set."""

    def __init__(self, gate=None, fail=()):
        self.gate = gate
        self.fail = set(fail)
        self.calls = []
        self.threads = set()

    def __call__(self, path, size):
        self.calls.append(path.stem)
        self.threads.add(threading.current_thread())
        if self.gate is not None:
            assert self.gate.wait(5)
        if path.stem in self.fail:
            raise OSError("corrupt card")
        return card_surface(path.stem)


def write_manifest(tmp_path, letters="ABCDEF"):
    directory = tmp_path / "storybook"
    directory.mkdir(exist_ok=True)
    rows = ["schema = 1"]
    for letter in letters:
        rows.append(f'[cards.{letter}]\nfile = "{letter}.jpg"\nanimal = "animal-{letter.lower()}"')
    path = directory / "manifest.toml"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def make(tmp_path, mode="both", letters="ABCDEF", loader=None, pond=None):
    loader = loader or Loader()
    pond = pond or FakePond()
    book = Storybook(SIZE, mode, pond=pond, manifest=write_manifest(tmp_path, letters), loader=loader)
    shows = []
    book.on_show.append(lambda *args: shows.append(args))
    return book, pond, loader, shows


def settle(book, until, **kwargs):
    """Let the worker finish: poll with zero-dt updates, bounded."""
    deadline = time.monotonic() + 5
    while not until():
        assert time.monotonic() < deadline, "worker did not finish"
        book.update(0.0, **kwargs)
        time.sleep(0.002)


def run(book, seconds, step=0.05, surface=None, **kwargs):
    surface = surface if surface is not None else pygame.Surface(SIZE)
    for _ in range(round(seconds / step)):
        book.update(step, **kwargs)
        book.draw(surface)


def triple(book, letter, t=10.0, **kwargs):
    for i in range(3):
        book.press(letter, t + i * 0.3, **kwargs)


def show_card(book, letter="C", t=10.0, **kwargs):
    """Press three times and run until the card is installed in the pond."""
    triple(book, letter, t, **kwargs)
    settle(book, lambda: book.showing == letter, **kwargs)
    book.draw(pygame.Surface(SIZE))


@pytest.fixture(autouse=True)
def _close_books(monkeypatch):
    books = []
    original = Storybook.__init__

    def tracking(self, *args, **kwargs):
        original(self, *args, **kwargs)
        books.append(self)

    monkeypatch.setattr(Storybook, "__init__", tracking)
    yield
    for book in books:
        book.close()


# ------------------------------------------------------------------ encore

def test_three_within_the_window_show_and_second_prefetches():
    enc = Encore()
    assert [enc.press("C", 0.0), enc.press("C", 1.0), enc.press("C", 2.0)] == [None, "prefetch", "show"]


def test_gap_over_window_resets_and_boundary_counts():
    enc = Encore()
    assert enc.press("C", 0.0) is None
    assert enc.press("C", 1.2) == "prefetch"      # exactly 1.2 s still counts
    assert enc.press("C", 2.5) is None            # 1.3 s: a fresh run of one
    assert enc.press("C", 3.0) == "prefetch"
    assert enc.press("C", 3.5) == "show"


def test_a_different_key_resets():
    enc = Encore()
    enc.press("C", 0.0)
    enc.press("C", 0.2)
    assert enc.press("D", 0.4) is None
    assert enc.press("C", 0.6) is None
    assert enc.press("C", 0.8) == "prefetch"


def test_after_a_show_the_same_key_needs_a_fresh_run():
    enc = Encore()
    verdicts = [enc.press("C", i * 0.2) for i in range(6)]
    assert verdicts == [None, "prefetch", "show", None, "prefetch", "show"]


def test_none_resets_the_run():
    enc = Encore()
    enc.press("C", 0.0)
    enc.press("C", 0.2)
    enc.press(None, 0.3)
    assert enc.press("C", 0.4) is None


def test_a_non_letter_press_between_letters_breaks_the_run(tmp_path):
    book, *_ = make(tmp_path)
    book.press("c", 1.0)
    book.press("c", 1.2)
    book.press(None, 1.3)                          # F-key, arrow, number: INT2 feeds None
    assert book.press("c", 1.4) is None


# ----------------------------------------------------------------- prefetch

def test_prefetch_starts_on_the_second_press_not_the_first(tmp_path):
    book, pond, loader, _ = make(tmp_path)
    book.press("C", 1.0)
    assert not book.thread_started and loader.calls == []
    book.press("C", 1.3)
    settle(book, lambda: "C" in book.cached_letters)
    assert loader.calls == ["C"]
    assert pond.calls == []                         # prefetch alone shows nothing
    assert loader.threads and threading.main_thread() not in loader.threads


def test_third_press_shows_the_prefetched_card_and_fires_hooks(tmp_path):
    book, pond, loader, shows = make(tmp_path)
    show_card(book, "C")
    assert pond.calls == [book._cache["C"]]
    assert shows == [("C", "animal-c", "encore")]
    assert loader.calls == ["C"]                    # decoded once


def test_hook_errors_never_escape(tmp_path):
    book, pond, *_ = make(tmp_path)
    book.on_show.insert(0, lambda *a: 1 / 0)
    show_card(book, "C")
    assert book.showing == "C" and len(pond.calls) == 1


# ------------------------------------------------------------------ dissolve

def test_dissolve_in_hold_dissolve_out_timing(tmp_path):
    book, pond, *_ = make(tmp_path)
    target = pygame.Surface(SIZE)
    target.fill((200, 0, 0))
    triple(book, "C")
    settle(book, lambda: book.showing == "C")
    assert pond.calls == []                          # the swap happens on the draw
    book.draw(target)
    assert len(pond.calls) == 1 and pond.calls[0] is book._cache["C"]
    assert book._snap.get_alpha() == 255             # first frame is still the old picture
    book.update(DISSOLVE_S / 2)
    book.draw(target)
    assert 120 <= book._snap.get_alpha() <= 135
    book.update(DISSOLVE_S / 2)
    assert not book.dissolving and len(pond.calls) == 1
    # hold: the card stays for HOLD_S, then clears exactly once
    run(book, HOLD_S - 0.6)                          # the hold counts from the start of the dissolve
    assert len(pond.calls) == 1 and book.showing == "C"
    run(book, 0.4)
    assert pond.calls[-1] is None and len(pond.calls) == 2 and book.showing is None
    run(book, DISSOLVE_S + 0.1)
    assert not book.dissolving and len(pond.calls) == 2


def test_swap_without_a_draw_still_happens(tmp_path):
    book, pond, *_ = make(tmp_path)
    triple(book, "C")
    settle(book, lambda: book.showing == "C")
    for _ in range(10):
        book.update(0.05)
    assert len(pond.calls) == 1 and pond.calls[0] is book._cache["C"]


def test_same_card_pressed_again_extends_the_hold(tmp_path):
    book, pond, *_ = make(tmp_path)
    show_card(book, "C")
    run(book, HOLD_S - 1.0)
    triple(book, "C", t=50.0)
    run(book, 2.0)
    assert book.showing == "C"
    run(book, HOLD_S)
    assert book.showing is None


def test_a_new_card_replaces_a_held_one_without_a_gap(tmp_path):
    book, pond, loader, shows = make(tmp_path)
    show_card(book, "C")
    show_card(book, "D", t=20.0)
    assert [c is None for c in pond.calls] == [False, False]
    assert pond.calls[1] is book._cache["D"] and book.showing == "D"
    assert [s[0] for s in shows] == ["C", "D"]
    assert sorted(book.cached_letters) == ["C", "D"]


# -------------------------------------------------------------- slow decode

def test_show_waits_for_a_slow_decode_then_dissolves(tmp_path):
    gate = threading.Event()
    book, pond, loader, shows = make(tmp_path, loader=Loader(gate))
    triple(book, "C")
    run(book, 0.5)
    assert book.showing is None and shows == [] and pond.calls == []
    gate.set()
    settle(book, lambda: book.showing == "C")
    book.draw(pygame.Surface(SIZE))
    assert len(pond.calls) == 1 and len(shows) == 1


def test_show_is_skipped_after_one_second(tmp_path):
    gate = threading.Event()
    book, pond, loader, shows = make(tmp_path, loader=Loader(gate))
    triple(book, "C")
    run(book, READY_TIMEOUT_S + 0.2)
    assert book.showing is None
    gate.set()
    settle(book, lambda: "C" in book.cached_letters)
    run(book, 1.0)
    assert book.showing is None and shows == [] and pond.calls == []


def test_a_stale_pending_show_is_cancelled_by_another_key(tmp_path):
    gate = threading.Event()
    book, pond, loader, shows = make(tmp_path, loader=Loader(gate))
    triple(book, "C")
    book.press("D", 11.5)
    gate.set()
    settle(book, lambda: "C" in book.cached_letters)
    run(book, 0.5)
    assert book.showing is None and shows == []


def test_latest_request_wins_the_single_slot(tmp_path):
    gate = threading.Event()
    book, pond, loader, shows = make(tmp_path, loader=Loader(gate))
    for i, letter in enumerate("ABCD"):
        book.press(letter, 1.0 + i)
        book.press(letter, 1.1 + i)                  # prefetch each in turn
    gate.set()
    settle(book, lambda: not book._inflight)
    assert len(loader.calls) <= 3                    # one in flight plus the newest; the rest were displaced
    assert loader.calls[-1] == "D"


# -------------------------------------------------------------------- party

def test_no_card_is_shown_during_a_party(tmp_path):
    book, pond, loader, shows = make(tmp_path)
    triple(book, "C", party_active=True)
    run(book, 1.0, party_active=True)
    assert book.showing is None and pond.calls == [] and shows == []
    assert loader.calls == []


def test_a_party_starting_mid_card_clears_it_at_once(tmp_path):
    book, pond, *_ = make(tmp_path)
    show_card(book, "C")
    book.update(0.1, party_active=True)
    assert pond.calls[-1] is None and book.showing is None and not book.dissolving
    book.update(0.1)
    assert len(pond.calls) == 2


def test_unpainted_pond_never_shows_or_announces(tmp_path):
    book, pond, loader, shows = make(tmp_path, pond=FakePond(painted=False))
    triple(book, "C")
    run(book, 2.0)
    assert pond.calls == [] and shows == [] and loader.calls == []


# ------------------------------------------------------------ decode failure

def test_decode_failure_is_silent_and_logged_once(tmp_path, caplog):
    book, pond, loader, shows = make(tmp_path, loader=Loader(fail="C"))
    with caplog.at_level(logging.WARNING, logger=sb_mod.__name__):
        triple(book, "C")
        settle(book, lambda: "C" in book._failed)
        run(book, 1.5)
        triple(book, "C", t=30.0)
        run(book, 1.5)
    assert book.showing is None and pond.calls == [] and shows == []
    assert loader.calls == ["C"]                     # never retried
    assert len([r for r in caplog.records if "failed to decode" in r.getMessage()]) == 1


def test_a_missing_card_file_does_not_break_the_book(tmp_path):
    book = Storybook(SIZE, "both", pond=FakePond(), manifest=write_manifest(tmp_path, "C"))
    triple(book, "C")
    settle(book, lambda: "C" in book._failed)
    assert book.showing is None


# ------------------------------------------------------------- memory & close

def test_at_most_two_decoded_cards_are_kept(tmp_path):
    book, pond, *_ = make(tmp_path)
    for i, letter in enumerate("ABCDEF"):
        book.press(letter, 100.0 + i * 3)
        book.press(letter, 100.0 + i * 3 + 0.2)
        settle(book, lambda letter=letter: letter in book.cached_letters or letter in book._failed)
        assert len(book.cached_letters) <= 2
    show_card(book, "F", t=200.0)
    assert len(book.cached_letters) <= 2
    triple(book, "A", t=300.0)
    settle(book, lambda: book.showing == "A")
    book.draw(pygame.Surface(SIZE))
    assert len(book.cached_letters) <= 2


def test_close_stops_the_thread_and_clears_the_card(tmp_path):
    book, pond, loader, _ = make(tmp_path)
    show_card(book, "C")
    thread = book._decoder._thread
    assert thread.is_alive()
    book.close()
    assert not thread.is_alive()
    assert pond.calls[-1] is None and book.cached_letters == []
    book.close()                                     # idempotent
    assert book.press("C", 50.0) in (None, "prefetch", "show")
    triple(book, "C", t=60.0)
    book.update(0.1)
    assert not book.enabled and book.showing is None


def test_close_with_no_thread_is_fine(tmp_path):
    book, *_ = make(tmp_path)
    book.close()
    assert not book.thread_started


# ------------------------------------------------------------------- attract

def test_attract_slideshow_cadence(tmp_path):
    book, pond, loader, shows = make(tmp_path, letters="ABC")
    for _ in range(int(ATTRACT_PERIOD_S - 3)):
        book.attract_tick(1.0, True)
    assert loader.calls == []
    for _ in range(2):
        book.attract_tick(1.0, True)                 # at 6 s: the next card is prefetched
    settle(book, lambda: "A" in book.cached_letters, attract_active=True)
    assert shows == []
    surface = pygame.Surface(SIZE)
    for _ in range(2):
        book.attract_tick(1.0, True)
    book.draw(surface)
    assert shows == [("A", "animal-a", "attract")] and len(pond.calls) == 1
    for _ in range(int(ATTRACT_PERIOD_S)):
        book.attract_tick(1.0, True)
        settle(book, lambda: not book._inflight, attract_active=True)
    book.draw(surface)
    assert [s[0] for s in shows] == ["A", "B"]
    # cards hold until replaced: no dissolve-out in between
    assert None not in pond.calls


def test_attract_leaves_with_a_dissolve_and_is_idempotent_inactive(tmp_path):
    book, pond, loader, shows = make(tmp_path, letters="AB")
    for _ in range(int(ATTRACT_PERIOD_S)):
        book.attract_tick(1.0, True)
        settle(book, lambda: not book._inflight, attract_active=True)
    book.draw(pygame.Surface(SIZE))
    assert book.showing == "A"
    book.attract_tick(0.1, False)
    book.draw(pygame.Surface(SIZE))
    assert pond.calls[-1] is None and book.showing is None
    before = list(pond.calls)
    for _ in range(5):
        book.attract_tick(1.0, False)
        book.draw(pygame.Surface(SIZE))
    assert pond.calls == before
    assert len(shows) == 1


def test_attract_never_runs_in_encore_mode_nor_encore_in_attract_mode(tmp_path):
    (tmp_path / "e").mkdir()
    (tmp_path / "a").mkdir()
    book, pond, loader, shows = make(tmp_path / "e", mode="encore")
    for _ in range(20):
        book.attract_tick(1.0, True)
    assert shows == [] and loader.calls == []
    other, pond2, loader2, shows2 = make(tmp_path / "a", mode="attract")
    assert other.press("C", 1.0) is None
    triple(other, "C", t=5.0)
    run(other, 2.0)
    assert shows2 == [] and loader2.calls == []


def test_an_attract_card_does_not_block_an_encore_show(tmp_path):
    book, pond, *_ = make(tmp_path, letters="ABC")
    for _ in range(int(ATTRACT_PERIOD_S)):
        book.attract_tick(1.0, True)
        settle(book, lambda: not book._inflight, attract_active=True)
    book.draw(pygame.Surface(SIZE))
    assert book.showing == "A"
    triple(book, "C")
    settle(book, lambda: book.showing == "C")
    assert book._source == "encore"


# ----------------------------------------------------------------------- off

def test_off_creates_nothing(tmp_path):
    loader = Loader()
    pond = FakePond()
    book = Storybook(SIZE, "off", pond=pond, manifest=write_manifest(tmp_path), loader=loader)
    assert book._cards == {} and book._encore is None and book._decoder is None
    assert not book.enabled
    surface = pygame.Surface(SIZE)
    surface.fill((1, 2, 3))
    for i in range(5):
        assert book.press("C", float(i) * 0.1) is None
        book.update(0.1, attract_active=True)
        book.attract_tick(10.0, True)
        book.draw(surface)
    book.close()
    assert pond.calls == [] and loader.calls == [] and not book.thread_started
    assert surface.get_at((0, 0))[:3] == (1, 2, 3)
    assert not any(t.name == "storybook-decoder" for t in threading.enumerate())


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        Storybook(SIZE, "sometimes")


def test_the_shipped_manifest_is_empty_and_inert():
    assert SHIPPED.is_file()
    assert load_manifest(SHIPPED) == {}
    book = Storybook(SIZE, "both", pond=FakePond(), manifest=SHIPPED)
    assert not book.enabled
    triple(book, "C")
    book.update(1.0, attract_active=True)
    assert not book.thread_started


# ------------------------------------------------------------------ manifest

def test_manifest_rows_and_validation(tmp_path, caplog):
    path = tmp_path / "manifest.toml"
    path.write_text(
        'schema = 1\n[cards.A]\nfile = "A.jpg"\nanimal = "alligator"\n'
        '[cards.b]\nfile = "sub/B.jpg"\n'
        '[cards.AB]\nfile = "x.jpg"\n[cards.C]\nfile = "../C.jpg"\n[cards.D]\nanimal = "x"\n',
        encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=sb_mod.__name__):
        cards = load_manifest(path)
    assert list(cards) == ["A", "B"]
    assert cards["A"].path == tmp_path / "A.jpg" and cards["A"].animal == "alligator"
    assert cards["B"].path == tmp_path / "sub" / "B.jpg" and cards["B"].animal is None
    assert len(caplog.records) == 3


@pytest.mark.parametrize("body", ["schema = 2\n[cards.A]\nfile = \"A.jpg\"", "[cards.A]\nfile = \"A.jpg\"",
                                  "not toml ((", "schema = 1\ncards = 3"])
def test_unusable_manifests_mean_no_cards(tmp_path, body):
    path = tmp_path / "manifest.toml"
    path.write_text(body, encoding="utf-8")
    assert load_manifest(path) == {}
    assert load_manifest(tmp_path / "missing.toml") == {}


def test_decode_card_scales_to_the_screen(tmp_path):
    source = pygame.Surface((8, 8))
    source.fill((200, 10, 10))
    file = tmp_path / "A.png"
    pygame.image.save(source, file)
    card = decode_card(file, SIZE)
    assert card.get_size() == SIZE and card.get_at((5, 5))[:3] == (200, 10, 10)
    assert card.get_flags() & pygame.SRCALPHA == 0


# ------------------------------------------------------- real painted pond

def make_art(root):
    world = root / "world"
    world.mkdir()
    plate = pygame.Surface((100, 50))
    plate.fill((10, 10, 20))
    pygame.image.save(plate, world / "plate.png")
    for name, height in (("far", 15), ("near", 11)):
        strip = pygame.Surface((104, height), pygame.SRCALPHA)
        for x in range(104):
            pygame.draw.line(strip, (x, 90, 100, 255 if name == "far" else 128), (x, 0), (x, height - 1))
        pygame.image.save(strip, world / f"{name}.png")
    (world / "manifest.toml").write_text(
        '[moods.m0]\norder=0\nplate="plate.png"\nfar_shore="far.png"\nnear_water="near.png"\n',
        encoding="utf-8")


def rgb(surface):
    return pygame.image.tobytes(surface, "RGB")


@pytest.mark.parametrize("flat", [False, True])
def test_dissolve_is_continuous_over_a_real_painted_pond(tmp_path, flat):
    import random
    make_art(tmp_path)
    size = (100, 50)
    context = EffectContext(size=size, rng=random.Random(5))
    if flat:
        context.scale = 0.4
    pond = PondBackground(context, SceneConfig(fireflies=False), root=tmp_path)
    assert pond.painted
    card = pygame.Surface(size)
    card.fill((220, 40, 40))

    def frame(book=None):
        surface = pygame.Surface(size)
        pond.draw(surface)
        if book is not None:
            book.draw(surface)
        return surface

    plain = rgb(frame())
    book = Storybook(size, "both", pond=pond, manifest=write_manifest(tmp_path, "C"),
                     loader=lambda path, s: card)
    triple(book, "C")
    settle(book, lambda: book.showing == "C")
    swap_frame = rgb(frame(book))
    assert swap_frame == plain                       # no pop on the swap frame
    book.update(DISSOLVE_S / 2)
    mid = rgb(frame(book))
    assert mid != plain
    book.update(DISSOLVE_S)
    held = rgb(frame(book))
    assert held != plain and held == rgb(frame())    # dissolve done: the pond alone shows the page
    # a press drawn on top of the card is simply drawn: the card never hides or queues anything
    surface = frame(book)
    surface.set_at((3, 3), (1, 2, 3))
    assert surface.get_at((3, 3))[:3] == (1, 2, 3)
    run(book, HOLD_S + 0.1, surface=pygame.Surface(size))
    # the out-dissolve begins on the old frame and ends on the plain pond
    assert rgb(frame()) == plain
    book.close()
