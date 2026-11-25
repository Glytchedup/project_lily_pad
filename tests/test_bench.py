"""Benchmark CLI, metric boundaries and read-only cache accounting."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pygame
import pytest

from lilypad import bench
from lilypad.config import Config
from lilypad.effects.engine import EffectEngine


@pytest.mark.parametrize("scenario", ["heavy", "party", "idle"])
def test_headless_cli_writes_json(tmp_path, scenario):
    config = tmp_path / "settings.toml"
    config.write_text('[effects]\nanimal_art = "drawn"\nclean_sprites = true\n'
                      '[display]\nfps = 30\n', encoding="utf-8")
    out = tmp_path / "out.json"
    src = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ, PYTHONPATH=str(src), SDL_VIDEODRIVER="unused-driver",
               LILYPAD_ART_DIR=str(tmp_path))
    subprocess.run([sys.executable, "-m", "lilypad.bench", "--scenario", scenario,
                    "--seconds", "1", "--size", "224x128", "--config", str(config),
                    "--json", str(out)], check=True, env=env, timeout=30)
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["driver"] == "dummy" and result["size"] == [224, 128]
    assert result["scenario"] == scenario and result["config"] == str(config)
    assert result["frames"] == result["target_fps"] == 30
    ms = result["frame_ms"]
    assert 0 < ms["p50"] <= ms["p95"] <= ms["p99"]
    assert result["peak_rss_bytes"] is None or result["peak_rss_bytes"] > 0
    windows = result["animal_spawns"]
    if scenario == "idle":
        assert windows == [] and result["worst_spawn_frame_ms"] is None
    else:
        assert windows[0]["animal"] == "giraffe" and windows[0]["frame"] == 0
        assert result["worst_spawn_frame_ms"] == max(w["worst_ms"] for w in windows)
        assert result["sprite_cache_bytes"] > 0


def test_overlapping_spawn_windows_include_spawn_and_exact_deadline():
    starts = [0.0, 0.10, 0.16, 0.56, 0.60, 0.61, 0.70]
    costs = [99, 8, 1, 21, 35, 51, 52]
    spawns = [(1, "duck", 0.10), (2, "cow", 0.16), (6, "owl", 0.70)]
    assert bench._spawn_windows(spawns, starts, costs) == [
        {"frame": 1, "animal": "duck", "worst_ms": 35},
        {"frame": 2, "animal": "cow", "worst_ms": 51},
        {"frame": 6, "animal": "owl", "worst_ms": 52},
    ]


def test_frame_cost_includes_flip_but_excludes_pacing(monkeypatch):
    clock = [0.0]

    def advance(seconds):
        clock[0] += seconds

    engine = EffectEngine((160, 96))
    monkeypatch.setattr(bench.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(bench.time, "sleep", advance)
    monkeypatch.setattr(pygame.display, "flip", lambda: advance(0.012))
    report = bench._measure(engine, pygame.Surface(engine.size), "idle", 1.0, Config())
    assert engine.attract is not None
    assert report["frame_ms"] == pytest.approx({"p50": 12, "p95": 12, "p99": 12})
    assert report["wall_seconds"] == pytest.approx(1.0)


def test_late_spawn_measures_hitch_after_the_last_scripted_frame(monkeypatch):
    clock = [0.0]

    def advance(seconds):
        clock[0] += seconds

    engine = EffectEngine((160, 96))
    def flip():
        # The one scripted frame is cheap. The half-second spawn window
        # also sees a slow present once the scripted input has ended.
        advance(0.04 if 0.3 < clock[0] < 0.4 else 0.002)

    monkeypatch.setattr(bench.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(bench.time, "sleep", advance)
    monkeypatch.setattr(pygame.display, "flip", flip)
    report = bench._measure(engine, pygame.Surface(engine.size), "heavy", 1 / 60, Config())
    assert report["frames"] == 1 and report["spawn_tail_frames"] > 0
    assert report["frame_ms"]["p99"] == pytest.approx(2)
    assert report["worst_spawn_frame_ms"] == pytest.approx(40)


def test_cache_counts_unique_normal_mirrored_and_mini_surfaces(monkeypatch):
    animal = pygame.Surface((3, 5), pygame.SRCALPHA)
    flip = animal.copy()
    mini = pygame.Surface((2, 4), depth=24)
    caches = ({"idle": animal, "step": animal}, {"mirrored": flip}, {"mini": mini})
    for name, cache in zip(("_animal_cache", "_flip_cache", "_mini_cache"), caches):
        monkeypatch.setattr(bench.animal_art, name, cache)
    assert bench._sprite_cache_bytes() == 2 * (4 * 3 * 5) + 3 * 2 * 4
    assert caches == ({"idle": animal, "step": animal}, {"mirrored": flip}, {"mini": mini})
