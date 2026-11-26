"""Measure the renderer, including input, spawns and display.flip(), on a fixed-step replay."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from itertools import count
import json
import math
import os
from pathlib import Path
import random
import sys
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

from .__main__ import _default_mode, _find_config
from .config import Config, load
from .effects import animal_art, animals, critter, letters
from .effects.assets import asset_root
from .effects.engine import ANIMAL_TYPES, EffectEngine
from .effects.glow import set_fx_style
from .effects.layout import layout_for
from .input.base import KeyEvent
from .input.mapper import KeyMapper, classify

SEED = 42
# Six taps/s stays below the rate-triggered mash wash, so heavy exercises
# trails even when all five animal slots and most glyph slots are occupied.
_SCRIPTS = {
    "heavy": (6, ("G", "O", "W", "C", "B", "SPACE", "5", "ENTER", "F7", "R", "RIGHT")),
    "party": (2, ("G", "ENTER", "D", "SPACE", "3", "F9")),
    "parade": (0, ()),
    "idle": (0, ()),
}


def _size(value: str) -> tuple[int, int]:
    try:
        w, h = (int(n) for n in value.lower().split("x"))
        if w > 0 and h > 0:
            return w, h
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected positive WIDTHxHEIGHT")


def _sprite_cache_bytes() -> int:
    # Count actual allocations once even if two poses alias the same Surface.
    caches = (animal_art._animal_cache, animal_art._flip_cache, animal_art._mini_cache)
    sprites = {sprite for cache in caches for sprite in cache.values()}
    return sum(s.get_bytesize() * s.get_width() * s.get_height() for s in sprites)


def _parade_cache_bytes(parade):
    """Temporary parade pixels, excluding poses borrowed from the resident cast."""
    resident = set(animal_art._animal_cache.values()) | set(animal_art._flip_cache.values())
    surfaces = {sprite.get_abs_parent() for sprite in parade._frames.values()}
    return sum(s.get_pitch() * s.get_height() for s in surfaces - resident)


def _peak_rss_bytes() -> int | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("page_faults", wintypes.DWORD),
                        ("peak_working_set", ctypes.c_size_t), ("other", ctypes.c_size_t * 7)]

        counters = ProcessMemoryCounters()
        counters.size = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess
        process.restype = wintypes.HANDLE
        if ctypes.windll.psapi.GetProcessMemoryInfo(
                wintypes.HANDLE(process()), ctypes.byref(counters), counters.size):
            return counters.peak_working_set
    try:
        import psutil
    except ImportError:
        pass
    else:
        try:
            info = psutil.Process().memory_info()
            for field in ("peak_wset", "peak_rss"):
                peak = getattr(info, field, None)
                if peak is not None:
                    return peak
        except (psutil.Error, OSError):
            pass
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii", errors="replace").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss if sys.platform == "darwin" else rss * 1024
    except (ImportError, OSError):
        return None


def _spawn_windows(spawns, frame_starts, frame_ms):
    """Include the spawn frame and every frame starting within the next 500 ms."""
    windows = []
    for frame, animal, spawned_at in spawns:
        stop = bisect_right(frame_starts, spawned_at + 0.5, lo=frame)
        windows.append({"animal": animal, "frame": frame,
                        "worst_ms": max(frame_ms[frame:stop])})
    return windows


def _measure(engine: EffectEngine, screen: pygame.Surface, scenario: str,
             seconds: float, cfg: Config) -> dict:
    fps = cfg.display.fps
    dt = 1 / fps
    mapper = KeyMapper(chord_window=cfg.effects.chord_window)
    rate, keys = _SCRIPTS[scenario]
    # Idle benchmarks start at the attract threshold, as if the room just emptied.
    engine.last_action_time = -engine.idle_timeout if scenario == "idle" else 0.0
    next_tap = 0
    frame_starts, frame_ms, spawns = [], [], []
    min_scale = engine.ctx.scale
    peak_parade_bytes = last_pose_count = 0
    replay_frames = math.ceil(seconds * fps)
    start = time.perf_counter()

    def dispatch(action):
        before = len(engine.effects)
        engine.spawn(action, now)
        # A cap or the degradation ladder may drop an animal. Measure only
        # accepted spawns, with their own deadline even when windows overlap.
        for effect in engine.effects[before:]:
            if isinstance(effect, ANIMAL_TYPES):
                spawns.append((frame, effect.name, time.perf_counter() - start))

    for frame in count():
        began = time.perf_counter()
        replaying = frame < replay_frames
        # A spawn on the last scripted tap still gets its full half second.
        # Drain those frames without new input or biasing the replay percentiles.
        if not replaying and (not spawns or began - start > spawns[-1][2] + 0.5):
            break
        if any(event.type == pygame.QUIT for event in pygame.event.get()):
            raise SystemExit("benchmark interrupted by display close")
        now = frame / fps
        if scenario == "party" and frame == 0:
            engine.start_party(now)
        if scenario == "parade" and frame == 0:
            engine.letters_seen.update("ABCDEFGHIJKLMNOPQRSTUVWXY")
            dispatch(classify("Z"))
        while replaying and keys and next_tap * fps <= frame * rate:
            key = keys[next_tap % len(keys)]
            engine.wake(now)
            engine.attract_key(key)
            for pressed in (True, False):
                for action in mapper.feed(KeyEvent(key, pressed, now)):
                    dispatch(action)
            next_tap += 1
        for action in mapper.poll_holds(now):
            dispatch(action)
        engine.update(dt, now)
        engine.draw(screen)
        if engine.album is not None:
            engine.album.draw(screen)
        pygame.display.flip()
        cost = time.perf_counter() - began
        frame_starts.append(began - start)
        frame_ms.append(cost * 1000)
        engine.note_frame_time(cost)
        parade = engine.parade or engine.trio
        pose_count = len(parade._frames) if parade is not None else 0
        if pose_count > last_pose_count:
            peak_parade_bytes = max(peak_parade_bytes, _parade_cache_bytes(parade))
        last_pose_count = pose_count
        if replaying:
            min_scale = min(min_scale, engine.ctx.scale)
        # Pacing (including any scheduler delay) never enters the work timer.
        delay = began + dt - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        if frame + 1 == replay_frames:
            elapsed = time.perf_counter() - start

    windows = _spawn_windows(spawns, frame_starts, frame_ms)
    ordered = sorted(frame_ms[:replay_frames])
    percentiles = {f"p{p}": ordered[math.ceil(p / 100 * len(ordered)) - 1]
                   for p in (50, 95, 99)}
    return {
        "scenario": scenario, "seed": SEED, "size": list(screen.get_size()),
        "driver": pygame.display.get_driver(), "seconds": seconds,
        "frames": replay_frames, "spawn_tail_frames": len(frame_ms) - replay_frames,
        "target_fps": fps, "wall_seconds": elapsed,
        "achieved_fps": replay_frames / elapsed, "min_scale": min_scale,
        "frame_ms": percentiles, "animal_spawns": windows,
        "worst_spawn_frame_ms": max((w["worst_ms"] for w in windows), default=None),
        "sprite_cache_bytes": _sprite_cache_bytes(), "peak_rss_bytes": _peak_rss_bytes(),
        "peak_additional_parade_sprite_bytes": peak_parade_bytes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=_SCRIPTS, default="heavy")
    parser.add_argument("--seconds", type=float, default=20,
                        help="seconds of game time at the configured frame rate")
    parser.add_argument("--size", type=_size, default=(1920, 1080))
    parser.add_argument("--config", type=Path, help="path to config.toml")
    parser.add_argument("--json", type=Path, help="write the report here (default: stdout)")
    parser.add_argument("--display", action="store_true", help="use a real display")
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be positive and finite")
    if args.config and not args.config.is_file():
        parser.error(f"config file does not exist: {args.config}")
    config_path = args.config or _find_config(None)
    cfg = load(config_path)
    if cfg.display.fps < 1:
        parser.error("display.fps must be positive")

    driver = os.environ.get("SDL_VIDEODRIVER")
    kiosk = args.display and (_default_mode() == "kiosk" or driver == "kmsdrm")
    if not args.display:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    elif kiosk:
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    elif driver in ("dummy", "offscreen"):
        del os.environ["SDL_VIDEODRIVER"]
    try:
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(args.size, pygame.FULLSCREEN if kiosk else 0)
        if args.display and pygame.display.get_driver() in ("dummy", "offscreen"):
            parser.error("--display requires a real SDL display")
        if screen.get_size() != args.size:
            parser.error(f"display opened at {screen.get_size()}, requested {args.size}")
        w, h = screen.get_size()
        root = asset_root(kiosk=kiosk)
        animal_art.set_art_mode(cfg.effects.animal_art, root=root)
        critter.set_pip_art(cfg.effects.pip_art, root=root)
        letters.set_letter_art(cfg.effects.animal_art, root=root)
        letters.set_eye_art(cfg.effects.animal_art, root=root)
        set_fx_style(cfg.effects.fx_style, root=root)
        animals.prewarm(h, screen_width=w, max_sprite_width=cfg.effects.max_sprite_width,
                       layout=layout_for(cfg.scene.world))
        engine = EffectEngine.from_config((w, h), cfg, root=root, rng=random.Random(SEED), lily_seed=SEED)
        try:
            report = _measure(engine, screen, args.scenario, args.seconds, cfg)
        finally:
            engine.close()
        report["reflection_cache_bytes"] = engine.reflections.bytes_used
        report["config"] = str(config_path) if config_path else None
    finally:
        pygame.quit()
    output = json.dumps(report, indent=2, allow_nan=False)
    if args.json:
        args.json.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
