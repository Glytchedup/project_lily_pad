"""Keyboard frames can be sampled at any song position, without audio or USB."""

from pathlib import Path

import pytest

from lilypad.audio.tracks import BeatClock, BeatMap
from lilypad.config import load
from lilypad.lighting.base import blank_grid
from lilypad.lighting.keymap import COLS, ROWS
from lilypad.lighting.show import PartyShow, beat_chase, drop_flash, parade_chase, rainbow_wipe


@pytest.mark.parametrize("pattern", [beat_chase, rainbow_wipe, drop_flash, parade_chase])
def test_pattern_is_pure_and_returns_an_independent_full_matrix(pattern):
    kwargs = {"x_frac": 0.4} if pattern is parade_chase else {}
    for bar in (0, 1, 3):
        for phase in (0.0, 0.25, 0.99999):
            args = (123.0, phase, bar, True)
            frame = pattern(*args, **kwargs)
            assert len(frame) == ROWS and all(len(row) == COLS for row in frame)
            assert all(len(rgb) == 3 and all(type(c) is int and 0 <= c <= 255 for c in rgb)
                       for row in frame for rgb in row)
            repeat = pattern(*args, **kwargs)
            assert repeat == frame
            frame[0][0] = None
            assert repeat[0][0] is not None and frame[1][0] is not None


def test_runner_advances_within_a_beat_and_wipe_reveals_columns_in_bar_direction():
    def peak(grid):
        return max(range(COLS), key=lambda col: max(grid[0][col]))

    assert peak(beat_chase(0, 0, 0, False)) == 0
    assert beat_chase(0, 0.45, 0, False) != beat_chase(0, 0, 0, False)
    for bar, start in ((1, 0), (3, COLS - 1)):
        downbeat = rainbow_wipe(0, 0, bar, False)[0]
        assert [c for c, rgb in enumerate(downbeat) if max(rgb) > 200] == [start]
        half = rainbow_wipe(0, 0.5, bar, False)[0]
        assert COLS // 2 <= sum(max(rgb) > 200 for rgb in half) <= COLS // 2 + 1
        assert all(max(rgb) > 200 for rgb in rainbow_wipe(0, 0.999, bar, False)[0])


def test_mapped_clock_controls_bar_selection_drop_priority_and_lead_in():
    beats = (0.4, 0.9, 1.7, 2.1, 2.8, 3.2, 3.9, 4.3, 4.8)
    clock = BeatClock(BeatMap(120, 0.4, beats, (0.4, 2.8, 4.8), (3.2,)))
    show = PartyShow(clock)
    assert show.frame(90) == blank_grid()
    for ms, pattern in ((1300, beat_chase), (2900, rainbow_wipe), (3200, drop_flash),
                        (3500, drop_flash), (3900, beat_chase), (4800, beat_chase)):
        clock.resync(ms)
        phase, bar, drop = clock.beat_phase, clock.bar, clock.is_drop
        grid = show.frame(90)
        assert grid == pattern(90, phase, bar, drop)
        assert (clock.beat_phase, clock.bar, clock.is_drop) == (phase, bar, drop)
        if drop:
            assert len({rgb for row in grid for rgb in row}) == 1
            assert max(grid[0][0]) > 100
        if ms == 3200:
            assert show.frame(90, lead_x_frac=0.25) == parade_chase(90, phase, bar, True, x_frac=0.25)


def test_free_run_uses_120_bpm_and_supports_seeking():
    show = PartyShow()
    assert show.frame(0.25) == beat_chase(0.25, 0.5, 0, False)
    assert show.frame(2.125) == rainbow_wipe(2.125, 0.25, 1, False)
    assert show.frame(0.25) == show.frame(0.75)


def test_wipe_uses_mapped_downbeat_after_a_short_bar_and_only_lasts_one_beat():
    beats = tuple(i * 0.5 for i in range(12))
    clock = BeatClock(BeatMap(120, 0, beats, (0.5, 2.0, 3.5), ()))
    show = PartyShow(clock)
    for ms, bar, pattern in ((2100, 1, rainbow_wipe), (2600, 1, beat_chase),
                             (5600, 3, rainbow_wipe), (6100, 3, beat_chase)):
        clock.resync(ms)
        assert clock.bar == bar
        assert show.frame(0) == pattern(0, clock.beat_phase, bar, False)


@pytest.mark.parametrize(("fraction", "centre"), [(-2, 0), (0, 0), (0.5, 11), (1, 21), (2, 21)])
def test_rainbow_ribbon_tracks_screen_column(fraction, centre):
    grid = parade_chase(0, 0.2, 1, False, x_frac=fraction)
    for row in grid:
        assert max(range(COLS), key=lambda col: max(row[col])) == centre
        assert all((max(rgb) > 0) == (abs(col - centre) <= 2) for col, rgb in enumerate(row))
    assert len({row[centre] for row in grid}) == ROWS


def test_both_show_switches_follow_the_profile():
    root = Path(__file__).resolve().parents[1]
    for filename, expected in (("config.toml", True), ("config.legacy.toml", False)):
        cfg = load(root / filename)
        assert cfg.music.party_show is cfg.effects.parade is expected
