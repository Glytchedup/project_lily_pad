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

# Count-along ladder: C major pentatonic from C4, wrapping an octave up at the
# sixth step so ten objects climb a full "one ... ten" staircase.
_COUNT_HZ = [261.63, 293.66, 329.63, 392.00, 440.00,
             523.25, 587.33, 659.25, 783.99, 880.00]


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


def _glide(f0: float, f1: float, dur: float, *,
           vibrato: float = 0.0, vib_rate: float = 5.5,
           harmonics: tuple[float, ...] = (1.0, 0.35, 0.12),
           attack: float = 0.01, release: float = 0.4,
           gain: float = 0.5, curve: float = 1.0) -> list[float]:
    """Swept-pitch tone. Phase is accumulated (not f*t) so the slide really
    slides instead of smearing; ``curve`` > 1 delays the sweep, < 1 front-loads
    it (a fast pitch dip at the attack)."""
    n = max(1, int(SAMPLE_RATE * dur))
    out = []
    phase = 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        f = f0 + (f1 - f0) * (i / n) ** curve
        f *= 1.0 + vibrato * math.sin(_TAU * vib_rate * t)
        phase += _TAU * f / SAMPLE_RATE
        v = sum(a * math.sin(phase * (k + 1)) for k, a in enumerate(harmonics))
        out.append(v * _env(i, n, attack, release) * gain)
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


# ------------------------------------------------- farm animals (cartoon, not real)
# Deliberate caricatures: a 2-year-old should recognise "moo!" instantly, so
# these lean on the *shape* of each sound (slide, bleat, grunt) rather than any
# attempt at realism.

# Nasal/reedy partial stacks — lots of upper harmonics at near-equal weight is
# what makes a tone read as "buzzy voice" instead of "flute".
_MOO_HARMONICS = (1.0, 0.50, 0.28, 0.14, 0.07)
_QUACK_HARMONICS = (1.0, 0.80, 0.65, 0.50, 0.40, 0.30, 0.22)
_OINK_HARMONICS = (1.0, 0.60, 0.40, 0.25, 0.15)


def moo() -> list[float]:
    """Cow: low downward slide plus a slower, lower second syllable (~0.9 s)."""
    first = _glide(110, 96, 0.34, vibrato=0.02, vib_rate=6.0,
                   harmonics=_MOO_HARMONICS, attack=0.06, release=0.25, gain=0.45)
    second = _glide(100, 85, 0.50, vibrato=0.025, vib_rate=4.5,
                    harmonics=_MOO_HARMONICS, attack=0.08, release=0.45, gain=0.5)
    return _mix(first, _shift(second, 0.38))


def quack() -> list[float]:
    """Duck: two short buzzy nasal bursts with a fast decay (~0.5 s)."""
    first = _glide(320, 280, 0.16, harmonics=_QUACK_HARMONICS,
                   attack=0.01, release=0.6, gain=0.45)
    second = _glide(300, 250, 0.20, harmonics=_QUACK_HARMONICS,
                    attack=0.01, release=0.65, gain=0.45)
    return _mix(first, _shift(second, 0.28))


def oink() -> list[float]:
    """Pig: two quick low grunts, hard attack, pitch dipping away (~0.5 s)."""
    first = _glide(165, 120, 0.18, harmonics=_OINK_HARMONICS, curve=0.6,
                   attack=0.004, release=0.55, gain=0.5)
    second = _glide(150, 110, 0.20, harmonics=_OINK_HARMONICS, curve=0.6,
                    attack=0.004, release=0.60, gain=0.5)
    return _mix(first, _shift(second, 0.28))


def baa() -> list[float]:
    """Sheep: mid tone wobbled by a strong fast vibrato — the bleat (~0.8 s)."""
    return _mix(_glide(228, 205, 0.8, vibrato=0.075, vib_rate=13.0,
                       harmonics=(1.0, 0.55, 0.35, 0.20, 0.10),
                       attack=0.05, release=0.35, gain=0.5))


def count_note(i: int) -> list[float]:
    """Bright chime for the i-th counted object (0-based), climbing the
    pentatonic ladder so "one, two, three ..." rises in pitch. Index is
    clamped, so out-of-range callers get the top note rather than an error."""
    f = _COUNT_HZ[max(0, min(i, len(_COUNT_HZ) - 1))]
    return _mix(
        _tone(f, 0.25, harmonics=(1.0, 0.25, 0.12), attack=0.005, release=0.55),
        _tone(f * 2.0, 0.22, harmonics=(0.30,), attack=0.005, release=0.60),
    )


def celebration() -> list[float]:
    """Milestone fanfare (~2 s): rising arpeggio into a sparkling chord."""
    arpeggio = [
        _shift(_tone(f, 0.35, harmonics=(1.0, 0.40, 0.18),
                     attack=0.005, release=0.5), step * 0.13)
        for step, f in enumerate(_SCALE_HZ[:4])
    ]
    chord = [
        _shift(_tone(f, 1.35, harmonics=(1.0, 0.35, 0.15, 0.07),
                     attack=0.01, release=0.55), 0.55)
        for f in (_SCALE_HZ[0], _SCALE_HZ[2], _SCALE_HZ[4], _SCALE_HZ[5])
    ]
    sparkles = [_shift(sparkle(), t) for t in (0.60, 1.00, 1.45)]
    return _mix(*arpeggio, *chord, *sparkles)


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
        "moo": moo(),
        "quack": quack(),
        "oink": oink(),
        "baa": baa(),
        "celebration": celebration(),
    }
    for i in range(6):
        cues[f"chime{i}"] = chime(rng)
    for i in range(len(_COUNT_HZ)):
        cues[f"count_{i}"] = count_note(i)
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
