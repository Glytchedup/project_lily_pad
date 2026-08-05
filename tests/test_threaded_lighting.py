import time

from lilypad.lighting.base import blank_grid
from lilypad.lighting.mock import MockLightingBackend
from lilypad.lighting.threaded import ThreadedLightingBackend


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_apply_is_async_and_reaches_inner():
    inner = MockLightingBackend()
    threaded = ThreadedLightingBackend(inner)
    try:
        threaded.apply(blank_grid())
        assert wait_until(lambda: inner.frames_applied >= 1)
    finally:
        threaded.close()


def test_latest_frame_wins_under_burst():
    class SlowMock(MockLightingBackend):
        def apply(self, grid):
            time.sleep(0.03)
            super().apply(grid)

    inner = SlowMock()
    threaded = ThreadedLightingBackend(inner)
    try:
        marker = blank_grid()
        marker[0][0] = (1, 2, 3)
        for _ in range(10):
            threaded.apply(blank_grid())
        threaded.apply(marker)  # last one posted must be the one that lands
        assert wait_until(lambda: inner.last_grid is not None
                          and inner.last_grid[0][0] == (1, 2, 3))
        # Burst of 11 rapid frames collapses — far fewer inner applies.
        assert inner.frames_applied < 11
    finally:
        threaded.close()


def test_apply_returns_fast_even_when_inner_is_slow():
    class VerySlow(MockLightingBackend):
        def apply(self, grid):
            time.sleep(0.05)
            super().apply(grid)

    threaded = ThreadedLightingBackend(VerySlow())
    try:
        start = time.perf_counter()
        for _ in range(20):
            threaded.apply(blank_grid())
        elapsed = time.perf_counter() - start
        assert elapsed < 0.05, "apply() must not block on inner backend I/O"
    finally:
        threaded.close()


def test_close_joins_and_closes_inner():
    inner = MockLightingBackend()
    threaded = ThreadedLightingBackend(inner)
    threaded.apply(blank_grid())
    threaded.close()
    assert inner.closed
    assert not threaded._worker.is_alive()


def test_inner_exception_does_not_kill_worker():
    class Flaky(MockLightingBackend):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def apply(self, grid):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("usb hiccup")
            super().apply(grid)

    inner = Flaky()
    threaded = ThreadedLightingBackend(inner)
    try:
        threaded.apply(blank_grid())
        assert wait_until(lambda: inner.calls >= 1)
        threaded.apply(blank_grid())
        assert wait_until(lambda: inner.frames_applied >= 1), \
            "worker must survive an inner backend exception"
    finally:
        threaded.close()
