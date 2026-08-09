"""Musical theory core: which note does a key play, and what chord do two make.

Pure data and pure functions — no audio, no pygame, no I/O. The synth turns
these numbers into WAVs; the engine looks them up at keypress time.

The one idea the whole design rests on:

    **Every key maps to a note of the C major pentatonic scale (C D E G A).**

That scale contains no minor 2nd (1 semitone), no tritone (6) and no major 7th
(11) in any inversion — the three intervals that make a cluster sound *wrong*.
So a toddler laying both palms across the keyboard produces a chord, not a
crash. Consonance is structural here, not something we filter for afterwards.
"""

from __future__ import annotations

from ..lighting.keymap import KEY_MATRIX

# ------------------------------------------------------------------ pitch math

A4_MIDI = 69
A4_HZ = 440.0

#: Scale degrees of the major pentatonic, in semitones above the root.
PENTATONIC = (0, 2, 4, 7, 9)

#: Playable register for key notes: C3 (131 Hz) to E6 (1319 Hz). Low enough to
#: have body on a small speaker, capped well below the range that makes a
#: 2-year-old at arm's length flinch.
LOW_MIDI = 48
HIGH_MIDI = 88


def midi_to_hz(midi: float) -> float:
    """Equal temperament, A4 = 440 Hz."""
    return A4_HZ * 2.0 ** ((midi - A4_MIDI) / 12.0)


def pentatonic(index: int, base: int = 60) -> int:
    """The ``index``-th note of the pentatonic ladder rooted at ``base``.

    Wraps up an octave every 5 steps, so index keeps climbing forever:
    ``pentatonic(0..5, 60)`` is C4 D4 E4 G4 A4 C5. Negative indices descend.
    """
    octave, degree = divmod(index, len(PENTATONIC))
    return base + 12 * octave + PENTATONIC[degree]


def fold_into_range(midi: int, lo: int = LOW_MIDI, hi: int = HIGH_MIDI) -> int:
    """Octave-shift ``midi`` until it sits in [lo, hi].

    Octave shifts preserve pitch class, so a folded pentatonic note is still
    pentatonic — the consonance guarantee survives the fold intact.
    """
    if hi - lo < 12:
        raise ValueError("range must span at least an octave to fold into")
    while midi < lo:
        midi += 12
    while midi > hi:
        midi -= 12
    return midi


# --------------------------------------------------------------- key → note

#: Octave root per physical matrix row. Row 0 is the Esc/function row at the
#: top of the board and row 5 is the space bar row, so the bases descend with
#: the row index: reaching *up* the keyboard reaches *up* in pitch, which is
#: the mapping a child discovers without being told. Bases must be C's (a
#: multiple of 12) or the ladder would no longer be C pentatonic.
_ROW_BASE = {0: 96, 1: 84, 2: 72, 3: 60, 4: 48, 5: 36}

#: Digits keep their own ladder so "one, two, three ..." climbs step by step,
#: matching the counting chimes the number keys already trigger.
_DIGIT_ORDER = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0")

COUNT_MIDIS: tuple[int, ...] = tuple(pentatonic(i, 60) for i in range(10))


def _build_note_map() -> dict[str, int]:
    """Derive the note layout from the LED matrix.

    Reusing ``KEY_MATRIX`` rather than writing a second layout table means the
    musical and lighting layouts cannot drift apart: a key added for one is
    automatically placed for the other.
    """
    notes: dict[str, int] = {}
    for name, (row, col) in KEY_MATRIX.items():
        base = _ROW_BASE.get(row, 60)
        notes[name] = fold_into_range(pentatonic(col, base))
    for i, digit in enumerate(_DIGIT_ORDER):
        notes[digit] = fold_into_range(COUNT_MIDIS[i])
        notes[f"KP{digit}"] = notes[digit]
    return notes


NOTE_FOR_KEY: dict[str, int] = _build_note_map()

#: Middle-of-the-board fallback for a key the matrix does not place.
DEFAULT_MIDI = fold_into_range(pentatonic(2, 60))

#: Every distinct pitch the synth has to render a note WAV for.
NOTE_MIDIS: tuple[int, ...] = tuple(sorted(set(NOTE_FOR_KEY.values())))


def note_for_key(name: str) -> int:
    """MIDI note for a key name; unplaced keys get a safe middle note."""
    return NOTE_FOR_KEY.get(name.upper(), DEFAULT_MIDI)


# ------------------------------------------------------------------- chords

#: The six diatonic triads of C major, as (root pitch class, semitone offsets).
#: F major has no pentatonic root, so no key can *summon* it — but it is the
#: "IV" that every anthem leans on, so the tunes and the celebration cadence
#: still use it.
TRIADS: dict[str, tuple[int, tuple[int, ...]]] = {
    "C":  (0, (0, 4, 7)),
    "Dm": (2, (0, 3, 7)),
    "Em": (4, (0, 3, 7)),
    "F":  (5, (0, 4, 7)),
    "G":  (7, (0, 4, 7)),
    "Am": (9, (0, 3, 7)),
}

#: Pentatonic pitch class → the triad a key note rooted there summons. Every
#: one is native to C major, so a two-key chord is always in key.
_TRIAD_FOR_PITCH_CLASS: dict[int, str] = {
    0: "C", 2: "Dm", 4: "Em", 7: "G", 9: "Am",
}

#: Chords the synth builds a cue for — only the ones a keypress can reach.
CHORD_NAMES: tuple[str, ...] = tuple(_TRIAD_FOR_PITCH_CLASS.values())

#: Root octave for chords: C3. Roots land in 48–57 and the highest triad note
#: reaches 64 (E4), so the chord sits as a bed *under* the key notes rather
#: than competing with them, and never rumbles on a small speaker.
CHORD_ROOT_BASE = 48

#: The mash-storm swell: an open Cadd9 (no third) spread over two octaves.
#: Leaving the third out keeps chaos mode shimmering and unresolved instead of
#: landing on a plain major chord — and it still cannot sound dissonant.
MASH_CHORD: tuple[int, ...] = (48, 55, 60, 62, 67, 74)


def triad_midis(name: str, base: int = CHORD_ROOT_BASE) -> tuple[int, ...]:
    """The three MIDI notes of a named diatonic triad, rooted from ``base``.
    Raises KeyError for a name that is not one of ``TRIADS``."""
    pitch_class, intervals = TRIADS[name]
    root = base + pitch_class
    return tuple(root + i for i in intervals)


def chord_for_notes(midis: tuple[int, ...]) -> str:
    """Name the diatonic triad that best fits the given key notes.

    Uses the lowest note as the root — the bass note is what the ear hears as
    "the chord" — so the harmony follows the lower hand. Every key note is a
    pentatonic pitch class, so a triad always exists.
    """
    if not midis:
        return "C"
    return _TRIAD_FOR_PITCH_CLASS.get(min(midis) % 12, "C")


def chord_for_keys(keys: tuple[str, ...]) -> str:
    """Name the triad for a set of simultaneously pressed key names."""
    return chord_for_notes(tuple(note_for_key(k) for k in keys))
