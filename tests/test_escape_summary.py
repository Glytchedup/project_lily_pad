"""Exercise the parent combo, summary poll and cleanup through the app entry point."""

import time

import pygame
import pytest

from lilypad import __main__ as app
from lilypad import summary
from lilypad.effects import animal_art, animals, critter, glow
from lilypad.input import sdl_backend, synthetic
from lilypad.input.base import KeyEvent


@pytest.mark.parametrize("reason,seconds,expected", [
    ("escape", .14, True), ("error", .14, True), ("stop_on_card", 2, True),
    ("smoke", .14, False), ("escape", 0, False), ("quit", .14, False),
    ("sigterm", .14, False),
])
def test_summary_exit_paths(reason, seconds, expected, tmp_path, monkeypatch):
    config = tmp_path / "test.toml"
    config.write_text(f"""
[audio]
mute = true
[escape]
summary_seconds = {seconds}
hold_seconds = 0.001
[display]
dev_window = [224, 128]
[scene]
world = "drawn"
[effects]
album = false
storybook = "off"
animal_art = "drawn"
""")
    # Keep this main() run from altering the session's warmed art, signal
    # handlers and SDL display. The mapper, escape hatch and renderer are real.
    for module, func in ((animal_art, "set_art_mode"), (animals, "prewarm"),
                         (critter, "set_pip_art"), (glow, "set_fx_style")):
        monkeypatch.setattr(module, func, lambda *a, **kw: None)
    monkeypatch.setattr(app, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(app, "_stop_requested", False)
    monkeypatch.setattr(pygame, "quit", lambda: None)
    monkeypatch.setenv("LILYPAD_ART_DIR", str(tmp_path))

    class Input:
        polls = 0
        stopped = quit_requested = False

        def start(self):
            pass

        def poll(self):
            self.polls += 1
            if self.polls == 2 and reason == "sigterm":
                app._request_stop()
            if self.polls == 2 and reason == "quit":
                self.quit_requested = True
            if card_started and reason == "stop_on_card":
                app._request_stop()
            assert self.polls < 100, "parent escape or summary failed to finish"
            return [KeyEvent("X" if card_started else "G", True, time.monotonic())]

        def held_keys(self):
            return frozenset(("LEFTSHIFT", "RIGHTSHIFT", "BACKSPACE"))

        def stop(self):
            self.stopped = True

    device = Input()
    monkeypatch.setattr(sdl_backend, "SdlInputBackend", lambda: device)
    monkeypatch.setattr(synthetic, "SyntheticInputBackend", lambda **kw: device)
    card_started = []
    # Keep setup deterministic. run_summary owns its real deadline and poll loop.
    monkeypatch.setattr(summary, "render_card", lambda size, *args: pygame.Surface(size))
    observations = []

    def observe(screen, stats, deadline, poll, **kwargs):
        start = time.monotonic()
        card_started.append(start)
        observations.append((stats, deadline - start))
        if reason == "error":
            raise RuntimeError("injected summary failure")
        summary.run_summary(screen, stats, deadline, poll, **kwargs)

    monkeypatch.setattr(app, "run_summary", observe)
    original_size = pygame.display.get_surface().get_size()
    try:
        argv = ["--dev", "--config", str(config)]
        if reason == "smoke":
            argv += ["--smoke", "1"]
        assert app.main(argv) == 0
        end = time.monotonic()
        assert bool(card_started) == expected and device.stopped
        if card_started:
            (stats, budget), = observations
            assert stats.letters_found == {"G"} and stats.favourite == "giraffe"
            assert budget == pytest.approx(seconds, abs=.05)
            elapsed = end - card_started[0]
            assert elapsed <= seconds + .5
            if reason == "escape":
                assert elapsed >= seconds - .025 and device.polls > 3
            if reason == "stop_on_card":
                assert elapsed < .5
    finally:
        pygame.display.set_mode(original_size)
