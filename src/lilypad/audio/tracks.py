"""Optional audio asset manifests and a transport-independent party beat clock."""

from __future__ import annotations

import json
import logging
import math
import tomllib
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

log = logging.getLogger(__name__)
# Adding frame deltas can fall a few ulps short of an exact beat boundary.
# The writer rounds timestamps to microseconds.
_TIME_EPSILON = 1e-9


def read_audio_manifest(directory: Path) -> dict[tuple[str, str], Path]:
    """Index existing audio files in [group.key] tables beside manifest.toml."""
    try:
        with (directory / "manifest.toml").open("rb") as stream:
            document = tomllib.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Ignoring audio manifest in %s: %s", directory, exc)
        return {}

    root = directory.resolve()
    files = {}
    for group, rows in document.items():
        if not isinstance(rows, dict):
            continue
        for key, row in rows.items():
            filename = row.get("file") if isinstance(row, dict) else None
            if not isinstance(filename, str):
                continue
            relative = Path(filename)
            if (relative.anchor or ".." in relative.parts
                    or relative.suffix.lower() not in (".ogg", ".mp3", ".wav")):
                continue
            try:
                path = (root / relative).resolve()
                if path.is_relative_to(root) and path.is_file():
                    files[group, key] = path
            except (OSError, ValueError, RuntimeError):
                continue
    return files


def load_bundled_tracks(directory: Path) -> tuple[Path, ...]:
    """Return playable track paths in manifest order, without decoding audio."""
    return tuple(path for (group, _), path in read_audio_manifest(directory).items()
                 if group == "tracks")


def reward_source_order(reward_source: str) -> tuple[str, ...]:
    """Try each source until it supplies tracks. Generated mode uses synth tunes only."""
    if reward_source == "generated":
        return ("generated",)
    if reward_source == "bundled":
        return ("bundled", "folder", "generated")
    return ("folder", "bundled", "generated")


@dataclass(frozen=True)
class BeatMap:
    bpm: float
    offset: float
    beats: tuple[float, ...]
    downbeats: tuple[float, ...]
    drops: tuple[float, ...]


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("expected a number")
    if not math.isfinite(value) or value < 0:
        raise ValueError("expected a finite, non-negative number")
    return float(value)


def _timestamps(values: object) -> tuple[float, ...]:
    if not isinstance(values, list):
        raise TypeError("expected a list of timestamps in seconds")
    times = tuple(_number(value) for value in values)
    if any(right <= left for left, right in pairwise(times)):
        raise ValueError("timestamps must be strictly increasing")
    return times


def load_beat_map(track: Path) -> BeatMap | None:
    """Read <full filename>.beats.json, for bundled and parent tracks alike.

    The writer emits absolute track seconds. Offset is already in beats[0].
    A missing or unusable map leaves the audio track available for playback.
    """
    sidecar = track.with_name(track.name + ".beats.json")
    try:
        with sidecar.open("rb") as stream:
            data = json.load(stream)
        bpm = _number(data["bpm"])
        offset = _number(data["offset"])
        beats = _timestamps(data["beats"])
        downbeats = _timestamps(data["downbeats"])
        drops = _timestamps(data.get("drops", []))
        if not 60 <= bpm <= 180:
            raise ValueError("bpm outside 60–180")
        if not beats or not math.isclose(beats[0], offset, abs_tol=1e-6, rel_tol=0):
            raise ValueError("offset must mark the first beat")
        if not set(downbeats).issubset(beats):
            raise ValueError("downbeats must be beat timestamps")
        return BeatMap(bpm, offset, beats, downbeats, drops)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError) as exc:
        log.warning("Ignoring beat map %s: %s", sidecar, exc)
        return None


class BeatClock:
    """Sample an absolute track position; advance by frame dt between mixer reads.

    Beats and bars are zero-based (-1 during the lead-in). Phase runs from
    zero up to one across the actual interval. A drop stays active from its
    timestamp to the next beat, so a frame need not land on the exact onset.
    Without a sidecar the clock starts in 4/4 at 120 BPM. Past the last
    mapped beat it continues at the declared tempo.
    """

    def __init__(self, beatmap: BeatMap | None = None, music_pos_ms: float = 0) -> None:
        self._period = 60.0 / beatmap.bpm if beatmap else 0.5
        self._beats = beatmap.beats if beatmap else (0.0,)
        self._drops = beatmap.drops if beatmap else ()
        self._bar_starts = (0,)
        if beatmap and beatmap.downbeats:
            self._bar_starts = tuple(bisect_left(self._beats, t) for t in beatmap.downbeats)
        if not math.isfinite(music_pos_ms):
            music_pos_ms = 0.0
        self._sample(max(0.0, music_pos_ms / 1000.0))

    def advance(self, dt: float) -> None:
        """Advance by elapsed seconds, including when no mixer position exists."""
        if dt > 0 and math.isfinite(dt):
            self._sample(self._position + dt)

    def resync(self, music_pos_ms: float) -> None:
        """Anchor to absolute track milliseconds; SDL's stopped sentinel is -1."""
        if music_pos_ms >= 0 and math.isfinite(music_pos_ms):
            self._sample(music_pos_ms / 1000.0)

    def _sample(self, position: float) -> None:
        self._position = position
        index = bisect_right(self._beats, position + _TIME_EPSILON) - 1
        if index < 0:
            self.beat_index = self.bar = -1
            self.beat_phase = 0.0
            self.time_to_next_beat = self._beats[0] - position
            self.is_drop = False
            return

        start = self._beats[index]
        if index + 1 < len(self._beats):
            interval = self._beats[index + 1] - start
        else:
            interval = self._period
            extra = math.floor((position - start + _TIME_EPSILON) / interval)
            index += extra
            start += extra * interval
        elapsed = max(0.0, position - start)
        self.beat_index = index
        self.beat_phase = elapsed / interval
        self.time_to_next_beat = interval - elapsed
        self.bar = bisect_right(self._bar_starts, index) - 1
        if index >= self._bar_starts[-1]:
            self.bar += (index - self._bar_starts[-1]) // 4
        marker = bisect_right(self._drops, position + _TIME_EPSILON) - 1
        self.is_drop = marker >= 0 and self._drops[marker] >= start - _TIME_EPSILON
