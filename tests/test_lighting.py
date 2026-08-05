from lilypad.lighting.base import (
    KEY_FLASH_LIFE,
    RIPPLE_LIFE,
    LightingEngine,
    Ripple,
    blank_grid,
    render_frame,
)
from lilypad.lighting.keymap import COLS, KEY_MATRIX, ROWS, position
from lilypad.lighting.mock import MockLightingBackend


def grid_dims_ok(grid):
    return len(grid) == ROWS and all(len(row) == COLS for row in grid)


def test_blank_grid_shape():
    g = blank_grid()
    assert grid_dims_ok(g)
    assert g[0][0] == (0, 0, 0)


def test_idle_frame_breathes_everywhere():
    g = render_frame(10.0, [], {}, mash=False)
    assert grid_dims_ok(g)
    assert all(any(px) for row in g for px in row), "idle breathing lights all LEDs"


def test_ripple_brightens_near_its_origin():
    now = 100.0
    rp = Ripple(row=3, col=10, start=now - 0.05, hue=0.0)
    with_ripple = render_frame(now, [rp], {}, mash=False)
    without = render_frame(now, [], {}, mash=False)
    origin_delta = sum(with_ripple[3][10]) - sum(without[3][10])
    far_delta = sum(with_ripple[0][21]) - sum(without[0][21])
    assert origin_delta > far_delta, "ripple should light its origin first"


def test_pressed_key_flashes_bright():
    now = 50.0
    lit = {"A": (now - 0.05, 0.3)}
    g = render_frame(now, [], lit, mash=False)
    r, c = position("A")
    assert sum(g[r][c]) > 350  # near-white flash


def test_mash_strobe_is_rainbow():
    g = render_frame(1.0, [], {}, mash=True)
    assert grid_dims_ok(g)
    hues = {px for row in g for px in row}
    assert len(hues) > 8, "strobe frame should span many colors"


def test_engine_ticks_at_configured_fps():
    backend = MockLightingBackend()
    engine = LightingEngine(backend, fps=30, brightness=0.5)
    assert backend.brightness == 0.5
    engine.key_pressed("A", 0.0)
    engine.tick(0.0)
    engine.tick(0.01)   # too soon — dropped
    engine.tick(0.04)   # past 1/30s — applied
    assert backend.frames_applied == 2


def test_engine_expires_state():
    backend = MockLightingBackend()
    engine = LightingEngine(backend, fps=1000)
    engine.key_pressed("Q", 0.0)
    engine.tick(RIPPLE_LIFE + KEY_FLASH_LIFE + 1.0)
    assert engine._ripples == []
    assert engine._lit == {}


def test_engine_close_closes_backend():
    backend = MockLightingBackend()
    LightingEngine(backend).close()
    assert backend.closed


# ------------------------------------------------------------------ keymap

def test_keymap_positions_in_bounds():
    for name, (r, c) in KEY_MATRIX.items():
        assert 0 <= r < ROWS, name
        assert 0 <= c < COLS, name


def test_keymap_covers_the_keys_that_matter():
    for name in [*"ABCDEFGHIJKLMNOPQRSTUVWXYZ", *"0123456789",
                 "SPACE", "ENTER", "BACKSPACE", "LEFTSHIFT", "RIGHTSHIFT",
                 "UP", "DOWN", "LEFT", "RIGHT", "ESC"]:
        assert name in KEY_MATRIX, name


def test_unknown_key_gets_center_fallback():
    r, c = position("NOT_A_KEY")
    assert 0 <= r < ROWS and 0 <= c < COLS
