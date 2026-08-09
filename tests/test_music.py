"""The musical layer: key→note mapping, chords, and the tunes.

The centrepiece is ``test_no_two_keys_can_clash`` — the whole "pleasant to
listen to" claim rests on that property, so it is asserted directly rather
than left to taste.
"""

import itertools

import pytest

from lilypad.audio import music
from lilypad.audio.music import (
    COUNT_MIDIS, HIGH_MIDI, LOW_MIDI, NOTE_FOR_KEY, NOTE_MIDIS, PENTATONIC,
    TRIADS, chord_for_keys, chord_for_notes, fold_into_range, midi_to_hz,
    note_for_key, pentatonic, triad_midis,
)
from lilypad.audio.synth import SAMPLE_RATE
from lilypad.audio.tunes import BEATS_PER_BAR, TUNES, TUNE_NAMES, render_tune
from lilypad.lighting.keymap import KEY_MATRIX


# ------------------------------------------------------------- pitch basics

def test_midi_to_hz_hits_the_reference_pitches():
    assert midi_to_hz(69) == pytest.approx(440.0)
    assert midi_to_hz(60) == pytest.approx(261.63, abs=0.01)   # middle C
    assert midi_to_hz(81) == pytest.approx(880.0)


def test_pentatonic_climbs_and_wraps_an_octave_every_five_steps():
    assert [pentatonic(i, 60) for i in range(6)] == [60, 62, 64, 67, 69, 72]
    assert pentatonic(-1, 60) == 57            # A below the root
    assert pentatonic(10, 60) == 84            # two octaves up


def test_fold_into_range_preserves_pitch_class():
    for midi in range(0, 128):
        folded = fold_into_range(midi)
        assert LOW_MIDI <= folded <= HIGH_MIDI
        assert folded % 12 == midi % 12


def test_fold_into_range_rejects_a_range_it_could_loop_in():
    with pytest.raises(ValueError):
        fold_into_range(60, 60, 65)


# ----------------------------------------------------------- the key layout

def test_every_key_on_the_board_has_a_note_in_the_safe_register():
    for name in KEY_MATRIX:
        assert name in NOTE_FOR_KEY, name
        assert LOW_MIDI <= NOTE_FOR_KEY[name] <= HIGH_MIDI, name


def test_unknown_keys_still_get_a_note():
    # Total mapping: the mapper turns every key into an action, so the audio
    # engine must have a pitch for anything that reaches it.
    assert LOW_MIDI <= note_for_key("NOSUCHKEY") <= HIGH_MIDI
    assert note_for_key("a") == note_for_key("A")      # case-insensitive


def test_the_fallback_note_is_one_the_synth_actually_builds():
    # NOTE_MIDIS drives which note_*.wav files exist. If the fallback pitch
    # weren't among them, exotic keys would silently have no cue on disk.
    assert music.DEFAULT_MIDI in NOTE_MIDIS


def test_no_two_keys_can_clash():
    """Any combination of keys, pressed together, is consonant.

    Every mapped note is a C-major-pentatonic pitch class, and that scale
    contains no minor 2nd (1 semitone), tritone (6) or major 7th (11) in any
    inversion. This is the property that lets a toddler lie on the keyboard
    without producing a horror-film chord.
    """
    dissonant = {1, 6, 11}
    classes = {m % 12 for m in NOTE_MIDIS}
    assert classes <= set(PENTATONIC)
    for a, b in itertools.combinations_with_replacement(sorted(classes), 2):
        assert (b - a) % 12 not in dissonant
        assert (a - b) % 12 not in dissonant


def test_letter_rows_climb_from_left_to_right():
    # Reaching right reaches up in pitch — the mapping a child finds without
    # being told. (The top row is long enough to wrap an octave, like a toy
    # piano with too few keys, so only its first stretch is checked.)
    for row in ("ZXCVBNM", "ASDFGHJKL", "QWERTY"):
        notes = [note_for_key(k) for k in row]
        assert notes == sorted(notes), row
        assert len(set(notes)) == len(notes), row


def test_higher_keyboard_rows_sound_higher():
    assert note_for_key("Z") < note_for_key("A") < note_for_key("Q")
    assert note_for_key("M") < note_for_key("J")


def test_digits_follow_the_counting_ladder():
    digits = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
    assert [note_for_key(d) for d in digits] == list(COUNT_MIDIS)
    assert [note_for_key(f"KP{d}") for d in digits] == list(COUNT_MIDIS)
    # "0" means ten, so it must be the top of the ladder, not the bottom.
    assert note_for_key("0") == max(COUNT_MIDIS)


def test_count_ladder_rises_step_by_step():
    assert list(COUNT_MIDIS) == sorted(COUNT_MIDIS)
    assert len(set(COUNT_MIDIS)) == 10


# ---------------------------------------------------------------- chords

def test_every_triad_is_diatonic_to_c_major():
    c_major = {0, 2, 4, 5, 7, 9, 11}
    for name in TRIADS:
        for midi in triad_midis(name):
            assert midi % 12 in c_major, f"{name} has a note outside C major"


def test_triads_are_major_or_minor_and_correctly_rooted():
    assert triad_midis("C") == (48, 52, 55)      # C  major: root, +4, +7
    assert triad_midis("Am") == (57, 60, 64)     # A  minor: root, +3, +7
    assert triad_midis("F", base=60) == (65, 69, 72)


def test_unknown_chord_name_is_an_error_not_a_silent_wrong_chord():
    with pytest.raises(KeyError):
        triad_midis("Bdim")


def test_chord_follows_the_lower_key_and_ignores_press_order():
    for a, b in itertools.combinations("ASDFGHJKLQWERTZXCVBNM", 2):
        assert chord_for_keys((a, b)) == chord_for_keys((b, a))
        assert chord_for_keys((a, b)) in music.CHORD_NAMES


def test_chord_for_notes_roots_on_the_lowest_note():
    assert chord_for_notes((60, 67)) == "C"      # C in the bass
    assert chord_for_notes((69, 72)) == "Am"     # A in the bass
    assert chord_for_notes(()) == "C"            # degenerate, still in key


def test_mash_chord_is_open_and_consonant():
    dissonant = {1, 6, 11}
    for a, b in itertools.combinations(music.MASH_CHORD, 2):
        assert (b - a) % 12 not in dissonant
    assert 4 not in {m % 12 for m in music.MASH_CHORD}, "add9 has no third"


# ----------------------------------------------------------------- tunes

def test_tune_names_are_unique():
    assert len(set(TUNE_NAMES)) == len(TUNE_NAMES)


@pytest.mark.parametrize("tune", TUNES, ids=lambda t: t.name)
def test_melody_length_matches_the_progression(tune):
    written = sum(beats for _, beats in tune.melody)
    assert written == pytest.approx(len(tune.progression) * BEATS_PER_BAR)


@pytest.mark.parametrize("tune", TUNES, ids=lambda t: t.name)
def test_tune_chords_are_known_and_melody_is_diatonic_and_singable(tune):
    c_major = {0, 2, 4, 5, 7, 9, 11}
    for name in tune.progression:
        assert name in TRIADS, name
    for midi, beats in tune.melody:
        assert beats > 0
        if midi is None:
            continue
        assert midi % 12 in c_major, midi
        # A comfortable lead register: middle C up to a high G.
        assert 60 <= midi <= 79, midi


@pytest.mark.parametrize("tune", TUNES, ids=lambda t: t.name)
def test_tune_progressions_are_four_bar_loops(tune):
    assert len(tune.progression) % 4 == 0
    assert 0.0 <= tune.percussion <= 1.0


@pytest.mark.parametrize("tune", TUNES, ids=lambda t: t.name)
def test_rendered_tune_is_exactly_its_written_length(tune):
    expected = len(tune.progression) * BEATS_PER_BAR * (60.0 / tune.bpm)
    rendered = len(render_tune(tune)) / SAMPLE_RATE
    assert rendered == pytest.approx(expected, abs=0.001)


@pytest.mark.parametrize("tune", TUNES, ids=lambda t: t.name)
def test_rendered_tune_loops_without_a_click(tune):
    """The end has to join the start silently — this plays on repeat for as
    long as the room is empty, so a click would become a metronome."""
    buf = render_tune(tune)
    steps = sorted(abs(a - b) for a, b in zip(buf, buf[1:]))
    typical = steps[int(len(steps) * 0.99)]
    seam = abs(buf[0] - buf[-1])
    assert seam < typical, f"loop seam {seam:.4f} vs typical step {typical:.4f}"


@pytest.mark.parametrize("tune", TUNES, ids=lambda t: t.name)
def test_rendered_tune_is_audible_and_never_clips(tune):
    buf = render_tune(tune)
    assert all(-1.0 <= s <= 1.0 for s in buf)
    assert max(abs(s) for s in buf) > 0.5
    rms = (sum(s * s for s in buf) / len(buf)) ** 0.5
    # Background music, not a wall of sound: loud enough to hear across a
    # room, quiet enough to sit under a child banging on the keyboard.
    assert 0.08 < rms < 0.30
