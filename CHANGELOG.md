# Changelog

All notable changes to Project Lily Pad (Toddler Keyboard Playground) are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is
pre-1.0, so everything lands under Unreleased until first on-device verification.

## [Unreleased]

### Added (musical audio — keys are notes, chords, and background tunes)
- `audio/music.py`: the theory core. Every key maps to a note of the **C major
  pentatonic** scale, derived from `lighting/keymap.py`'s LED matrix so the
  musical and lighting layouts cannot drift apart — lower physical rows are
  lower notes, left to right climbs the scale, everything folded into MIDI
  48–88 (C3–E6). That scale contains no minor 2nd, tritone or major 7th in any
  inversion, so **any** combination of keys pressed together is consonant by
  construction; `tests/test_music.py::test_no_two_keys_can_clash` asserts it
  directly. Also: diatonic triad tables and `chord_for_keys()`.
- `audio/tunes.py`: four original instrumental loops (`sunrise`, `counting`,
  `boats`, `party`) in an anthemic pop-piano style — four-chord loops, an
  eighth-note piano ostinato, soft stomp-clap backbeat and a singable melody.
  Rendered at build time into seamless ~20 s WAVs (the reverb tail is wrapped
  back over the loop start, so repeats have no click). All in C major, the same
  key as the keys, so playing over a tune lands in tune.
- Background music: `AudioEngine.set_idle()`, driven from the frame loop by
  `engine.attract is not None`. Tunes fade in with the attract animation and
  fade straight out on the next keypress, round-robining through the four.
  Played via `pygame.mixer.music` so cues never steal the music's channel.
- `[music]` config section: `key_notes` (default `true`), `tunes`
  (`idle` | `always` | `off`, default `idle`), `tune_volume` (default `0.45`,
  independent of `audio.volume`). An invalid `tunes` value raises at load.

### Changed (audio)
- `audio/synth.py` grew a real instrument model: a `Voice` dataclass with
  **per-harmonic exponential decay** (upper partials die faster — the ear's main
  cue for "struck/plucked" rather than "beep"), a gentle attack ramp, a detuned
  chorus layer, pitch-dependent brightness rolloff so the top of the keyboard
  sparkles instead of piercing, and a short lowpassed reverb tail. Voices:
  `BELL` (letters), `MARIMBA` (counting), `PAD` (chords), `PIANO`/`PLUCK`/`BASS`
  (tunes).
- Keypresses now sound their note: letters play the note **and** the spoken
  letter name (previously name-*or*-chime), with a per-family gain table
  keeping the note under the voice. Space/enter/arrows/specials/sparkles layer
  a note under their character cue. Numbers keep the counting ladder, now a
  marimba.
- Two-key chords play the diatonic triad their lower note roots (was a single
  static three-note stab); mash storms get a wide open add9 swell.
  `celebration` is recomposed as a I–V–vi–IV cadence.
- Synth plumbing rewritten for the ~100× more samples the tunes need: a `Mixer`
  class (slice + `zip` listcomp) replaces the O(n·layers) indexed loop, WAV
  writing goes through `array('h').tobytes()`, and oscillators use a fixed-point
  wavetable. A full cue build (56 files, 6 MB, including four tunes) takes ~6 s.
- `build_cues(dest, tunes=False)` skips the slow tune render for tests.
- Character cues (whoosh, boom, drum, boing, animal calls) are unchanged —
  they are caricatures, not music.

### Added (visual WOW upgrade — implements all 10 VISUAL_REVIEW.md recommendations)
- Pond scene (`effects/scenery.py`): pre-rendered night/dusk/aurora gradient
  skies with baked moon, stars, and drifting lily pads; slow crossfade between
  variants every 5 minutes; twinkling star overlay.
- Additive glow rendering (`effects/glow.py`): cached radial-gradient sprites
  blitted with `BLEND_ADD` replace flat circles in `ParticleSystem.draw` —
  overlapping particles now sum toward white.
- Motion trails: the engine clears each frame with a translucent scene veil
  (plus a subtract/max-snap pass that defeats pygame's integer-blend ghosting)
  so lights streak and fade; `effects.trails` config toggle.
- Glossy interactive bubbles (`effects/bubbles.py`): letter B blows a flotilla
  of specular-highlight bubbles that Pip pops on contact (droplet spray);
  attract mode now uses the same glossy sprites.
- Farm-animal peekaboo cast (`effects/animals.py`): C/D/P/S slide a
  primitive-drawn cow/duck/pig/sheep up from the bottom edge — blink, wiggle,
  and a procedural moo/quack/oink/baa — then slide away.
- Fireworks upgrade: glitter trails on climbing rockets, white crackle
  micro-pops partway through each burst, and 50% shaped explosions that draw a
  heart, star, or smiley in the sky.
- Characterful letters: thick contrasting outline, 1-in-4 rainbow-gradient
  fill, gentle bob/sway wobble, and googly eyes during the hold phase.
- Count-along with real things: digits now count ducks/apples/frogs/flowers/
  stars (one kind per press), with a left-to-right mini-burst fanfare and an
  ascending pentatonic count note per press.
- Key-hold rainbow comets (`effects/comet.py`): any key held ~0.4 s becomes a
  wandering hue-cycling comet (max 4) that grows while held and bursts on
  release; `KeyMapper.poll_holds` drives hold_start/hold_end actions.
- Milestone mega-celebrations: every 50th press (configurable via
  `effects.milestone_every`) fires fireworks + confetti + balloons + a timed
  rainbow border pulse + frog joy-hops + a celebration fanfare; completing all
  26 letters adds a heart-shaped burst.
- Frog splash-down ripples (water rings at his feet on real impacts).
- Audio: new procedural cues (moo/quack/oink/baa, count_0..9 pentatonic
  ladder, celebration fanfare) and `AudioEngine.on_celebration()`.
- Tests: 171 (was 52) — new coverage for animals, bubbles, comet, glow,
  scenery, synth cues, hold detection, engine integration, and regression
  tests from both adversarial review rounds.

### Fixed (visual WOW upgrade)
- A resting frog re-triggered its floor bounce every frame (sub-pixel gravity
  re-entry), which kept him permanently squashed and would have rained
  ripples; bounces now require a real impact.

### Fixed (adversarial review round 2 — three fresh independent reviewers:
### whole-branch, fix-regression hunt, and rendered-frame visual QA)
- Glow sprites pushed every core ~92% toward white, erasing the particle
  palette (71% of burst pixels measured colorless) and flattening the fade
  curve; the core now keeps ~half its saturation, so single particles read
  as their color and true white only appears where glows overlap.
- Googly eyes were placed glyph-blind and punched pupil-holes through
  letter strokes (white ball invisible on the white outline); they now
  perch on top of the glyph with a dark rim — every letter reads as a
  creature and legibility is untouched.
- The count-along digit lived a fixed 1.9 s and was gone before the 8th,
  9th and 10th objects even appeared; it now holds until the count (and
  fanfare) finish. Fanfare bursts are bigger and fire above each object.
- Alphabet completion during the celebration cooldown silently destroyed
  both the party and the 26-letter progress (97% of completions eaten at
  mash speeds); the big party now bypasses cooldown and budget, and
  progress is only consumed when it actually fires. A budget-blocked
  ordinary milestone no longer arms the cooldown either.
- Round-1's "honest" overlay budget weight starved mash mode of its own
  bursts (72% fewer at default config; zero below max_particles=250) —
  the engine-owned mash overlay no longer taxes the spawn gates
  (CelebrationPulse, which lives in the effects list, still does).
- Trails now pause while mash chaos is active: the veil re-blended the
  full-screen hue wash every frame into a solid saturated screen.
- Space bar's drawn Rings stacked into a full-screen bullseye moiré under
  trails; replaced with expanding rings made of fading glow particles.
- Pond variants each baked their own moon and starfield, so crossfades
  showed two moons; all variants now share one sky layout. Lily pads sat
  almost entirely below the bottom edge; raised into view.
- Comet: inward steering strengthened and the clamp inset by the head
  size (heads/bursts pinned half-clipped into edges); stuck-hold auto-
  release raised 30 s → 120 s so a toddler leaning on a key keeps their
  comet; wash surface re-created on size mismatch.
- Audio: count-cue fallback removed (it double-fired "pop" at 2x amplitude
  on pre-upgrade sound dirs — the voice line already falls back);
  ANIMAL_LETTERS now imported from effects.animals instead of duplicated.
- Rainbow letter gradient now spans the full glyph (violet end previously
  fell past the ink); mini duck's stick-bill replaced with a rounded one;
  registry docstring corrected; celebration pulse draws at the same depth
  as the mash overlay it subclasses; dead `rising_balloons` removed.

### Fixed (adversarial review round 1 — three independent reviewers)
- `ChaosOverlay.draw` allocated and filled a full-screen surface every frame
  (~12 MB/frame of churn, ~1.9 ms/overlay); the wash surface is now
  persistent. Worst-case frame time dropped ~32% (17.4 → 11.8 ms mean on the
  dev box), p95 ~37%.
- Milestone celebrations now respect the particle-budget gate and a 10 s
  cooldown — under a mash storm the mega-party recurred every ~1.7 s,
  stacked up to 3 full-screen overlays, and made 3.5% of presses visually
  dead by saturating the budget.
- The degradation ladder can now shed the trail veil (off below scale 0.4,
  back above 0.6): its cost is fixed per frame, so particle scaling alone
  measurably could not recover the budget. The anti-ghost SUB/MAX pass also
  runs every 4th frame instead of every frame (~2 ms → ~0.5 ms).
- Comet trail shedding is now dt-based (was per-tick: doubled at 120 fps,
  starved at 30), and a comet whose key-release never arrives (USB unplug
  mid-hold) auto-releases after 30 s instead of living forever.
- Rate-triggered mash mode no longer strobes on/off ~19x/s under fast
  tapping (it now stays on while the press rate holds, and exits via the
  per-frame poll once tapping slows — previously it could also wedge ON
  forever, since exit only ran on a release event).
- Chaos overlay now counts toward the particle budget (its wash measured
  ~880 particle-equivalents but reported 30, blinding the spawn gates).
- Count-along pop-in scale curve was discontinuous (26% single-frame size
  snap at the overshoot boundary); digit glyph now uses the clamped count;
  fade no longer rescales sprites to an identical size every frame.
- Giant letters: a white fill could draw a white outline (~1% of letters
  became a flat glyph); the fade phase copied a ~1 MB surface per frame
  (now set_alpha in place).
- New audio cues (animal sounds, count notes) now fall back to pre-upgrade
  cues on a sounds dir generated before this change.
- `poll_holds` iterates a snapshot of held keys (latent
  dictionary-changed-during-iteration hazard for future callers).

### Added
- `VISUAL_REVIEW.md`: visual-design review of the effects layer with 10 ranked
  recommendations (glossy bubbles, farm-animal cast, additive glow, motion
  trails, shaped fireworks, characterful letters, countable objects, pond
  scene, key-hold comets, milestone celebrations) plus build order and Pi
  performance guardrails.
- Repo bootstrap: `.gitignore`, `.gitattributes` (LF for Pi-executed files),
  `CLAUDE.md` project context, this changelog.
- `RESEARCH.md`: verified findings + citations for RGB control (direct-HID
  primary / OpenRazer fallback), EVIOCGRAB capture, KMSDRM rendering, boot
  hardening, USB power budget, prior art. Target OS bumped to Raspberry Pi
  OS Lite 64-bit **Trixie** (current stable; spec assumed Bookworm).
- `PLAN.md` (architecture, module map, decision log D1–D10) and `BOM.md`
  (Pi 5 + mandatory 27 W PSU; Pi 4 budget alternative; hub as contingency).
- Core app:
  - TOML config (`lilypad.config`) with defaults, clamping, validation.
  - Input: `KeyEvent`/backend interface; SDL dev backend; evdev Pi backend
    grabbing **all** keyboard nodes exclusively; synthetic smoke backend.
  - Mapper: total keycode→action mapping (letters, numbers, space, arrows,
    enter, named specials, sparkle fallback), 2-key chords, mash-storm
    detection (5+ held or 8 presses/s).
  - Effects: particle primitives (burst, confetti, balloons, rings,
    fireworks, vacuum, spirals), giant pop-in letters, count-along numbers,
    idle attract mode, rainbow-chaos overlay, Pip the frog (arrow-key
    critter), frame-budget graceful degradation.
  - Lighting: host-side 6×22 frame math (breathing, ripples, key flash,
    mash strobe); backends: direct-USB `razer_hid` (OpenRazer wire
    protocol via pyusb), `openrazer` daemon fallback, `mock`; auto-fallback
    factory; BlackWidow Chroma key-position map.
  - Audio: pure-stdlib procedural cues (chimes, pop, whoosh, boom, drum,
    boing, chord fanfare), espeak-ng voice generation, mute flag,
    silence-on-failure mixer engine.
  - Parent escape hatch (both Shifts + Backspace, 5 s hold) with on-screen
    progress cue; clean exit stays stopped under systemd.
  - `--smoke N` self-test mode exercising the full pipeline with synthetic
    toddler input.
- Deployment: idempotent `install.sh` (apt deps, `/opt/lilypad` venv, sound
  generation, config, quiet-boot cmdline, getty@tty1 off), systemd unit
  (boot-to-app, restart-on-failure), udev keyboard-replug restart rule,
  SysRq-off sysctl.
- Tests: 47 pytest cases (mapper, chords, mash, escape timing, config,
  registry totality, lighting math, keymap bounds, synth WAVs, razer report
  layout/CRC) — all green on Windows/Python 3.14.
- Docs: `README.md` (flash-to-playing walkthrough, config table,
  troubleshooting), `VERIFY.md` (on-device checklist), MIT `LICENSE`.

### Changed (post-build quality audit)
- Hardware lighting backends now run behind a threaded latest-wins wrapper:
  razer_hid's ~7 USB control transfers per frame no longer block the render
  loop (they cost ~300 ms/s at 30 lighting fps — guaranteed stutter).
- `install.sh` no longer requests `libasound2` explicitly (Debian 13 t64
  package rename hazard); `alsa-utils` pulls the correct ALSA lib.
- Tests: 52 (added threaded-wrapper coverage: async delivery, frame
  collapsing, non-blocking apply, exception survival, clean shutdown).

### Fixed
- Lighting engine dropped its first frame when ticked at t=0 (`_last_frame`
  now starts at −∞).
- Frame-time measurement included `clock.tick`'s fps-cap sleep, so the
  graceful-degradation *recovery* path could never trigger; now measures
  work time only.
- `install.sh` was committed without its executable bit (authored on
  Windows) — `sudo ./install.sh` would have failed on the Pi.
- README license link pointed at pyproject.toml instead of LICENSE.
