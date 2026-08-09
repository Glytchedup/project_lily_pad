# Musical audio: notes, chords and instrumental tunes

Date: 2026-08-08

## Goal

Replace the ad-hoc beep/chime sound effects with a real musical system:

1. Every keypress plays a **musical note**, positioned like a piano across the keyboard.
2. Keys pressed together sound as a **chord**, never a clash.
3. Gentle **instrumental tunes** play in the background (attract/idle mode) and on
   milestone celebrations.
4. The whole thing has to be *pleasant to listen to* for hours, next to a 2-year-old.

## On the "OneRepublic melodies" request

The tunes are **original compositions in that anthemic pop-piano idiom** — pulsing
eighth-note piano ostinato, four-chord loops (I–V–vi–IV, vi–IV–I–V), soft stomp-clap
backbeat, singable diatonic melody with a rising hook. They are *not* transcriptions of
OneRepublic songs.

Reason: specific melodies are copyrighted, and this project's own rule (`CLAUDE.md`) is
"No copyrighted characters/assets anywhere — original visuals, generated audio". Chord
progressions, tempo and production style are not protectable; the actual tune is. So the
style is honoured and the melodies are ours.

## Why "pleasant" is a design constraint, not a wish

A toddler mashes keys. If keys map to arbitrary pitches, simultaneous presses produce
minor 2nds and tritones — the two most grating intervals there are. The fix is
structural rather than cosmetic:

**Every key maps to a note in the C major pentatonic scale (C D E G A).**

That scale contains no minor 2nd (1 semitone), no tritone (6) and no major 7th (11) —
in any inversion. So *any* subset of keys, pressed in any combination, is consonant by
construction. Ten fingers on ten random keys still sounds like a chord.

## Architecture

### New: `lilypad/audio/music.py` — theory core, no audio

Pure functions and tables. No pygame, no I/O.

- `midi_to_hz(midi)` — equal temperament, A4 = 440.
- `pentatonic(index, base)` — the C-pentatonic ladder; index wraps octaves.
- `fold_into_range(midi, lo, hi)` — octave-shift a note into the safe register.
- `NOTE_FOR_KEY: dict[str, int]` — key name → MIDI note, **derived from
  `lighting.keymap.KEY_MATRIX`** so the musical layout and the LED layout can never
  drift apart. Physical row sets the octave (lower row = lower pitch), column climbs the
  scale left→right. Everything is then folded into MIDI 48–88 (C3–E6, 131–1319 Hz) so
  nothing is ever muddy or shrill.
- Digits `1`–`0` override to the existing count ladder so "one, two, three…" still
  climbs in pitch.
- `CHORD_FOR_ROOT` — pitch-class → diatonic triad (C major, D minor, E minor, G major,
  A minor). `chord_for_keys(keys)` picks the lower of two pressed notes as the root and
  returns the triad name; that is always in key.
- `NOTE_MIDIS` / `CHORD_NAMES` — the exact set of WAVs the synth must build.

### Changed: `lilypad/audio/synth.py` — real instrument voices

The old `_tone` was a static harmonic stack with a linear envelope: the reason
everything sounded like a beep. Replaced with a `Voice` dataclass and a renderer that
models what actually makes an instrument sound like an instrument:

- **Per-harmonic exponential decay** — upper partials die faster than the fundamental,
  which is the single biggest cue for "struck/plucked" vs "electronic".
- **Gentle attack ramp** (5–20 ms) so there is no click.
- **Detuned second layer** (a few cents) for chorus warmth.
- **Brightness rolloff with pitch** — high notes drop their upper partials, so the top
  of the keyboard sparkles instead of piercing.
- **Short reverb tail** — a few lowpassed delayed taps, so notes sit in a room.

Voices: `BELL` (music box / celesta — letters), `MARIMBA` (counting), `PAD` (warm
sustained — chords), `PIANO` (ostinato), `PLUCK` (melody), `BASS`.

Also replaces the O(n·layers) mixing and per-sample WAV writing with a `Mixer` class
(slice + `zip` listcomp) and `array('h').tobytes()`. Needed: tunes are ~20 s each and
the old code path would take minutes on a Pi.

The existing non-musical cues (`whoosh`, `boom`, `drum`, `boing`, `moo`, `quack`,
`oink`, `baa`, `pop`, `sparkle`) are kept as-is — they are character, not music.
`celebration` is recomposed as a I–V–vi–IV cadence.

### New: `lilypad/audio/tunes.py` — the tune player's source material

A tiny declarative format:

```python
Tune(name, bpm, progression=("C","G","Am","F", ...), melody=((midi|None, beats), ...))
```

`render(tune)` arranges each bar into four layers — bass root, piano eighth-note
ostinato, soft stomp/clap backbeat, and the melody on a pluck voice — and mixes them.
Rendered notes are cached by `(voice, midi, duration)`, so a 20 s tune costs ~25 note
renders rather than ~140.

Four tunes ship: `sunrise` (I–V–vi–IV, 100 bpm), `counting` (vi–IV–I–V, 108 bpm),
`boats` (gentle, 88 bpm), `party` (upbeat, 118 bpm).

### Changed: `lilypad/audio/engine.py`

- `_play_note(key)` on every fresh-press action kind (letter, space, arrow, enter,
  special, sparkle). Numbers keep the count ladder — it is already the right pitch.
  Synthetic kinds (`chord`, `mash_*`, `hold_*`) do not re-trigger a note.
- Letters now play the spoken letter name **and** the note (layered), instead of
  name-or-chime.
- `chord` action → the diatonic triad for those two keys, on the warm pad voice.
- `mash_start` → a big add9 swell rather than the same three-note stab.
- `set_idle(bool)` drives background tunes through `pygame.mixer.music` (a separate
  stream from the 16 Sound channels, so cues never steal the music's channel).
  Round-robins the four tunes, fades in over 1.2 s, fades out over 0.7 s on the first
  keypress.
- Per-cue gain table so notes sit *under* the spoken voice instead of masking it.

### Changed: `lilypad/config.py`

New `[music]` section:

| key | default | meaning |
|---|---|---|
| `key_notes` | `true` | keys play musical notes |
| `tunes` | `"idle"` | `idle` \| `always` \| `off` |
| `tune_volume` | `0.45` | background music level, independent of cue volume |

Invalid `tunes` value raises at load, like `lighting.backend` does.

### Changed: `lilypad/__main__.py`

One line in the frame loop: `audio.set_idle(engine.attract is not None)`.

## Failure behaviour

Unchanged contract: audio degrades to silence, never crashes. Missing note WAV → falls
back to the old chime; missing tune → no music; mixer unavailable → everything is a
no-op. `mute = true` short-circuits before any of it.

## Testing

New `tests/test_music.py`:

- every key in `KEY_MATRIX` has a note, and every note is in 48–88;
- **consonance property**: no two mapped notes are 1, 6 or 11 semitones apart mod 12
  (this is the guarantee the whole design rests on);
- home row and bottom row climb left→right;
- digits match the count ladder;
- `chord_for_keys` always returns a diatonic triad, and is order-independent;
- tune bars sum to 4 beats, melodies are diatonic and within a singable range;
- rendered tunes are the expected length and never clip.

Extended `tests/test_synth.py`: note/chord WAVs exist, are valid, pitch rises with MIDI
number, notes decay (energy in the last quarter < first quarter).

Extended `tests/test_config.py`: `[music]` parsing, defaults, invalid `tunes` rejected.
