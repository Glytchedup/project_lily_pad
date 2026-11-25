"""The exit-path summary card: must always come back, quickly, and never raise."""

import time

import pygame
import pytest

from lilypad import summary
from lilypad.effects import album, animal_art
from lilypad.input.mapper import classify
from lilypad.stats import PlayStats

SIZE = (480, 270)


class FakeClock:
    """A clock the test moves: ``sleep`` advances it, ``tick`` optionally per call."""

    def __init__(self, start=1000.0, tick=0.0):
        self.t, self.tick, self.calls = start, tick, 0

    def __call__(self):
        self.calls += 1
        self.t += self.tick
        return self.t

    def sleep(self, seconds):
        self.t += seconds


@pytest.fixture(autouse=True)
def drawn_art(monkeypatch):
    previous = animal_art._art_mode
    animal_art.set_art_mode("drawn")
    flips = []
    monkeypatch.setattr(pygame.display, "flip", lambda: flips.append(1))
    yield flips
    animal_art.set_art_mode(previous)


@pytest.fixture
def screen():
    return pygame.Surface(SIZE)


def busy_stats():
    s = PlayStats()
    for i, ch in enumerate("abcdefghijklmnopq"):
        s.on_action(classify(ch), i * 10.0)
    s.on_animal("lion", 5.0)
    s.on_animal("lion", 6.0)
    s.on_animal("owl", 7.0)
    s.on_party(8.0)
    return s


def call(screen, stats, clock, deadline_in=8.0, poll=lambda: False, **kw):
    return summary.run_summary(screen, stats, clock.t + deadline_in, poll, clock,
                               sleep=clock.sleep, **kw)


def test_returns_at_the_deadline_and_never_later_than_half_a_second_after(screen, drawn_art):
    clock = FakeClock()
    deadline = clock.t + 8.0
    summary.run_summary(screen, busy_stats(), deadline, lambda: False, clock, sleep=clock.sleep)
    assert deadline <= clock.t <= deadline + 0.5
    assert len(drawn_art) >= 8 * summary.FPS * 0.9          # it really showed the card


def test_overshoot_stays_bounded_when_every_clock_read_costs_time(screen):
    clock = FakeClock(tick=0.03)                             # slow machine: each call burns 30 ms
    deadline = clock.t + 3.0
    summary.run_summary(screen, busy_stats(), deadline, lambda: False, clock, sleep=clock.sleep)
    assert deadline <= clock.t <= deadline + 0.5


def test_already_past_deadline_returns_without_drawing(screen, drawn_art):
    clock = FakeClock()
    summary.run_summary(screen, busy_stats(), clock.t - 1, lambda: False, clock, sleep=clock.sleep)
    assert drawn_art == [] and clock.t == 1000.0


def test_quit_flag_returns_within_one_frame(screen, drawn_art):
    clock = FakeClock()
    polls = []

    def poll():
        polls.append(clock.t)
        return clock.t >= 1000.0 + 1.0                      # SIGTERM arrives 1 s in

    call(screen, busy_stats(), clock, poll=poll)
    assert 1001.0 <= clock.t <= 1001.0 + 1 / summary.FPS + 1e-6
    assert polls[-1] >= 1001.0          # it stopped on the first poll that said so


def test_quit_flag_already_set_never_draws(screen, drawn_art):
    clock = FakeClock()
    call(screen, busy_stats(), clock, poll=lambda: True)
    assert drawn_art == [] and clock.t == 1000.0


def test_quit_during_setup_abandons_the_build(screen, drawn_art, monkeypatch):
    clock = FakeClock()
    flag = {"n": 0}

    def poll():
        flag["n"] += 1
        return flag["n"] > 3                                 # flips true while portraits build

    built = []
    real = album.portrait
    monkeypatch.setattr(album, "portrait", lambda *a, **k: built.append(a[0]) or real(*a, **k))
    call(screen, busy_stats(), clock, poll=poll)
    assert drawn_art == [] and len(built) <= 3               # it stopped at once, not after 27


def test_each_frame_polls_so_the_input_grab_is_kept_alive(screen):
    clock = FakeClock()
    polls = []
    call(screen, busy_stats(), clock, poll=lambda: polls.append(1) or False)
    assert len(polls) >= 8 * summary.FPS * 0.9


def test_keys_are_ignored_poll_is_a_quit_flag_not_an_event_list(screen):
    """INT2 must pass a bool wrapper; an empty event list is falsy, a falsy flag keeps going."""
    clock = FakeClock()
    call(screen, busy_stats(), clock, deadline_in=2.0, poll=lambda: [])
    assert clock.t >= 1002.0


class Boom(Exception):
    pass


def test_exception_in_stats_still_returns_promptly(screen):
    class BadStats(PlayStats):
        @property
        def letters_found(self):
            raise Boom("stats exploded")

    clock = FakeClock()
    call(screen, BadStats(), clock)                          # must not raise
    assert clock.t - 1000.0 <= 0.5


def test_exception_from_poll_still_returns(screen):
    clock = FakeClock()

    def poll():
        raise Boom("grab died")

    call(screen, busy_stats(), clock, poll=poll)
    assert clock.t - 1000.0 <= 0.5


def test_exception_from_flip_returns_without_raising(screen, monkeypatch, drawn_art):
    def flip():
        raise pygame.error("display lost")

    monkeypatch.setattr(pygame.display, "flip", flip)
    clock = FakeClock()
    call(screen, busy_stats(), clock)
    assert clock.t - 1000.0 <= 0.5


def test_exception_from_the_screen_returns(monkeypatch):
    class DeadScreen:
        def get_size(self):
            raise pygame.error("no surface")

    clock = FakeClock()
    call(DeadScreen(), busy_stats(), clock)
    assert clock.t - 1000.0 <= 0.5


def test_none_stats_is_survivable(screen):
    clock = FakeClock()
    call(screen, None, clock)
    assert clock.t - 1000.0 <= 0.5


def test_a_stalled_clock_cannot_hold_the_exit_forever(screen, drawn_art):
    frozen = lambda: 1000.0                                  # noqa: E731
    summary.run_summary(screen, busy_stats(), 1008.0, lambda: False, frozen,
                        sleep=lambda s: None)
    assert len(drawn_art) <= 8 * summary.FPS * 2 + 30


def test_real_clock_run_is_bounded(screen):
    t0 = time.monotonic()
    summary.run_summary(screen, busy_stats(), t0 + 0.4, lambda: False)
    assert time.monotonic() - t0 <= 0.4 + 0.5


def test_zero_stats_still_render(screen, drawn_art):
    card = summary.render_card(SIZE, PlayStats())
    assert card.get_size() == SIZE
    clock = FakeClock()
    call(screen, PlayStats(), clock, deadline_in=1.0)
    assert len(drawn_art) > 10


def test_card_has_the_bright_and_dim_grid(screen):
    stats = PlayStats()
    stats.on_action(classify("a"), 0)
    lit = summary.render_card(SIZE, stats)
    empty = summary.render_card(SIZE, PlayStats())
    assert pygame.image.tobytes(lit, "RGB") != pygame.image.tobytes(empty, "RGB")


def test_missing_card_background_is_fine(tmp_path):
    folder = tmp_path / "album"
    folder.mkdir()
    (folder / "manifest.toml").write_text('schema = 1\ncard = "card.jpg"\n', encoding="utf-8")
    card = summary.render_card(SIZE, busy_stats(), root=tmp_path)    # card.jpg does not exist
    assert card.get_size() == SIZE


def test_painted_card_background_is_used_when_present(tmp_path):
    folder = tmp_path / "album"
    folder.mkdir()
    image = pygame.Surface((32, 18))
    image.fill((12, 200, 44))
    pygame.image.save(image, folder / "card.png")
    (folder / "manifest.toml").write_text('schema = 1\ncard = "card.png"\n', encoding="utf-8")
    card = summary.render_card(SIZE, busy_stats(), root=tmp_path)
    assert card.get_at((2, 2))[:3] == (12, 200, 44)


def test_unreadable_card_background_falls_back_to_the_gradient(tmp_path):
    folder = tmp_path / "album"
    folder.mkdir()
    (folder / "card.jpg").write_bytes(b"junk")
    (folder / "manifest.toml").write_text('schema = 1\ncard = "card.jpg"\n', encoding="utf-8")
    card = summary.render_card(SIZE, busy_stats(), root=tmp_path)
    assert card.get_at((2, 2))[:3] != (0, 0, 0)


def test_renders_at_odd_sizes():
    for size in ((320, 240), (1280, 720), (800, 1000)):
        assert summary.render_card(size, busy_stats()).get_size() == size


def test_halting_mid_build_returns_none():
    assert summary.render_card(SIZE, busy_stats(), halt=lambda: True) is None


@pytest.mark.parametrize("seconds,text", [
    (0, "0 min"), (-5, "0 min"), (float("nan"), "0 min"), (30, "<1 min"), (60, "1 min"),
    (2520, "42 min"), (3600, "1 h 00 min"), (3900, "1 h 05 min"),
])
def test_duration_wording(seconds, text):
    assert summary.format_duration(seconds) == text


def test_animal_names_read_well():
    assert summary.animal_title("trex") == "T. rex"
    assert summary.animal_title("xrayfish") == "X-ray fish"
    assert summary.animal_title("giraffe") == "Giraffe"


def test_summary_never_writes_files(screen, monkeypatch, tmp_path):
    import builtins
    real_open = builtins.open

    def guarded(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            raise AssertionError(f"summary opened {file!r} for writing")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded)
    clock = FakeClock()
    call(screen, busy_stats(), clock, deadline_in=1.0)
