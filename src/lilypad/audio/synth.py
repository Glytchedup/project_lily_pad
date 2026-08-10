"""Procedural sound generation — pure stdlib (math + wave), zero assets.

Generates every non-voice cue as a 22.05 kHz mono 16-bit WAV. Voice files
(letter/number names) are produced separately by espeak-ng in install.sh /
build_voice(); if they're absent the audio engine falls back to these cues.

Two families live here:

* **musical** — key notes, chords and the celebration cadence, built from
  :mod:`lilypad.audio.music` pitches through the ``Voice`` renderer below;
* **character** — whoosh, boom, drum, animal calls. These are caricatures, not
  music, and are deliberately left as raw shaped tones.

Run directly to (re)build:  python -m lilypad.audio.synth [dest_dir]
"""

from __future__ import annotations

import array
import math
import random
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from .music import (
    CHORD_NAMES, COUNT_MIDIS, MASH_CHORD, NOTE_MIDIS,
    midi_to_hz, triad_midis,
)

SAMPLE_RATE = 22050
_TAU = math.tau

#: Bump whenever the *sound* of any cue changes. ``build_cues`` stamps it into
#: ``cues.version`` and the audio engine regenerates any sounds dir whose stamp
#: doesn't match — otherwise a device that already has WAVs on disk keeps
#: playing the old ones forever and a retune never reaches anybody.
#:   1 = original cue set · 2 = softened cues · 3 = musical notes/chords/tunes
CUE_VERSION = 3

# Pentatonic-ish happy scale for chimes (C major pentatonic, one octave up)
_SCALE_HZ = [523.25, 587.33, 659.25, 783.99, 880.00, 1046.50]

# Count-along ladder: C major pentatonic from C4, wrapping an octave up at the
# sixth step so ten objects climb a full "one ... ten" staircase.
_COUNT_HZ = [midi_to_hz(m) for m in COUNT_MIDIS]


# --------------------------------------------------------------- fast plumbing
# The musical layer renders ~20 s tunes, two orders of magnitude more samples
# than the old cue set. Per-sample Python loops for mixing and file writing
# were fine for a 0.3 s blip and are not fine here, so both are done with
# C-level bulk operations (slice + zip listcomp, array.tobytes).

# Quarter-precision sine wavetable. Indexing a list is roughly 3x faster than
# calling math.sin, and at 4096 points the quantisation sits near -70 dB —
# inaudible under a note's own harmonics.
_TABLE_BITS = 12
_TABLE_SIZE = 1 << _TABLE_BITS
_FRAC_BITS = 16
_PHASE_MASK = (_TABLE_SIZE << _FRAC_BITS) - 1
_SINE = [math.sin(_TAU * i / _TABLE_SIZE) for i in range(_TABLE_SIZE)]


def _write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array.array("h", (
        int(max(-1.0, min(1.0, s)) * 32767) for s in samples
    ))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())


class Mixer:
    """Accumulating buffer: drop layers in at arbitrary time offsets.

    Grows on demand, so callers never have to know the final length up front —
    which is what makes arranging a tune bar-by-bar practical.
    """

    def __init__(self) -> None:
        self.buf: list[float] = []

    def add(self, samples: list[float], at: float = 0.0, gain: float = 1.0) -> None:
        if not samples or gain == 0.0:
            return
        off = max(0, int(at * SAMPLE_RATE))
        end = off + len(samples)
        if end > len(self.buf):
            self.buf.extend([0.0] * (end - len(self.buf)))
        window = self.buf[off:end]
        if gain == 1.0:
            self.buf[off:end] = [a + b for a, b in zip(window, samples)]
        else:
            self.buf[off:end] = [a + b * gain for a, b in zip(window, samples)]

    def samples(self) -> list[float]:
        return list(self.buf)

    def render(self, peak: float = 0.9) -> list[float]:
        """Normalise to ``peak``. Silence stays silence."""
        if not self.buf:
            return []
        loudest = max(abs(s) for s in self.buf)
        if loudest <= 1e-9:
            return list(self.buf)
        scale = peak / loudest
        return [s * scale for s in self.buf]


def _lowpass(samples: list[float], alpha: float) -> list[float]:
    out, prev = [], 0.0
    for s in samples:
        prev += alpha * (s - prev)
        out.append(prev)
    return out


#: Early-reflection taps: (delay seconds, gain). Prime-ish spacing avoids the
#: metallic ring that evenly spaced taps produce.
_REVERB_TAPS = ((0.043, 0.30), (0.077, 0.21), (0.131, 0.14), (0.197, 0.08))


def reverb(samples: list[float], amount: float = 1.0) -> list[float]:
    """Put a note in a small room. Wet taps are lowpassed so the tail darkens
    as it decays, the way a real room absorbs treble first."""
    if amount <= 0.0:
        return samples
    wet = _lowpass(samples, 0.35)
    mix = Mixer()
    mix.add(samples)
    for delay, gain in _REVERB_TAPS:
        mix.add(wet, delay, gain * amount)
    return mix.samples()


# ------------------------------------------------------------------- voices

@dataclass(frozen=True)
class Voice:
    """An instrument.

    What separates an instrument from a beep is mostly ``harmonic_decay``:
    upper partials dying faster than the fundamental is the ear's main cue for
    "something was struck or plucked". A static harmonic stack with a linear
    fade — which is what this module used to do — always reads as electronic.
    """

    harmonics: tuple[float, ...] = (1.0, 0.40, 0.18, 0.08)
    decay: float = 3.0            # fundamental's decay rate, 1/s
    harmonic_decay: float = 0.9   # partial k decays at decay * (1 + k * this)
    attack: float = 0.008         # seconds; > 0 kills the click
    detune_cents: float = 4.0     # chorus layer; 0 disables
    detune_gain: float = 0.30
    rolloff_hz: float = 2600.0    # partials above this are progressively cut
    gain: float = 0.55
    reverb: float = 1.0


#: Music box / celesta — the letter keys. Bright, short, unmistakably "a note".
BELL = Voice(harmonics=(1.0, 0.50, 0.28, 0.14, 0.06), decay=3.6,
             harmonic_decay=1.1, attack=0.004, detune_cents=5.0,
             rolloff_hz=3000.0, gain=0.55)

#: Marimba — the counting ladder. Woodier and rounder than the bell so
#: "one, two, three" reads as a different instrument from the letters.
MARIMBA = Voice(harmonics=(1.0, 0.22, 0.34, 0.08), decay=6.0,
                harmonic_decay=1.4, attack=0.003, detune_cents=3.0,
                rolloff_hz=2200.0, gain=0.6)

#: Warm sustained pad — two-key chords and the mash swell. Slow attack turns a
#: keypress into a swell rather than a stab.
PAD = Voice(harmonics=(1.0, 0.45, 0.22, 0.12, 0.06), decay=1.1,
            harmonic_decay=0.55, attack=0.055, detune_cents=7.0,
            detune_gain=0.45, rolloff_hz=2000.0, gain=0.42)

#: Felt piano — the tune ostinato.
PIANO = Voice(harmonics=(1.0, 0.42, 0.20, 0.11, 0.05), decay=2.4,
              harmonic_decay=1.0, attack=0.005, detune_cents=3.5,
              rolloff_hz=2400.0, gain=0.5)

#: Plucked lead — the tune melody. Sings above the ostinato without piercing.
PLUCK = Voice(harmonics=(1.0, 0.55, 0.26, 0.13, 0.06), decay=2.2,
              harmonic_decay=0.85, attack=0.006, detune_cents=6.0,
              rolloff_hz=2800.0, gain=0.5)

#: Soft round bass. Almost pure sine — anything richer turns to mud on the
#: little speaker a Pi is likely wired to.
BASS = Voice(harmonics=(1.0, 0.18, 0.06), decay=1.8, harmonic_decay=1.2,
             attack=0.010, detune_cents=0.0, rolloff_hz=1200.0, gain=0.55,
             reverb=0.4)


def render_note(midi: float, dur: float, voice: Voice = BELL) -> list[float]:
    """One note of ``voice`` at ``midi``, ``dur`` seconds long (tail included).

    Partials are summed with an incremental phase accumulator and a
    multiplicative decay, so the inner loop is integer adds and a table lookup
    rather than a sin() and an exp() per sample per harmonic.
    """
    n = max(1, int(SAMPLE_RATE * dur))
    out = [0.0] * n
    f0 = midi_to_hz(midi)

    layers = [(f0, 1.0)]
    if voice.detune_cents:
        layers.append((f0 * 2.0 ** (voice.detune_cents / 1200.0), voice.detune_gain))

    nyquist_guard = SAMPLE_RATE * 0.45
    sine = _SINE
    for f_base, layer_gain in layers:
        for k, amp in enumerate(voice.harmonics):
            if amp <= 0.0:
                continue
            f = f_base * (k + 1)
            if f > nyquist_guard:
                break
            # High partials get progressively cut, so top-of-keyboard notes
            # sparkle instead of piercing.
            a = amp * layer_gain * voice.gain / (1.0 + (f / voice.rolloff_hz) ** 2)
            step = math.exp(-voice.decay * (1.0 + k * voice.harmonic_decay) / SAMPLE_RATE)
            dphase = int(f / SAMPLE_RATE * _TABLE_SIZE * (1 << _FRAC_BITS))
            phase = 0
            env = a
            for i in range(n):
                out[i] += env * sine[phase >> _FRAC_BITS]
                phase = (phase + dphase) & _PHASE_MASK
                env *= step

    attack_n = min(n, max(1, int(SAMPLE_RATE * voice.attack)))
    for i in range(attack_n):
        out[i] *= i / attack_n
    # Fade the truncation point so a shortened note doesn't click.
    fade_n = min(n, int(SAMPLE_RATE * 0.03))
    for j in range(fade_n):
        out[n - fade_n + j] *= 1.0 - j / fade_n

    return reverb(out, voice.reverb)


def render_chord(midis: tuple[int, ...], dur: float, voice: Voice = PAD,
                 spread: float = 0.018, peak: float = 0.82) -> list[float]:
    """A chord, strummed rather than stamped.

    ``spread`` staggers the notes by a few milliseconds each. Perfectly
    simultaneous onsets sound synthetic; a human hand never manages it.
    """
    mix = Mixer()
    for i, midi in enumerate(midis):
        mix.add(render_note(midi, dur, voice), i * spread)
    return mix.render(peak)


# ------------------------------------------------- legacy shaped-tone helpers
# Used by the character cues (animals, whoosh, boom ...). Left untouched: those
# are caricatures, and modelling them as instruments would spoil the joke.

def _env(i: int, n: int, attack: float = 0.01, release: float = 0.3) -> float:
    """Simple attack/release envelope, times as fractions of total length."""
    t = i / n
    if t < attack:
        return t / attack
    if t > 1.0 - release:
        return (1.0 - t) / release
    return 1.0


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
    """Sum the character-cue layers, attenuating only if they would clip.

    The 0.72 ceiling (rather than a full-scale 0.9) is deliberate headroom:
    these fire alongside a spoken letter name and a key note, and at 0.9 the
    animal calls buried both.
    """
    mix = Mixer()
    for layer in layers:
        mix.add(layer)
    peak = max(1.0, max((abs(s) for s in mix.buf), default=0.0))
    return [s / peak * 0.72 for s in mix.buf]


def _shift(samples: list[float], seconds: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * seconds) + samples


def _soften(samples: list[float]) -> list[float]:
    """Finishing pass for the character cues: a gentle one-pole ~3 kHz lowpass
    rounds off buzzy upper partials and any residual attack click, then peaks
    above 0.8 are normalised *down* — never up, so quiet cues stay quiet.

    Deliberately not applied to the musical cues: ``Voice`` already shapes
    brightness by pitch and adds a reverb tail, and a 3 kHz lowpass on top of
    that just makes the bells sound like they're underwater.
    """
    alpha = 0.46  # one-pole coefficient ≈ 3 kHz cutoff at 22.05 kHz
    out, prev = [], 0.0
    for s in samples:
        prev = prev + alpha * (s - prev)
        out.append(prev)
    peak = max((abs(s) for s in out), default=0.0)
    if peak > 0.8:
        out = [s / peak * 0.8 for s in out]
    return out


def cues_stale(dest: Path) -> bool:
    """True when ``dest`` lacks a complete cue set at the current CUE_VERSION."""
    version_file = dest / "cues.version"
    if not (dest / "pop.wav").is_file() or not version_file.is_file():
        return True
    try:
        return version_file.read_text(encoding="ascii").strip() != str(CUE_VERSION)
    except OSError:
        return True


# ------------------------------------------------------------ musical cues

def note_cue(midi: int) -> list[float]:
    """The cue fired by a single keypress: one bell note, ~1.1 s with tail."""
    mix = Mixer()
    mix.add(render_note(midi, 1.1, BELL))
    return mix.render(0.85)


def chord_cue(name: str) -> list[float]:
    """Two keys at once: a warm diatonic triad swelling underneath."""
    return render_chord(triad_midis(name), 1.6, PAD, spread=0.022, peak=0.78)


def mash_chord_cue() -> list[float]:
    """Chaos mode: a wide open add9 swell, six notes over two octaves."""
    return render_chord(MASH_CHORD, 2.2, PAD, spread=0.030, peak=0.80)


def count_note(i: int) -> list[float]:
    """Marimba note for the i-th counted object (0-based), climbing the
    pentatonic ladder so "one, two, three ..." rises in pitch. Index is
    clamped, so out-of-range callers get the top note rather than an error."""
    midi = COUNT_MIDIS[max(0, min(i, len(COUNT_MIDIS) - 1))]
    mix = Mixer()
    mix.add(render_note(midi, 0.75, MARIMBA))
    return mix.render(0.85)


def celebration() -> list[float]:
    """Milestone fanfare (~2 s): the I–V–vi–IV cadence under a rising bell run."""
    beat = 0.42
    mix = Mixer()
    for step, name in enumerate(("C", "G", "Am", "F")):
        for i, midi in enumerate(triad_midis(name, base=60)):
            mix.add(render_note(midi, beat * 1.9, PAD), step * beat + i * 0.02, 0.75)
    for step, midi in enumerate((72, 76, 79, 84, 88)):
        mix.add(render_note(midi, 0.6, BELL), 0.18 + step * 0.16, 0.9)
    mix.add(sparkle(), 1.05)
    return mix.render(0.9)


def chord_fanfare() -> list[float]:
    """Legacy three-note stab, kept as the fallback for a pre-upgrade cue set."""
    return chord_cue("C")


def chime(rng: random.Random) -> list[float]:
    """Legacy random chime, kept as the fallback when a note cue is missing."""
    midi = rng.choice([60, 62, 64, 67, 69, 72])
    return note_cue(midi)


# ------------------------------------------------------------ character cues

def pop() -> list[float]:
    """Short pitch-drop blip."""
    n = int(SAMPLE_RATE * 0.12)
    return [
        math.sin(_TAU * (750 - 450 * (i / n)) * (i / SAMPLE_RATE)) * _env(i, n, 0.08, 0.5) * 0.45
        for i in range(n)
    ]


def whoosh() -> list[float]:
    """Filtered-noise sweep (spacebar confetti)."""
    rng = random.Random(7)
    n = int(SAMPLE_RATE * 0.7)
    out, prev = [], 0.0
    for i in range(n):
        # One-pole lowpass over white noise, cutoff swept by envelope position
        alpha = 0.04 + 0.22 * (i / n)
        prev = prev + alpha * (rng.uniform(-1, 1) - prev)
        out.append(prev * _env(i, n, 0.2, 0.45) * 0.55)
    return out


def boom() -> list[float]:
    """Firework thump: low sine drop + noise tail."""
    rng = random.Random(3)
    n = int(SAMPLE_RATE * 0.9)
    out, prev = [], 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        f = 140 - 90 * (i / n)
        prev = prev + 0.10 * (rng.uniform(-1, 1) - prev)
        body = math.sin(_TAU * f * t) * 0.8 + prev * 0.3
        out.append(body * _env(i, n, 0.03, 0.6))
    return out


def sparkle() -> list[float]:
    """Tiny glissando up."""
    n = int(SAMPLE_RATE * 0.25)
    return [
        math.sin(_TAU * (600 + 550 * (i / n)) * (i / SAMPLE_RATE)) * _env(i, n, 0.10, 0.45) * 0.30
        for i in range(n)
    ]


def drum() -> list[float]:
    rng = random.Random(11)
    n = int(SAMPLE_RATE * 0.3)
    out, prev = [], 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        prev = prev + 0.25 * (rng.uniform(-1, 1) - prev)
        out.append((math.sin(_TAU * 90 * t) * 0.9 + prev * 0.22) * _env(i, n, 0.02, 0.7))
    return out


def boing() -> list[float]:
    """Frog hop."""
    n = int(SAMPLE_RATE * 0.35)
    return [
        math.sin(_TAU * (300 + 260 * math.sin(_TAU * 3.2 * (i / n))) * (i / SAMPLE_RATE))
        * _env(i, n, 0.06, 0.4) * 0.42
        for i in range(n)
    ]


# ------------------------------------------------- farm animals (cartoon, not real)
# Deliberate caricatures: a 2-year-old should recognise "moo!" instantly, so
# these lean on the *shape* of each sound (slide, bleat, grunt) rather than any
# attempt at realism.

# Nasal/reedy partial stacks — lots of upper harmonics at near-equal weight is
# what makes a tone read as "buzzy voice" instead of "flute".
_MOO_HARMONICS = (1.0, 0.50, 0.28, 0.14, 0.07)
_QUACK_HARMONICS = (1.0, 0.55, 0.32, 0.18, 0.10)
_OINK_HARMONICS = (1.0, 0.50, 0.28, 0.15, 0.08)


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
                   attack=0.05, release=0.6, gain=0.42)
    second = _glide(300, 250, 0.20, harmonics=_QUACK_HARMONICS,
                    attack=0.05, release=0.65, gain=0.42)
    return _mix(first, _shift(second, 0.28))


def oink() -> list[float]:
    """Pig: two quick low grunts, hard attack, pitch dipping away (~0.5 s)."""
    first = _glide(165, 120, 0.18, harmonics=_OINK_HARMONICS, curve=0.6,
                   attack=0.03, release=0.55, gain=0.5)
    second = _glide(150, 110, 0.20, harmonics=_OINK_HARMONICS, curve=0.6,
                    attack=0.03, release=0.60, gain=0.5)
    return _mix(first, _shift(second, 0.28))


def baa() -> list[float]:
    """Sheep: mid tone wobbled by a strong fast vibrato — the bleat (~0.8 s)."""
    return _mix(_glide(228, 205, 0.8, vibrato=0.06, vib_rate=11.0,
                       harmonics=(1.0, 0.45, 0.22, 0.10, 0.05),
                       attack=0.08, release=0.35, gain=0.5))


# ----------------------------------------------------------------- building

#: Cues that get the _soften() finishing pass — the character family only.
_SOFTENED = frozenset({
    "pop", "whoosh", "boom", "sparkle", "drum", "boing",
    "moo", "quack", "oink", "baa",
})


def build_cues(dest: Path, *, tunes: bool = True) -> list[Path]:
    """Generate all non-voice cues into ``dest``. Deterministic seed.

    ``tunes=False`` skips the four background tunes — they are by far the
    slowest part of a build, and tests that only care about cues can skip them.
    """
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
        "chord_mash": mash_chord_cue(),
    }
    for i in range(6):
        cues[f"chime{i}"] = chime(rng)
    for i in range(len(COUNT_MIDIS)):
        cues[f"count_{i}"] = count_note(i)
    for midi in NOTE_MIDIS:
        cues[f"note_{midi}"] = note_cue(midi)
    for name in CHORD_NAMES:
        cues[f"chord_{name}"] = chord_cue(name)
    for name, samples in cues.items():
        path = dest / f"{name}.wav"
        _write_wav(path, _soften(samples) if name in _SOFTENED else samples)
        written.append(path)

    if tunes:
        from .tunes import TUNES, clear_cache, render_tune
        for tune in TUNES:
            path = dest / f"tune_{tune.name}.wav"
            _write_wav(path, render_tune(tune))
            written.append(path)
        # The app itself may have run this on first launch; don't hold the
        # renderer's scratch space for the rest of the session.
        clear_cache()
        # Stamped only on a complete build: a tunes=False set really is stale.
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "cues.version").write_text(str(CUE_VERSION), encoding="ascii")
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
