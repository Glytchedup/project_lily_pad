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


#: Party meter: a bar in the top-right that fills as the next reward track is
#: earned. Deliberately small and off to the side — it is a hint, not a scoreboard,
#: and the playground itself has to stay the thing worth looking at.
PARTY_METER_EMPTY = (0, 199, 190)     # teal, just started
PARTY_METER_FULL = (255, 214, 10)     # gold, about to fire
PARTY_METER_TRACK = (28, 32, 42)


def _draw_party_meter(surface, progress: float) -> None:
    """Fills left-to-right and warms teal -> gold as the party nears."""
    import pygame
    if progress <= 0.0:
        return
    w, h = surface.get_size()
    bar_w = int(w * 0.16)
    bar_h = max(10, int(h * 0.018))
    x, y = w - bar_w - int(w * 0.025), int(h * 0.035)
    radius = bar_h // 2
    pygame.draw.rect(surface, PARTY_METER_TRACK, (x, y, bar_w, bar_h),
                     border_radius=radius)
    fill_w = int(bar_w * min(1.0, progress))
    if fill_w > 0:
        colour = tuple(
            int(a + (b - a) * progress)
            for a, b in zip(PARTY_METER_EMPTY, PARTY_METER_FULL)
        )
        # Never narrower than the rounded cap, or the border_radius clips the
        # fill into nothing and the first few presses look like they did zero.
        pygame.draw.rect(surface, colour, (x, y, max(bar_h, fill_w), bar_h),
                         border_radius=radius)
    pygame.draw.rect(surface, (210, 220, 240), (x, y, bar_w, bar_h),
                     width=max(2, bar_h // 5), border_radius=radius)


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


DRM_SYS = Path("/sys/class/drm")


def _nudge_connectors(sys_root: Path = DRM_SYS) -> list[str]:
    """Force every HDMI connector that reports *disconnected* on, and keep it
    forced only if a monitor answers over DDC.

    A monitor that has sat in deep sleep can stop asserting hot-plug detect
    while its EDID still reads fine. Seen on the Pi 5 with the ASUS VE276
    after two idle weeks: both connectors ``disconnected``, dmesg saying
    "Cannot find any crtc or sizes", the app waiting on "kmsdrm not
    available" forever, and a card that checked out flawless. ``video=...@60D``
    in cmdline.txt is the cure on a configured card; this is the same cure
    for a card nobody has configured yet.

    The sysfs ``status`` node is the interface, not debugfs ``force``:
    writing ``on`` there re-probes synchronously (verified on the Pi: status
    flips before the write returns), so the EDID check right after is real,
    and ``detect`` is its documented revert. An empty port forced on grows
    the kernel's default modes and SDL would happily drive it blind, which
    is why a port with no EDID is put straight back to real hot-plug
    detection. Root only; a no-op where the tree doesn't exist (dev box,
    tests). Returns the connectors left forced, for the log.
    """
    forced = []
    for conn in sorted(sys_root.glob("card*-HDMI-*")):
        status = conn / "status"
        try:
            if status.read_text().strip() != "disconnected":
                continue
            status.write_text("on")
            if (conn / "edid").read_bytes():
                forced.append(conn.name.partition("-")[2])  # card1-HDMI-A-2
            else:
                status.write_text("detect")
        except OSError:
            continue
    return forced


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
            forced = _nudge_connectors()
            if forced:
                log.info("forced %s on: monitor answers over DDC but not hot-plug",
                         ", ".join(forced))
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
    args = parser.parse_args(argv)

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
    set_silhouettes(cfg.effects.silhouettes)
    prewarm(size[1])

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
                        tune_volume=cfg.music.tune_volume,
                        background_folder=Path(cfg.music.background_folder) if not kiosk
                                          else Path("/opt/lilypad") / cfg.music.background_folder,
                        fade_after=cfg.music.fade_after,
                        reward_seconds=cfg.music.reward_seconds,
                        reward_presses=cfg.music.reward_presses,
                        reward_window=cfg.music.reward_window,
                        party_volume=cfg.music.party_volume,
                        party_duck=cfg.music.party_duck)

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
                    audio.notify_activity(now)
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
            audio.tick(now)
            # The audio engine owns the reward meter (it owns the music), so
            # it says when the party starts; the effect engine says what a
            # party looks like. The party ends when the track does.
            if audio.consume_party_started():
                engine.start_party(now)
            elif engine.party and not audio.party_active:
                engine.end_party(now)
            # Dark screen, dark keyboard.
            lighting.set_sleep(engine.asleep)
            engine.draw(screen)
            # Both overlays go on top of the scene, and neither may paint over
            # a sleeping screen — the whole point of sleep is a dark room.
            if not engine.asleep:
                _draw_party_meter(screen, audio.reward_progress)
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
