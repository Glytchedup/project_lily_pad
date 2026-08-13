"""Lily Pad entry point.

Modes:
  --dev    windowed on a desktop, SDL keyboard input, mock lighting default
  --kiosk  fullscreen KMSDRM on the Pi, evdev exclusive grab, real lighting

With no flag: kiosk on Linux consoles (no DISPLAY/WAYLAND), dev otherwise.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

log = logging.getLogger("lilypad")

DEFAULT_CONFIG_PATHS = ("/etc/lilypad/config.toml", "config.toml")


def _default_mode() -> str:
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY"):
        return "kiosk"
    return "dev"


def _find_config(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for candidate in DEFAULT_CONFIG_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


def _draw_escape_cue(surface, progress: float) -> None:
    """Subtle bottom-right bar while the parent combo is being held."""
    import pygame
    if progress <= 0.02:
        return
    w, h = surface.get_size()
    bar_w, bar_h = int(w * 0.18), 10
    x, y = w - bar_w - 24, h - bar_h - 20
    pygame.draw.rect(surface, (60, 60, 60), (x, y, bar_w, bar_h), border_radius=5)
    pygame.draw.rect(surface, (240, 240, 240),
                     (x, y, int(bar_w * progress), bar_h), border_radius=5)


DISPLAY_RETRY_SECONDS = 3.0
DISPLAY_LOG_EVERY = 10          # log once per this many attempts (~30 s)

#: Frame rate while the screen is asleep. The loop still has to run — it is
#: what notices the next keypress — but painting black 60 times a second is
#: pure heat, and a Pi in a toddler's bedroom should idle cold and quiet.
SLEEP_FPS = 10

#: Set by SIGTERM/SIGINT. Module-level rather than a local because the app has
#: two places that must notice a shutdown: the wait-for-display loop, which runs
#: before the main loop exists, and the main loop itself.
_stop_requested = False


def _request_stop(_signum=None, _frame=None) -> None:
    global _stop_requested
    _stop_requested = True


def _install_signal_handlers() -> None:
    """Take SIGTERM/SIGINT back from SDL.

    ``pygame.init()`` installs SDL's own handlers, which only post a QUIT event
    — useless here, because the kiosk path doesn't read SDL's queue and the
    wait-for-display loop below hasn't got a queue to read yet. Must therefore
    be called *after* pygame.init(), or SDL overwrites these.
    """
    global _stop_requested
    _stop_requested = False
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)


def _wait_for_display(retry: float = DISPLAY_RETRY_SECONDS):
    """Take over the screen, waiting for one to exist if necessary.

    A monitor that is switched off, asleep, or on another input reports its
    HDMI connector as disconnected, and SDL then raises "kmsdrm not available".
    Exiting on that would be wrong twice over: systemd would spin the service
    in a restart storm, and once the restarts outpaced ``StartLimitBurst`` the
    unit would latch into *failed* and stay dead even after the monitor came
    back — a black box in a toddler's room until a parent SSHes in.

    So we wait instead. The moment the display appears the app starts, and
    nothing has to be restarted by hand. Verified on a Pi 5: the monitor being
    off at boot is an ordinary event, not an error.

    Returns ``None`` if a shutdown was requested while waiting — a reboot with
    the monitor off must not have to wait out systemd's kill timeout.
    """
    import pygame
    attempt = 0
    while not _stop_requested:
        try:
            return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        except pygame.error as exc:
            if attempt % DISPLAY_LOG_EVERY == 0:
                log.warning("no display yet (%s) — waiting; is the monitor on?", exc)
            attempt += 1
            # Short sleeps so a SIGTERM lands promptly rather than up to
            # `retry` seconds later.
            waited = 0.0
            while waited < retry and not _stop_requested:
                time.sleep(min(0.25, retry - waited))
                waited += 0.25
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lilypad",
                                     description="Toddler Keyboard Playground")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dev", action="store_true", help="windowed dev mode")
    mode.add_argument("--kiosk", action="store_true", help="fullscreen Pi kiosk mode")
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("--lighting", choices=["auto", "razer_hid", "openrazer", "mock"],
                        help="override lighting backend")
    parser.add_argument("--smoke", type=float, metavar="SECONDS",
                        help="self-test: synthesize random key events for N "
                             "seconds, then exit cleanly")
    parser.add_argument("--doctor", action="store_true",
                        help="diagnose the display, audio, network and "
                             "deployment state, then exit")
    args = parser.parse_args(argv)

    # Before anything imports pygame or touches the display: the doctor has to
    # be runnable while the service is up, and on a machine with no screen.
    if args.doctor:
        from .doctor import format_report, run_all
        report = run_all()
        print(format_report(report), end="")
        return 1 if report.failed else 0

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    kiosk = args.kiosk or (not args.dev and _default_mode() == "kiosk")

    if kiosk:
        os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
    # Must come after the env var is set:
    import pygame

    from .audio.engine import AudioEngine
    from .config import load as load_config
    from .effects.engine import EffectEngine
    from .escape import EscapeHatch
    from .input.mapper import KeyMapper
    from .lighting import LightingEngine, make_backend

    cfg = load_config(_find_config(args.config))

    pygame.init()
    # After pygame.init(), which installs SDL's own handlers, and before the
    # wait below — a reboot while the monitor is off has to be honoured too.
    _install_signal_handlers()
    if kiosk:
        screen = _wait_for_display()
        if screen is None:
            log.info("shutdown requested while waiting for a display")
            pygame.quit()
            return 0
    else:
        screen = pygame.display.set_mode(cfg.display.dev_window)
        pygame.display.set_caption("Lily Pad — dev mode (hold both Shifts + Backspace 5s to exit)")
    pygame.mouse.set_visible(False)
    size = screen.get_size()
    log.info("mode=%s display=%sx%s", "kiosk" if kiosk else "dev", *size)

    # Must happen before the first sprite is cached, and after the display
    # exists so the probe can build a real surface.
    from .effects.animal_art import set_silhouettes
    from .effects.animals import prewarm
    from .effects.shapes import prewarm as prewarm_shapes
    set_silhouettes(cfg.effects.silhouettes)
    prewarm(size[1])
    prewarm_shapes(size[1])

    # Input backend
    if args.smoke:
        from .input.synthetic import SyntheticInputBackend
        input_backend = SyntheticInputBackend(duration=args.smoke)
    elif kiosk:
        from .input.evdev_backend import EvdevInputBackend
        input_backend = EvdevInputBackend()
    else:
        from .input.sdl_backend import SdlInputBackend
        input_backend = SdlInputBackend()
    input_backend.start()

    # Lighting: kiosk defaults to config/auto; dev defaults to mock
    lighting_pref = args.lighting or (cfg.lighting.backend if kiosk else "mock")
    lighting = LightingEngine(make_backend(lighting_pref),
                              fps=cfg.lighting.fps,
                              brightness=cfg.lighting.brightness)

    audio = AudioEngine(Path("assets/sounds/generated") if not kiosk
                        else Path("/opt/lilypad/sounds"),
                        mute=cfg.audio.mute, volume=cfg.audio.volume,
                        key_notes=cfg.music.key_notes,
                        tunes=cfg.music.tunes,
                        tune_volume=cfg.music.tune_volume)

    mapper = KeyMapper(chord_window=cfg.effects.chord_window)
    escape = EscapeHatch(combo=cfg.escape.combo,
                         hold_seconds=cfg.escape.hold_seconds)
    engine = EffectEngine(size,
                          max_particles=cfg.effects.max_particles,
                          idle_timeout=cfg.display.idle_timeout,
                          fps=cfg.display.fps,
                          trails=cfg.effects.trails,
                          milestone_every=cfg.effects.milestone_every,
                          sleep_timeout=cfg.display.sleep_timeout)

    clock = pygame.time.Clock()
    running = True
    exit_code = 0

    try:
        while running and not _stop_requested:
            dt = clock.tick(SLEEP_FPS if engine.asleep
                            else cfg.display.fps) / 1000.0
            # Measure work time only — clock.tick's fps-cap sleep must not
            # count against the frame budget or degradation can never recover.
            frame_start = time.perf_counter()
            now = time.monotonic()

            events = input_backend.poll()
            if getattr(input_backend, "quit_requested", False):
                running = False
            if kiosk:
                # SDL's own queue is unused on the Pi (evdev is the input
                # path), but it must be *drained*, not blindly discarded —
                # QUIT arrives here and dropping it is how the app used to
                # ignore shutdown requests.
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        running = False

            def handle(action):
                engine.spawn(action, now)
                audio.on_action(action)
                if action.kind == "mash_start":
                    lighting.set_mash(True)
                elif action.kind == "mash_end":
                    lighting.set_mash(False)

            for ev in events:
                if ev.pressed:
                    # Wake on the raw event, before the mapper decides whether
                    # this key means anything: a key that produces no action
                    # (a lone Shift) still means somebody is at the keyboard.
                    engine.wake(now)
                    lighting.key_pressed(ev.name, now)
                for action in mapper.feed(ev):
                    handle(action)
            # Time-based: keys held past the threshold become rainbow comets,
            # and rate-triggered mash mode exits once tapping slows.
            for action in mapper.poll_holds(now):
                handle(action)
            if engine.consume_celebration():
                audio.on_celebration()

            if escape.update(input_backend.held_keys(), now):
                log.info("parent escape combo held — exiting cleanly")
                running = False

            engine.update(dt, now)
            # Background tunes are the soundtrack to an empty room: attract
            # mode fades them in, the next keypress fades them straight out.
            audio.set_idle(engine.attract is not None)
            # Dark screen, dark keyboard.
            lighting.set_sleep(engine.asleep)
            engine.draw(screen)
            _draw_escape_cue(screen, escape.hold_progress(now))
            pygame.display.flip()
            lighting.tick(now)
            engine.note_frame_time(time.perf_counter() - frame_start)
    except KeyboardInterrupt:
        log.info("interrupted")
    except Exception:
        log.exception("crashed — systemd will restart the service")
        exit_code = 1
    finally:
        input_backend.stop()
        lighting.close()
        audio.close()
        pygame.quit()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
