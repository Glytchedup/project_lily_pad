"""Procedural sound generation — pure stdlib (math + wave), zero assets.

Generates every non-voice cue as a 22.05 kHz mono 16-bit WAV. Voice files
(letter/number names) are produced separately by espeak-ng in install.sh /
build_voice(); if they're absent the audio engine falls back to these cues.

Run directly to (re)build:  python -m lilypad.audio.synth [dest_dir]
"""

from __future__ import annotations

import math
import random
import shutil
import subprocess
import wave
from pathlib import Path

SAMPLE_RATE = 22050
_TAU = math.tau

# Pentatonic-ish happy scale for chimes (C major pentatonic, one octave up)
_SCALE_HZ = [523.25, 587.33, 659.25, 783.99, 880.00, 1046.50]


def _write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for s in samples:
        v = max(-1.0, min(1.0, s))
        frames += int(v * 32767).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(bytes(frames))


def _env(i: int, n: int, attack: float = 0.01, release: float = 0.3) -> float:
    """Simple attack/release envelope, times as fractions of total length."""
    t = i / n
    if t < attack:
        return t / attack
    if t > 1.0 - release:
        return (1.0 - t) / release
    return 1.0


def _tone(freq: float, dur: float, *, vibrato: float = 0.0,
          harmonics: tuple[float, ...] = (1.0, 0.35, 0.12),
          attack: float = 0.01, release: float = 0.4) -> list[float]:
    n = int(SAMPLE_RATE * dur)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        f = freq * (1.0 + vibrato * math.sin(_TAU * 5.5 * t))
        v = sum(a * math.sin(_TAU * f * (k + 1) * t) for k, a in enumerate(harmonics))
        out.append(v * _env(i, n, attack, release) * 0.5)
    return out


def _mix(*layers: list[float]) -> list[float]:
    n = max(len(x) for x in layers)
    out = [0.0] * n
    for layer in layers:
        for i, s in enumerate(layer):
            out[i] += s
    peak = max(1.0, max(abs(s) for s in out))
    return [s / peak * 0.9 for s in out]


def _shift(samples: list[float], seconds: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * seconds) + samples


def chime(rng: random.Random) -> list[float]:
    f = rng.choice(_SCALE_HZ)
    return _mix(_tone(f, 0.5), _shift(_tone(f * 1.5, 0.4), 0.08))


def pop() -> list[float]:
    """Short pitch-drop blip."""
    n = int(SAMPLE_RATE * 0.12)
    return [
        math.sin(_TAU * (900 - 600 * (i / n)) * (i / SAMPLE_RATE)) * _env(i, n, 0.02, 0.5) * 0.6
        for i in range(n)
    ]


def whoosh() -> list[float]:
    """Filtered-noise sweep (spacebar confetti)."""
    rng = random.Random(7)
    n = int(SAMPLE_RATE * 0.7)
    out, prev = [], 0.0
    for i in range(n):
        # One-pole lowpass over white noise, cutoff swept by envelope position
        alpha = 0.05 + 0.4 * (i / n)
        prev = prev + alpha * (rng.uniform(-1, 1) - prev)
        out.append(prev * _env(i, n, 0.15, 0.4) * 0.9)
    return out


def boom() -> list[float]:
    """Firework thump: low sine drop + noise tail."""
    rng = random.Random(3)
    n = int(SAMPLE_RATE * 0.9)
    out, prev = [], 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        f = 140 - 90 * (i / n)
        prev = prev + 0.12 * (rng.uniform(-1, 1) - prev)
        body = math.sin(_TAU * f * t) * 0.8 + prev * 0.5
        out.append(body * _env(i, n, 0.005, 0.6))
    return out


def sparkle() -> list[float]:
    """Tiny glissando up."""
    n = int(SAMPLE_RATE * 0.25)
    return [
        math.sin(_TAU * (700 + 900 * (i / n)) * (i / SAMPLE_RATE)) * _env(i, n, 0.05, 0.4) * 0.4
        for i in range(n)
    ]


def chord_fanfare() -> list[float]:
    return _mix(
        _tone(_SCALE_HZ[0], 0.6),
        _shift(_tone(_SCALE_HZ[2], 0.5), 0.05),
        _shift(_tone(_SCALE_HZ[4], 0.5), 0.10),
    )


def drum() -> list[float]:
    rng = random.Random(11)
    n = int(SAMPLE_RATE * 0.3)
    out, prev = [], 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        prev = prev + 0.3 * (rng.uniform(-1, 1) - prev)
        out.append((math.sin(_TAU * 90 * t) * 0.9 + prev * 0.4) * _env(i, n, 0.003, 0.7))
    return out


def boing() -> list[float]:
    """Frog hop."""
    n = int(SAMPLE_RATE * 0.35)
    return [
        math.sin(_TAU * (300 + 260 * math.sin(_TAU * 3.2 * (i / n))) * (i / SAMPLE_RATE))
        * _env(i, n, 0.02, 0.4) * 0.5
        for i in range(n)
    ]


def build_cues(dest: Path) -> list[Path]:
    """Generate all non-voice cues into ``dest``. Deterministic seed."""
    rng = random.Random(42)
    written = []
    cues: dict[str, list[float]] = {
        "pop": pop(),
        "whoosh": whoosh(),
        "boom": boom(),
        "sparkle": sparkle(),
        "chord": chord_fanfare(),
        "drum": drum(),
        "boing": boing(),
    }
    for i in range(6):
        cues[f"chime{i}"] = chime(rng)
    for name, samples in cues.items():
        path = dest / f"{name}.wav"
        _write_wav(path, samples)
        written.append(path)
    return written


def build_voice(dest: Path) -> list[Path]:
    """Generate letter/number name WAVs with espeak-ng, if available.
    Slow, friendly child-directed settings. No-op (empty list) without espeak."""
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak is None:
        return []
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    words = {str(letter): letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    words |= {str(n): w for n, w in enumerate(
        ["zero", "one", "two", "three", "four", "five",
         "six", "seven", "eight", "nine", "ten"]) if n > 0}
    words["10"] = "ten"
    for name, word in words.items():
        path = dest / f"{name}.wav"
        subprocess.run(
            [espeak, "-v", "en+f3", "-s", "130", "-p", "60", "-w", str(path), word],
            check=True, capture_output=True,
        )
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    import sys
    args = sys.argv[1:] if argv is None else argv
    dest = Path(args[0]) if args else Path("assets/sounds/generated")
    cue_paths = build_cues(dest)
    voice_paths = build_voice(dest / "voice")
    print(f"wrote {len(cue_paths)} cues to {dest}")
    if voice_paths:
        print(f"wrote {len(voice_paths)} voice files to {dest / 'voice'}")
    else:
        print("espeak-ng not found - skipped voice files (cues will substitute)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
