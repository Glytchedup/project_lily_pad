from hashlib import sha256
from pathlib import Path
from time import perf_counter

import pytest

from lilypad.config import load as load_config
from lilypad.lighting.base import LightingEngine, blank_grid, render_frame
from lilypad.lighting.keymap import COLS, ROWS, position
from lilypad.lighting.mock import MockLightingBackend
from lilypad.lighting.patterns import Track


def idle(now):
    return render_frame(now, [], {}, False)


def changed(frame, now):
    base = idle(now)
    return {(r, c) for r in range(ROWS) for c in range(COLS) if frame[r][c] != base[r][c]}


def animal(name, now=0.0, *, x=0.5, y=0.5, width=7):
    track = Track(name, x, y, width / COLS, 0.0)
    return render_frame(now, [], {}, False, [track])


def test_giraffe_has_staggered_warm_spots_and_zebra_has_moving_stripes():
    giraffe = animal("giraffe")
    gold = (242, 196, 107)
    assert giraffe[3][9] == giraffe[2][8] == gold
    assert giraffe[3][8] == giraffe[2][10] != gold

    zebra = animal("zebra")
    assert zebra[2][8:15] == zebra[3][8:15]
    assert zebra[3][8] == zebra[3][10] != zebra[3][9]
    assert animal("zebra", x=12 / 21)[3][9:16] == zebra[3][8:15]


def test_lion_mane_glows_out_from_the_centre():
    row = animal("lion")[3]
    assert sum(row[11]) > sum(row[9]) > sum(row[8])
    assert row[8:15] == row[8:15][::-1]


@pytest.mark.parametrize("name", ["whale", "narwhal"])
def test_swimmer_has_a_rolling_blue_wave_on_the_bottom_two_rows(name):
    first = animal(name, y=0.75)
    assert changed(first, 0.0) == {(r, c) for r in (4, 5) for c in range(8, 15)}
    for r in (4, 5):
        assert all(b > g > red for red, g, b in first[r][8:15])
        assert first[r][8:15] != animal(name, 0.15, y=0.75)[r][8:15]
    assert first[4][8] != first[5][8]


def test_owl_blinks_even_while_its_position_is_updated():
    backend = MockLightingBackend()
    engine = LightingEngine(backend)
    engine.track("bird", "owl", 0.5, 0.5, 7 / COLS, 10.0)
    engine.tick(10.0)
    assert changed(backend.last_grid, 10.0) == {(3, 9), (3, 13)}
    open_eye = backend.last_grid[3][9]
    engine.track("bird", "owl", 12 / 21, 0.5, 7 / COLS, 12.4)
    engine.tick(12.4)
    assert changed(backend.last_grid, 12.4) == {(3, 10), (3, 14)}
    assert sum(backend.last_grid[3][10]) < sum(open_eye)
    engine.tick(12.6)
    assert backend.last_grid[3][10] == open_eye


def test_jellyfish_pulses_pink():
    dim = animal("jellyfish")[3][11]
    bright = animal("jellyfish", 0.41)[3][11]
    assert sum(dim) < sum(bright)
    assert all(red > blue > green for red, green, blue in (dim, bright))


@pytest.mark.parametrize("name", [
    "trex", "velociraptor", "stegosaurus", "triceratops", "brachiosaurus", "pterodactyl",
])
def test_dinosaur_stomp_lands_one_row_lower_and_brighter(name):
    landed = animal(name)
    lifted = animal(name, 0.3)
    assert {r for r, c in changed(landed, 0.0)} == {3, 4}
    assert {r for r, c in changed(lifted, 0.3)} == {2, 3}
    assert sum(landed[3][11]) > sum(lifted[3][11])
    assert all(g > max(r, b) for r, g, b in (landed[3][11], lifted[3][11]))


@pytest.mark.parametrize("name", [
    "alligator", "bear", "cow", "duck", "elephant", "fox", "horse", "iguana",
    "koala", "monkey", "pig", "quail", "rabbit", "sheep", "unicorn", "xrayfish",
    "yak", "unknown",
])
def test_remaining_coats_have_one_travelling_sparkle(name):
    first = animal(name)
    later = animal(name, 0.14)
    coat = first[2][8]
    rim = (191, 216, 255)
    assert first[3][8:15] == [rim] + [coat] * 6
    assert later[3][8:15] == [coat, rim] + [coat] * 5
    assert later == animal(name, 0.14)


@pytest.mark.parametrize(("x", "y", "column", "rows"), [
    (0.0, 0.0, 0, {0, 1}),
    (1.0, 1.0, 21, {4, 5}),
])
def test_single_column_track_hits_outermost_led(x, y, column, rows):
    assert changed(animal("zebra", x=x, y=y, width=1), 0.0) == {(r, column) for r in rows}


def test_width_is_screen_relative_and_clips_without_wrapping():
    frame = animal("zebra", width=11)
    assert {c for _, c in changed(frame, 0.0)} == set(range(6, 17))
    frame = animal("zebra", x=-1 / 21, width=5)
    assert {c for _, c in changed(frame, 0.0)} == {0, 1}
    assert animal("zebra", x=-1, width=5) == idle(0)


def test_untrack_reveals_the_older_coat_then_the_breathe_base():
    backend = MockLightingBackend()
    engine = LightingEngine(backend)
    engine.track(1, "zebra", 0.5, 0.5, 7 / COLS, 0.0)
    engine.track(2, "giraffe", 0.5, 0.5, 7 / COLS, 0.0)
    engine.tick(0)
    assert backend.last_grid == animal("giraffe")
    engine.untrack(2)
    engine.tick(0.1)
    assert backend.last_grid == animal("zebra", 0.1)
    engine.untrack(1)
    engine.untrack(1)
    engine.tick(0.2)
    assert backend.last_grid == idle(0.2)


def test_sixth_track_replaces_oldest_and_updates_do_not_take_another_slot():
    backend = MockLightingBackend()
    engine = LightingEngine(backend)
    for col in range(5):
        engine.track(col, "zebra", col / 21, 0.5, 1 / COLS, 0.0)
    engine.track(1, "zebra", 7 / 21, 0.5, 1 / COLS, 0.1)
    engine.track(5, "zebra", 5 / 21, 0.5, 1 / COLS, 0.1)
    engine.tick(0.1)
    assert {c for _, c in changed(backend.last_grid, 0.1)} == {2, 3, 4, 5, 7}


def test_ripple_and_pressed_key_render_over_coat():
    backend = MockLightingBackend()
    engine = LightingEngine(backend)
    row, col = position("A")
    engine.track(1, "zebra", col / 21, row / 5, 7 / COLS, 0.0)
    coat = animal("zebra", x=col / 21, y=row / 5)
    engine.key_pressed("A", 0.0)
    engine.tick(0.0)
    reference = MockLightingBackend()
    bare_keys = LightingEngine(reference)
    bare_keys.key_pressed("A", 0.0)
    bare_keys.tick(0.0)
    assert backend.last_grid[row][col] == reference.last_grid[row][col]
    # Adjacent cell is inside the new ring and outside the key flash.
    assert sum(backend.last_grid[row][col + 1]) > sum(coat[row][col + 1])
    assert backend.last_grid[row][col + 3] == coat[row][col + 3]


def test_blooms_survive_a_throttled_tick_and_last_one_submitted_frame():
    backend = MockLightingBackend()
    engine = LightingEngine(backend)
    engine.tick(0.0)
    engine.bloom(1, 0, (220, 30, 16), 0.005)
    engine.bloom(0, 1, (5, 100, 250), 0.006)
    engine.tick(0.01)
    assert backend.frames_applied == 1
    engine.tick(0.1)
    assert changed(backend.last_grid, 0.1) == {(0, 21), (0, 20), (1, 21), (5, 0), (4, 0), (5, 1)}
    assert backend.last_grid[0][21] == (220, 30, 16)
    assert backend.last_grid[5][0] == (5, 100, 250)
    engine.tick(0.2)
    assert backend.last_grid == idle(0.2)


def test_mash_overrides_tracks_and_consumes_blooms():
    backend = MockLightingBackend()
    engine = LightingEngine(backend)
    engine.track(0, "zebra", 0.5, 0.5, 7 / COLS, 0)
    engine.bloom(0, 0, (255, 85, 0), 0)
    engine.set_mash(True)
    engine.tick(0)
    assert backend.last_grid == render_frame(0, [], {}, True)
    engine.set_mash(False)
    engine.tick(0.1)
    assert backend.last_grid == animal("zebra", 0.1)


def test_sleep_blanks_and_discards_mirror_events_through_wake():
    backend = MockLightingBackend()
    engine = LightingEngine(backend)
    engine.track(0, "giraffe", 0.5, 0.5, 0.5, 0)
    engine.tick(0)
    engine.bloom(1, 1, (220, 20, 30), 0.01)
    engine.set_sleep(True)
    engine.track(1, "jellyfish", 0, 0, 0.3, 0.02)
    engine.bloom(0, 0, (5, 6, 7), 0.03)
    engine.tick(0.1)
    assert backend.last_grid == blank_grid()
    assert backend.frames_applied == 2
    engine.set_sleep(False)
    engine.tick(0.1)
    assert backend.last_grid == idle(0.1)


def test_legacy_config_matches_pre_mirror_frames_byte_for_byte():
    config = load_config(Path(__file__).resolve().parents[1] / "config.legacy.toml")
    backend = MockLightingBackend()
    engine = LightingEngine(backend, mirror_animals=config.lighting.mirror_animals)
    digest = sha256()

    def record():
        digest.update(bytes(ch for row in backend.last_grid for px in row for ch in px))

    engine.track(0, "giraffe", 0.5, 0.5, 0.5, 0)
    engine.tick(0.0)
    record()
    engine.key_pressed("A", 0.1)
    engine.bloom(0.5, 0.5, (10, 215, 200), 0.1)
    engine.tick(0.1)
    record()
    engine.tick(0.4)
    record()
    engine.set_mash(True)
    engine.tick(0.5)
    record()
    engine.set_sleep(True)
    record()
    engine.set_mash(False)
    engine.set_sleep(False)
    engine.tick(0.6)
    record()
    # Captured from the six original frames on e98b755 before J13.
    assert digest.hexdigest() == "a5ac9af838424b5489d3643ea1420fcff0de4ffcf9f6e9d63259f6aff32f6d95"


def test_five_full_width_tracks_render_under_two_ms():
    tracks = [Track(name, 0.5, 0.5, 1.0, 0) for name in
              ("giraffe", "lion", "narwhal", "jellyfish", "stegosaurus")]
    samples = []
    for n in range(120):
        start = perf_counter()
        render_frame(n / 30, [], {}, False, tracks)
        samples.append(perf_counter() - start)
    assert sorted(samples)[113] < 0.002  # 95th percentile of 120 frames
