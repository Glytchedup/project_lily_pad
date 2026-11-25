"""TOML configuration with defaults, using only the stdlib (tomllib)."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AudioConfig:
    mute: bool = False
    volume: float = 0.65
    voice: str = "narrator"
    phrases: bool = True
    count_aloud: bool = True


@dataclass(frozen=True)
class MusicConfig:
    key_notes: bool = True       # every key plays a musical note
    tunes: str = "reward"        # idle | always | off | active | reward
    tune_volume: float = 0.6     # background music level, independent of cues
    background_folder: str = "music"  # personal MP3s for "active"/"reward";
                                       # empty or missing falls back to tunes
    fade_after: float = 30.0     # seconds of no keypress before "active" fades out
    # "reward" mode: a track is earned by whichever lands first.
    reward_seconds: float = 60.0   # cumulative seconds of engaged play
    reward_presses: int = 50       # keypresses
    reward_window: float = 10.0    # gap over which play stops counting as engaged
    party_volume: float = 0.95     # reward track level — the party's whole point
    party_duck: float = 0.25       # key cues drop to this fraction during a party
    bundled_tracks: bool = True
    reward_source: str = "folder_first"
    party_show: bool = True


@dataclass(frozen=True)
class DisplayConfig:
    dev_window: tuple[int, int] = (1280, 720)
    fps: int = 60
    idle_timeout: float = 60.0     # seconds until the attract animation
    sleep_timeout: float = 300.0   # seconds until the screen goes black; 0 = never


@dataclass(frozen=True)
class EffectsConfig:
    max_particles: int = 900
    chord_window: float = 0.15
    trails: bool = True          # translucent frame clear → motion trails
    milestone_every: int = 50    # keypresses per mega-celebration (0 disables)
    silhouettes: bool = True     # traced-outline art for the creatures that have it
    animal_art: str = "painted"
    pip_art: str = "painted"
    max_sprite_width: float = 0.60
    clean_sprites: bool = True
    ecosystem: bool = True
    storybook: str = "both"
    fx_style: str = "painted"
    album: bool = True
    parade: bool = True


@dataclass(frozen=True)
class SceneConfig:
    world: str = "painted"
    parallax: bool = True
    reflections: bool = True
    fireflies: bool = True
    mood_minutes: float = 5.0


@dataclass(frozen=True)
class LightingConfig:
    backend: str = "auto"
    brightness: float = 0.9
    fps: int = 30
    mirror_animals: bool = True


@dataclass(frozen=True)
class EscapeConfig:
    combo: tuple[str, ...] = ("LEFTSHIFT", "RIGHTSHIFT", "BACKSPACE")
    hold_seconds: float = 5.0
    summary_seconds: float = 8.0


@dataclass(frozen=True)
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    music: MusicConfig = field(default_factory=MusicConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    effects: EffectsConfig = field(default_factory=EffectsConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)
    escape: EscapeConfig = field(default_factory=EscapeConfig)
    scene: SceneConfig = field(default_factory=SceneConfig)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _value(data: dict, name: str, default):
    section, key = name.split(".")
    table = data.get(section, {})
    if not isinstance(table, dict):
        raise ValueError(f"{section} must be a TOML table")
    return table.get(key, default)


def _choice(data: dict, name: str, default: str, *choices: str) -> str:
    value = _value(data, name, default)
    if value not in choices:
        raise ValueError(f"{name} must be one of {sorted(choices)}, got {value!r}")
    return value


def _flag(data: dict, name: str, default: bool) -> bool:
    value = _value(data, name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean, got {value!r}")
    return value


def _number(data: dict, name: str, default: float) -> float:
    value = _value(data, name, default)
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def load(path: str | Path | None = None) -> Config:
    """Load config from ``path``; missing file or keys fall back to defaults."""
    data: dict = {}
    if path is not None:
        p = Path(path)
        if p.is_file():
            with p.open("rb") as fh:
                data = tomllib.load(fh)

    audio = data.get("audio", {})
    music = data.get("music", {})
    display = data.get("display", {})
    effects = data.get("effects", {})
    lighting = data.get("lighting", {})
    escape = data.get("escape", {})

    backend = _choice(data, "lighting.backend", LightingConfig.backend,
                      "auto", "razer_hid", "openrazer", "mock")
    tune_mode = _choice(data, "music.tunes", MusicConfig.tunes,
                        "idle", "always", "off", "active", "reward")

    combo = tuple(str(k).upper() for k in escape.get("combo", EscapeConfig.combo))
    if len(combo) < 2:
        raise ValueError("escape.combo needs at least 2 keys — a single key is too easy to mash")

    dev_window = display.get("dev_window", (1280, 720))
    if not (isinstance(dev_window, (list, tuple)) and len(dev_window) == 2):
        raise ValueError("display.dev_window must be [width, height]")

    silhouettes = bool(effects.get("silhouettes", EffectsConfig.silhouettes))
    default_art = EffectsConfig.animal_art if silhouettes else "drawn"
    mood_minutes = _number(data, "scene.mood_minutes", SceneConfig.mood_minutes)
    if mood_minutes <= 0:
        raise ValueError(f"scene.mood_minutes must be positive, got {mood_minutes!r}")

    return Config(
        audio=AudioConfig(
            mute=bool(audio.get("mute", False)),
            volume=_clamp(float(audio.get("volume", 0.65)), 0.0, 1.0),
            voice=_choice(data, "audio.voice", AudioConfig.voice, "narrator", "espeak"),
            phrases=_flag(data, "audio.phrases", AudioConfig.phrases),
            count_aloud=_flag(data, "audio.count_aloud", AudioConfig.count_aloud),
        ),
        music=MusicConfig(
            key_notes=bool(music.get("key_notes", True)),
            tunes=tune_mode,
            tune_volume=_clamp(float(music.get("tune_volume", 0.6)), 0.0, 1.0),
            background_folder=str(music.get("background_folder", "music")),
            fade_after=max(0.0, float(music.get("fade_after", 30.0))),
            reward_seconds=max(1.0, float(music.get("reward_seconds", 60.0))),
            reward_presses=max(1, int(music.get("reward_presses", 50))),
            reward_window=max(0.5, float(music.get("reward_window", 10.0))),
            party_volume=_clamp(float(music.get("party_volume", 0.95)), 0.0, 1.0),
            party_duck=_clamp(float(music.get("party_duck", 0.25)), 0.0, 1.0),
            bundled_tracks=_flag(data, "music.bundled_tracks", MusicConfig.bundled_tracks),
            reward_source=_choice(data, "music.reward_source", MusicConfig.reward_source,
                                  "folder_first", "bundled", "generated"),
            party_show=_flag(data, "music.party_show", MusicConfig.party_show),
        ),
        display=DisplayConfig(
            dev_window=(int(dev_window[0]), int(dev_window[1])),
            fps=int(display.get("fps", 60)),
            idle_timeout=float(display.get("idle_timeout", 60.0)),
            sleep_timeout=max(0.0, float(display.get("sleep_timeout", 300.0))),
        ),
        effects=EffectsConfig(
            max_particles=int(effects.get("max_particles", 900)),
            chord_window=float(effects.get("chord_window", 0.15)),
            trails=bool(effects.get("trails", True)),
            milestone_every=max(0, int(effects.get("milestone_every", 50))),
            silhouettes=silhouettes,
            animal_art=_choice(data, "effects.animal_art", default_art, "painted", "traced", "drawn"),
            pip_art=_choice(data, "effects.pip_art", EffectsConfig.pip_art, "painted", "drawn"),
            max_sprite_width=_clamp(
                _number(data, "effects.max_sprite_width", EffectsConfig.max_sprite_width), 0.0, 1.0
            ),
            clean_sprites=_flag(data, "effects.clean_sprites", EffectsConfig.clean_sprites),
            ecosystem=_flag(data, "effects.ecosystem", EffectsConfig.ecosystem),
            storybook=_choice(data, "effects.storybook", EffectsConfig.storybook,
                              "encore", "attract", "both", "off"),
            fx_style=_choice(data, "effects.fx_style", EffectsConfig.fx_style, "painted", "glow"),
            album=_flag(data, "effects.album", EffectsConfig.album),
            parade=_flag(data, "effects.parade", EffectsConfig.parade),
        ),
        scene=SceneConfig(
            world=_choice(data, "scene.world", SceneConfig.world, "painted", "drawn"),
            parallax=_flag(data, "scene.parallax", SceneConfig.parallax),
            reflections=_flag(data, "scene.reflections", SceneConfig.reflections),
            fireflies=_flag(data, "scene.fireflies", SceneConfig.fireflies),
            mood_minutes=mood_minutes,
        ),
        lighting=LightingConfig(
            backend=backend,
            brightness=_clamp(float(lighting.get("brightness", 0.9)), 0.0, 1.0),
            fps=int(lighting.get("fps", 30)),
            mirror_animals=_flag(data, "lighting.mirror_animals", LightingConfig.mirror_animals),
        ),
        escape=EscapeConfig(
            combo=combo,
            hold_seconds=float(escape.get("hold_seconds", 5.0)),
            summary_seconds=max(
                0.0, _number(data, "escape.summary_seconds", EscapeConfig.summary_seconds)
            ),
        ),
    )
