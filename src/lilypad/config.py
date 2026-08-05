"""TOML configuration with defaults, using only the stdlib (tomllib)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AudioConfig:
    mute: bool = False
    volume: float = 0.8


@dataclass(frozen=True)
class DisplayConfig:
    dev_window: tuple[int, int] = (1280, 720)
    fps: int = 60
    idle_timeout: float = 60.0


@dataclass(frozen=True)
class EffectsConfig:
    max_particles: int = 900
    chord_window: float = 0.15


@dataclass(frozen=True)
class LightingConfig:
    backend: str = "auto"
    brightness: float = 0.9
    fps: int = 30


@dataclass(frozen=True)
class EscapeConfig:
    combo: tuple[str, ...] = ("LEFTSHIFT", "RIGHTSHIFT", "BACKSPACE")
    hold_seconds: float = 5.0


@dataclass(frozen=True)
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    effects: EffectsConfig = field(default_factory=EffectsConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)
    escape: EscapeConfig = field(default_factory=EscapeConfig)


_VALID_BACKENDS = {"auto", "razer_hid", "openrazer", "mock"}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def load(path: str | Path | None = None) -> Config:
    """Load config from ``path``; missing file or keys fall back to defaults."""
    data: dict = {}
    if path is not None:
        p = Path(path)
        if p.is_file():
            with p.open("rb") as fh:
                data = tomllib.load(fh)

    audio = data.get("audio", {})
    display = data.get("display", {})
    effects = data.get("effects", {})
    lighting = data.get("lighting", {})
    escape = data.get("escape", {})

    backend = str(lighting.get("backend", "auto"))
    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"lighting.backend must be one of {sorted(_VALID_BACKENDS)}, got {backend!r}"
        )

    combo = tuple(str(k).upper() for k in escape.get("combo", EscapeConfig.combo))
    if len(combo) < 2:
        raise ValueError("escape.combo needs at least 2 keys — a single key is too easy to mash")

    dev_window = display.get("dev_window", (1280, 720))
    if not (isinstance(dev_window, (list, tuple)) and len(dev_window) == 2):
        raise ValueError("display.dev_window must be [width, height]")

    return Config(
        audio=AudioConfig(
            mute=bool(audio.get("mute", False)),
            volume=_clamp(float(audio.get("volume", 0.8)), 0.0, 1.0),
        ),
        display=DisplayConfig(
            dev_window=(int(dev_window[0]), int(dev_window[1])),
            fps=int(display.get("fps", 60)),
            idle_timeout=float(display.get("idle_timeout", 60.0)),
        ),
        effects=EffectsConfig(
            max_particles=int(effects.get("max_particles", 900)),
            chord_window=float(effects.get("chord_window", 0.15)),
        ),
        lighting=LightingConfig(
            backend=backend,
            brightness=_clamp(float(lighting.get("brightness", 0.9)), 0.0, 1.0),
            fps=int(lighting.get("fps", 30)),
        ),
        escape=EscapeConfig(
            combo=combo,
            hold_seconds=float(escape.get("hold_seconds", 5.0)),
        ),
    )
