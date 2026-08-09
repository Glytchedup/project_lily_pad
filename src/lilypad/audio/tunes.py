"""Background instrumental tunes — original compositions, rendered offline.

Style is anthemic pop-piano: a pulsing eighth-note ostinato, a four-chord loop,
a soft stomp-clap backbeat and a singable diatonic melody that climbs to a hook.
That idiom — the OneRepublic / stadium-pop sound — is what the tunes are aiming
at, but the **melodies here are original**. Chord progressions, tempo and
production style are not protectable; specific melodies are, and this project's
rule is no copyrighted assets anywhere.

Everything is in C major so the tunes and the key notes (C major pentatonic,
see :mod:`lilypad.audio.music`) share a key: a toddler hammering keys over a
playing tune is playing *in* the tune, not against it.

Tunes are rendered at build time into ~20 s seamlessly looping WAVs and played
back through ``pygame.mixer.music``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from .music import TRIADS, triad_midis
from .synth import (
    BASS, PIANO, PLUCK, SAMPLE_RATE, Mixer, Voice, render_note, reverb,
)

BEATS_PER_BAR = 4

#: Eighth-note ostinato patterns, as indices into the bar's four chord tones
#: (root, third, fifth, root+octave). Alternating two patterns keeps the pulse
#: driving without it turning into a metronome.
_OSTINATO_A = (0, 1, 2, 3, 2, 1, 2, 1)
_OSTINATO_B = (0, 2, 1, 3, 0, 2, 3, 2)


@dataclass(frozen=True)
class Tune:
    name: str
    bpm: float
    #: One chord name per bar; names index :data:`lilypad.audio.music.TRIADS`.
    progression: tuple[str, ...]
    #: ``(midi or None for a rest, beats)`` walked start to finish. Total beats
    #: must equal ``len(progression) * BEATS_PER_BAR``.
    melody: tuple[tuple[int | None, float], ...]
    #: 0 = no drums (lullaby), 1 = full stomp-clap.
    percussion: float = 0.6
    #: Melody level relative to the ostinato.
    melody_gain: float = 0.95


# --------------------------------------------------------------- the tunes

SUNRISE = Tune(
    name="sunrise",
    bpm=100,
    # I–V–vi–IV, the four-chord backbone of every stadium chorus.
    progression=("C", "G", "Am", "F", "C", "G", "F", "F"),
    melody=(
        (67, 1), (69, 0.5), (67, 0.5), (64, 2),
        (74, 1), (71, 0.5), (74, 0.5), (67, 2),
        (76, 1), (74, 0.5), (72, 0.5), (69, 2),
        (72, 1.5), (69, 0.5), (65, 2),
        (67, 1), (69, 0.5), (67, 0.5), (64, 2),
        (74, 1), (71, 0.5), (67, 0.5), (74, 2),
        (72, 1), (69, 1), (65, 1), (69, 1),
        (67, 2), (None, 2),
    ),
    percussion=0.55,
)

COUNTING = Tune(
    name="counting",
    bpm=108,
    # vi–IV–I–V: the same four chords started on the minor, so it reads as
    # driving rather than sunny.
    progression=("Am", "F", "C", "G", "Am", "F", "C", "G"),
    melody=(
        (69, 0.5), (72, 0.5), (76, 1), (74, 1), (72, 1),
        (69, 1), (65, 0.5), (69, 0.5), (72, 2),
        (67, 0.5), (64, 0.5), (67, 1), (72, 2),
        (74, 1), (71, 1), (67, 2),
        (69, 0.5), (72, 0.5), (76, 1), (77, 1), (76, 1),
        (72, 2), (69, 2),
        (76, 1), (74, 1), (72, 1), (67, 1),
        (71, 2), (74, 2),
    ),
    percussion=0.85,
)

BOATS = Tune(
    name="boats",
    bpm=88,
    # I–iii–vi–IV: the third chord swaps V for iii, which is what makes this
    # one drift instead of push. Wind-down music.
    progression=("C", "Em", "Am", "F", "C", "G", "F", "C"),
    melody=(
        (64, 1), (67, 1), (72, 2),
        (71, 1), (67, 1), (64, 2),
        (69, 1), (72, 1), (76, 2),
        (74, 1), (72, 1), (69, 2),
        (67, 1), (64, 1), (67, 2),
        (74, 1), (71, 1), (74, 2),
        (72, 1.5), (69, 0.5), (65, 2),
        (64, 2), (60, 2),
    ),
    percussion=0.0,
    melody_gain=0.85,
)

PARTY = Tune(
    name="party",
    bpm=118,
    progression=("F", "C", "G", "Am", "F", "C", "G", "G"),
    melody=(
        (65, 0.5), (69, 0.5), (72, 1), (69, 1), (65, 1),
        (64, 0.5), (67, 0.5), (72, 1), (67, 2),
        (74, 0.5), (71, 0.5), (67, 1), (71, 1), (74, 1),
        (72, 1), (69, 1), (76, 2),
        (65, 0.5), (69, 0.5), (72, 1), (77, 2),
        (76, 1), (72, 1), (67, 2),
        (74, 0.5), (71, 0.5), (74, 1), (79, 2),
        (74, 2), (None, 2),
    ),
    percussion=1.0,
)

TUNES: tuple[Tune, ...] = (SUNRISE, COUNTING, BOATS, PARTY)
TUNE_NAMES: tuple[str, ...] = tuple(t.name for t in TUNES)


# ------------------------------------------------------------- percussion

def _kick(gain: float) -> list[float]:
    """Soft foot-stomp: a fast pitch drop with no click on the attack."""
    n = int(SAMPLE_RATE * 0.20)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / n
        f = 92.0 - 46.0 * t ** 0.5
        phase += math.tau * f / SAMPLE_RATE
        env = min(1.0, i / 60) * math.exp(-5.5 * t)
        out.append(math.sin(phase) * env * gain)
    return out


def _clap(gain: float) -> list[float]:
    """Soft handclap: a short noise burst with the low end taken out."""
    rng = random.Random(101)
    n = int(SAMPLE_RATE * 0.16)
    low = 0.0
    out = []
    for i in range(n):
        t = i / n
        raw = rng.uniform(-1.0, 1.0)
        low += 0.22 * (raw - low)
        env = min(1.0, i / 40) * math.exp(-11.0 * t)
        out.append((raw - low) * env * gain * 0.5)
    return out


# ---------------------------------------------------------------- rendering

#: Rendered notes are cached across every tune in a build — the four tunes
#: share a key and a chord vocabulary, so most notes are rendered once and
#: placed a few dozen times.
_NOTE_CACHE: dict[tuple[int, int, int], list[float]] = {}
_VOICES: tuple[Voice, ...] = (PIANO, PLUCK, BASS)
#: Notes are rendered dry and the whole mix gets one reverb pass at the end:
#: cheaper than per-note reverb, and 140 overlapping tails would be mud.
_DRY: tuple[Voice, ...] = tuple(replace(v, reverb=0.0) for v in _VOICES)


def _note(voice_index: int, midi: int, dur: float) -> list[float]:
    key = (voice_index, midi, round(dur * 200))
    cached = _NOTE_CACHE.get(key)
    if cached is None:
        cached = render_note(midi, dur, _DRY[voice_index])
        _NOTE_CACHE[key] = cached
    return cached


_PIANO, _PLUCK, _BASS = 0, 1, 2


def render_tune(tune: Tune) -> list[float]:
    """Arrange and render one tune into a seamless loop."""
    beat = 60.0 / tune.bpm
    bars = len(tune.progression)
    mix = Mixer()

    for bar, chord_name in enumerate(tune.progression):
        bar_t = bar * BEATS_PER_BAR * beat
        root_pc = TRIADS[chord_name][0]

        # Bass: root on beats 1 and 3, an octave below the ostinato.
        bass_midi = 36 + root_pc
        for offset in (0.0, 2.0):
            mix.add(_note(_BASS, bass_midi, beat * 2.1), bar_t + offset * beat, 0.85)

        # Piano ostinato: eighth notes over the bar's chord tones.
        tones = triad_midis(chord_name, base=48)
        tones = (*tones, tones[0] + 12)
        pattern = _OSTINATO_A if bar % 2 == 0 else _OSTINATO_B
        for step, tone_index in enumerate(pattern):
            mix.add(_note(_PIANO, tones[tone_index], beat * 0.8),
                    bar_t + step * 0.5 * beat,
                    0.55 if step % 2 else 0.72)   # accent the downbeats

        # Backbeat: stomp on 1 and 3, clap on 2 and 4.
        if tune.percussion > 0.0:
            for offset in (0.0, 2.0):
                mix.add(_kick(0.55 * tune.percussion), bar_t + offset * beat)
            for offset in (1.0, 3.0):
                mix.add(_clap(0.40 * tune.percussion), bar_t + offset * beat)

    # Melody, walked start to finish over the whole loop.
    at = 0.0
    for midi, beats in tune.melody:
        if midi is not None:
            # Ring slightly past the written length so the line sings legato.
            dur = min(2.4, beats * beat * 1.25)
            mix.add(_note(_PLUCK, midi, dur), at, tune.melody_gain)
        at += beats * beat

    buf = reverb(mix.samples(), 0.8)

    # Wrap the reverb tail (and any note still ringing) back over the top of
    # the loop, so playing it on repeat has no seam and no click.
    total_n = int(bars * BEATS_PER_BAR * beat * SAMPLE_RATE)
    if len(buf) > total_n:
        tail = buf[total_n:total_n * 2]
        head = buf[:total_n]
        head[:len(tail)] = [a + b for a, b in zip(head[:len(tail)], tail)]
        buf = head
    elif len(buf) < total_n:
        buf.extend([0.0] * (total_n - len(buf)))

    loudest = max((abs(s) for s in buf), default=0.0)
    if loudest > 1e-9:
        scale = 0.86 / loudest
        buf = [s * scale for s in buf]
    return buf


def clear_cache() -> None:
    """Drop the rendered-note cache (~19 MB after a full build).

    Worth calling once the tunes are on disk: on first launch the app itself
    generates them, and a 2 GB Pi shouldn't carry the scratch space for the
    rest of the session.
    """
    _NOTE_CACHE.clear()


def melody_beats(tune: Tune) -> float:
    return sum(beats for _, beats in tune.melody)
