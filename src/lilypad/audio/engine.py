"""Audio engine: plays a cue for every action via pygame.mixer.

Degrades to silence — never crashes — if the mixer can't initialize (no
HDMI audio, dev box without an output). ``mute = true`` in config
short-circuits everything.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..input.mapper import Action

log = logging.getLogger(__name__)


class AudioEngine:
    def __init__(self, sounds_dir: str | Path, *, mute: bool = False,
                 volume: float = 0.8, autogen: bool = True) -> None:
        self.mute = mute
        self.volume = volume
        self.sounds_dir = Path(sounds_dir)
        self._sounds: dict[str, object] = {}
        self._chime_cycle = 0
        self._enabled = False
        if mute:
            log.info("audio: muted by config")
            return
        try:
            import pygame
            pygame.mixer.init(frequency=22050, channels=2, buffer=512)
            pygame.mixer.set_num_channels(16)
            self._enabled = True
        except Exception as exc:              # noqa: BLE001 — silence, never crash
            log.warning("audio unavailable (%s) — running silent", exc)
            return
        if autogen and not (self.sounds_dir / "pop.wav").is_file():
            log.info("audio: generating cues into %s", self.sounds_dir)
            from .synth import build_cues
            build_cues(self.sounds_dir)

    def _get(self, name: str):
        if not self._enabled:
            return None
        if name not in self._sounds:
            import pygame
            path = self.sounds_dir / f"{name}.wav"
            if not path.is_file():
                self._sounds[name] = None
            else:
                sound = pygame.mixer.Sound(str(path))
                sound.set_volume(self.volume)
                self._sounds[name] = sound
        return self._sounds[name]

    def _play(self, *names: str) -> None:
        """Play the first available sound from ``names``."""
        if not self._enabled or self.mute:
            return
        for name in names:
            sound = self._get(name)
            if sound is not None:
                sound.play()
                return

    def _next_chime(self) -> str:
        self._chime_cycle = (self._chime_cycle + 1) % 6
        return f"chime{self._chime_cycle}"

    def on_action(self, action: Action) -> None:
        kind = action.kind
        if kind == "letter":
            self._play(f"voice/{action.letter}", self._next_chime())
        elif kind == "number":
            self._play(f"voice/{action.count}", "pop")
        elif kind == "space":
            self._play("whoosh")
        elif kind == "enter":
            self._play("boom")
        elif kind == "arrow":
            self._play("boing")
        elif kind == "chord":
            self._play("chord")
        elif kind == "mash_start":
            self._play("chord")
        elif kind == "special":
            if action.letter == "drum":
                self._play("drum")
            elif action.letter == "vacuum":
                self._play("whoosh")
            else:
                self._play(self._next_chime())
        elif kind == "sparkle":
            self._play("sparkle")

    def close(self) -> None:
        if self._enabled:
            try:
                import pygame
                pygame.mixer.quit()
            except Exception:                 # noqa: BLE001
                pass
            self._enabled = False
