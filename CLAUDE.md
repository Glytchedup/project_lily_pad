# Project Lily Pad — Toddler Keyboard Playground

## What this is

A locked-down, fullscreen Raspberry Pi app for a 2-year-old. Every keypress on a Razer
BlackWidow Chroma (original, USB) triggers visuals on an HDMI monitor — giant letters,
count-along objects, particles, fireworks — and the keyboard's own RGB lighting reacts
(per-key light-up, ripples, rainbow modes). The toddler can never exit the app, reach the
OS, or trigger anything unexpected. A deliberate parent combo (both Shifts + Backspace,
held 5 s) exits cleanly.

## Key documents

| File | Purpose |
|---|---|
| `RESEARCH.md` | Verified findings + citations behind every platform decision |
| `PLAN.md` | Architecture, module breakdown, decision log |
| `BOM.md` | Hardware shopping list (Pi, PSU, SD, etc. — keyboard/monitor already owned) |
| `README.md` | Flash-to-playing instructions for the Pi |
| `VERIFY.md` | On-device verification checklist (no Pi was attached during development) |
| `CHANGELOG.md` | Entry per meaningful change |
| `docs/ART_BIBLE.md` | House style ("Moonlit Gouache") every painted asset must match |

## Architecture (summary — details in PLAN.md)

Python 3.11+ package `lilypad/`, src-layout:

- `input/` — backend interface; `evdev_backend` (Pi: exclusive `EVIOCGRAB` grab) vs
  `sdl_backend` (dev: normal pygame events); `mapper.py` turns keycodes into semantic
  actions and detects 2-key chords + mash storms (5+ keys → chaos mode).
- `effects/` — pygame renderer: engine (60 fps budget, graceful degradation, motion
  trails, milestones, **screen sleep**), registry (action → effect factory), particles
  (+ additive glow, shaped fireworks), letters (outline/rainbow/googly eyes), numbers
  (countable objects), scenery (pond background), bubbles, comet (key-hold rainbows),
  ambient/idle attract. The animal cast is three files: `animal_specs.py` is the cast
  list (one data row per creature — edit this to recast a letter), `animal_art.py`
  turns a row into a cached sprite, and `animals.py` owns who appears for which key,
  what they sound like (`ANIMAL_VOICES`, imported by the audio engine so the two
  can't drift), and how they move. Every letter A–Z has a creature; six are
  dinosaurs, four of which live on F7–F12. Side-on animals **cross the screen**
  (walk/hop/fly/swim, mirrored to face their direction); the four original front-on
  farm animals keep their peekaboo. Sprite construction is arbitrarily expensive
  because everything is cached by (name, height, pose) — only the per-frame blit
  budget is sacred, which is also why concurrent animals are capped at
  `MAX_ANIMALS` — and giant letters/count-alongs at `MAX_GLYPHS` (6), which
  retires the *oldest* glyph into its fade rather than dropping the newest,
  so the key just pressed is always the visible one. The shipped art route is
  **painted** (`effects.animal_art = "painted"`, see *Painted route*); beneath it,
  **all 26 side-on creatures get their *shape* from a traced public-domain
  outline** (`animal_stencil.py`) — see below.
- `lighting/` — `LightingBackend` interface with three implementations: `razer_hid`
  (direct USB control, primary on Pi), `openrazer_backend` (fallback), `mock` (dev).
  `keymap.py` maps keycodes to the BlackWidow's (row, col) matrix for ripple math.
- `audio/` — pygame.mixer cues, procedurally generated, plus the bundled AI-generated
  narrator clips and party anthems (zero copyrighted assets *in the repo* — see
  `background_folder` below for the one deliberate, git-ignored
  exception). `music.py` is the theory core: every key maps to a **C major
  pentatonic** note, derived from `lighting/keymap.py`'s matrix (lower rows = lower
  notes, left→right climbs). That scale has no minor 2nd / tritone / major 7th in any
  inversion, so any simultaneous keypress combination is consonant *by construction*
  — don't "fix" a clash by filtering, keep the mapping pentatonic. `synth.py` renders
  `Voice` instruments (per-harmonic decay, chorus, brightness rolloff, reverb) plus
  the character cues (animals, whoosh, boom — deliberately not musical). `tunes.py`
  holds four original anthemic-pop instrumental loops, rendered to seamless WAVs.
  `voice.py` is the narrator: `audio.voice = "narrator"` (default) plays recorded
  letter/phrase/counting/praise clips on one reserved mixer channel (letters always
  pre-empt; "X is for Animal!" only after a quiet moment); `"espeak"`, and any missing
  clip, falls back to espeak-ng for letter/number names. `voice.LETTER_NAMES`
  spells names for TTS ("A" and "E" bare — the respellings "Ay"/"Ee" were spoken wrong).

  **Background music.** The default is `music.tunes = "reward"`: the room is
  quiet while the child plays, an `AudioEngine`-owned meter fills with
  *engaged* play (`reward_seconds` OR `reward_presses`, whichever first;
  gaps longer than `reward_window` don't count), and filling it buys
  fireworks over silence for `PARTY_FANFARE_SECONDS`, then one whole track
  while `Frog.dance()` keeps Pip hopping. The audio engine owns the meter
  because it owns the music; the effect engine owns what a party *looks*
  like. The main loop is the only thing that joins them —
  `audio.consume_party_started()` -> `engine.start_party()`, and
  `not audio.party_active` -> `engine.end_party()`. While `engine.party` is
  set, attract mode, screen sleep and milestone celebrations are all
  suppressed: a child watching the frog dance presses nothing, and a
  three-minute track outlasts both timeouts. With the default
  `reward_rule = "animals"` the meter is 8 distinct animals and parties are
  spaced by `reward_min_gap` (120 s) measured from the previous party's END;
  the first party has no gap, the 8th animal fires it that frame, and `tick()`
  releases one held back by the gap the instant it expires;
  `reward_rule = "play"` is the older seconds-or-presses meter (legacy profile).
  `music.reward_source` orders the track pool (`folder_first`: the parent's
  `background_folder`, then the bundled anthems in `assets/music`, then generated
  tunes; `bundled` and `generated` reorder or narrow it). The four anthems are AI-generated, shifted to C major so they sit in the
  keys' pentatonic, each with a `.ogg.beats.json` map; `audio/tracks.py`'s
  `BeatClock` reads it (120 BPM without one) and times the party show.
  During a party
  (`music.party_show`) `EffectEngine._party_fireworks` adds a sky burst every
  0.8 s (0.4 s in the fanfare) and a big shaped burst per bar, budget-gated
  and clear of `ctx.occupied()`. `_start_tune` grew a `loops`
  argument for this — a reward track must END, so it plays once; every other
  mode still loops forever. `PARTY_MAX_SECONDS` is the failsafe: every mixer
  call in there swallows its exceptions, so a wedged mixer would otherwise
  latch the party — and the sleep suppression riding on it — on forever.

  The older modes are unchanged: `_start_tune`/`_stop_tune` (the
  four generated tunes) and, in `music.tunes = "active"` mode, a parallel
  `_playlist_*` state machine (`notify_activity()` + a per-frame `tick()`) that plays
  a shuffled `music.background_folder` while keys are being pressed and fades out
  after `music.fade_after` seconds idle, resuming mid-track rather than restarting.
  `background_folder` (default `music/`) is **git-ignored** — it's meant for a
  parent's own MP3s and is the one place this project's "no copyrighted assets"
  rule is deliberately scoped to *the repo*, not the device; an empty/missing folder
  falls back to looping the generated tunes, so a stock checkout still has music.
  `music.tunes = "idle"` is the older, opposite-trigger mode (soundtrack to an empty
  room, fades out on the next keypress) and is unchanged.
- `escape.py` — parent escape hatch state machine.
- `config.py` — TOML config (volume/mute, key notes + tune mode/volume, brightness,
  escape combo, effect toggles, idle/sleep timeouts).

**Traced outlines (`effects/animal_stencil.py`)**: the old drawn cast failed on
*proportion*, not detail — a giraffe reads as a giraffe because of its
neck-to-leg ratio, which stacked ellipses are structurally bad at. So all 26
side-on creatures take their silhouette from a CC0
[PhyloPic](https://www.phylopic.org/) outline vendored in
`assets/silhouettes/` (see `CREDITS.md` there — check the licence per *image*,
PhyloPic also hosts CC-BY-NC-SA, which must never enter this repo). Everything
else is still generated: colour, belly shading, coat markings, an oversized
cartoon eye, the dark keyline, the unicorn's horn, the narwhal's tusk, and all
motion. The outline is a **stencil, not a picture** — `fill(colour,
BLEND_RGB_MAX)` swaps the colour through it and leaves the anti-aliased alpha
edge intact, so it stays crisp at any size.

Both art routes come out of `animal_sprite`, so mirroring, squash, the cache and
the gaits are untouched; the cache key carries the mode so the two can't mix.
`effects.silhouettes = false` reverts the whole cast to the drawn art, which is
still there and still tested. If SDL_image can't rasterise SVG the feature
disables itself and logs why. Sprites are prebuilt at startup (156 of them,
~1 s at 1080p) because assembling one costs several ms against ~2 for a drawn
one, and that hitch would otherwise land on a child's first keypress.

**Adding or recasting a creature** is a per-animal job: pick a CC0 outline,
drop it in `assets/silhouettes/`, add a `StencilSpec` row, credit it, and find
`eye_at` by *looking* — it is a fraction of the sprite box and the tests will
catch it landing off the body, but only your eyes will catch it landing on an
ear. The four front-on farm animals have no row and never will (see D16).

**Pip the frog** (`effects/critter.py`) is cel-shaded — flat colour, hard-edged
shadow/highlight bands, one heavy keyline stamped around the *union* of head
and body so no seam crosses his face — and sits on his own lily pad. His sprite
is cached by `(radius, pose)`; only the squash is continuous, applied as a
cheap `scale` at draw time. `Frog.floor_y` is his resting height and is
deliberately well above the bottom of the screen: that gap is what the pad
occupies. Anything that needs to know where he lands must ask `floor_y` rather
than assume `h - r`.

**Painted route (`effects.animal_art = "painted"`, the shipped default).** AI-generated
gouache art in the house style (`docs/ART_BIBLE.md`) lives in `src/lilypad/assets/<kit>/`
(`assets/…` below means that directory). A kit is a `manifest.toml`, its files and a
`CREDITS.md`, read through `effects/assets.py`. **Every kit degrades alone**: a missing
or invalid manifest, or a missing frame, logs once and the older route takes over
(painted -> traced -> drawn; painted FX -> glow), so a checkout without art still runs.
`__main__` configures them together — `critter.set_pip_art`, `letters.set_letter_art`,
`letters.set_eye_art`, `glow.set_fx_style` — and the capture tool and `bench.py` must
call the same four or they render the legacy look.

| Kit | Used by | Holds |
|---|---|---|
| `painted/` | `painted.py`, `animals.py`, `critter.py`, `lily.py` | cast frames (idle/blink/step), Pip + pad (`pip_art`), count-along minis, Lily's six poses |
| `world/` | `scenery.py`, `reflection.py`, `layout.py` | four pond moods, shore/water strips; `layout.py` holds the POND vs classic bands |
| `fx/` | `glow.py` (`fx_style`) | painted stars, confetti, bubbles, balloons, glints, bokeh |
| `letters/`, `eyes/` | `letters.py`, `eyes.py` | A–Z animal-pattern stickers and the googly-eye kit; digits keep the outline font |
| `storybook/`, `album/` | `storybook.py`, `album.py` | 26 letter cards; the day-card backdrop |
| `voice/`, `music/` | `audio/voice.py`, `audio/tracks.py` | narrator clips; four anthems + beat maps |

Gait frames come from the effect clock (`AnimalCrossing.pose_for`, no rng). The
characters and shows built on it: **Lily** (`lily.py`) sits at one of six spots and
moves every `scene.lily_move_seconds`; `ecosystem.py`'s seeded Director picks Pip's
rides, ducks, jumps and greetings; `storybook.py` shows a letter's card after three
presses (and cycles them in attract); `album.py` flies each new animal's portrait into
a top strip; `parade.py` runs the **Grand Parade** on alphabet completion and the
three-animal trios during parties; `lighting/show.py` mirrors animals and the beat onto
the keyboard. `stats.py` + `summary.py` back the parent's "Today's play" card — memory
only, nothing on disk, and `summary` runs on the escape path so it must return by its
deadline and never raise.

**Letter placement.** Giant letters and count-along digits ask `ctx.occupied()`
(`EffectEngine._occupied`: Pip and his pad, Lily, the storybook card's third, the
album strip, crossing animals) and use the sky and margins, shrinking up to 15% when
crowded; party fireworks use it too. A new thing a child can summon on screen must
report its footprint there.

**Asset rules.** `tests/test_asset_budget.py` fails the build over 1.5 MB per file
(2.5 MB for `music/*.ogg`, which stream and are never decoded), 40 MB total, a file
with no `CREDITS.md` row, or a manifest naming a missing file. Credit AI art with
model, date and style ID; never add a reference to an existing character. Lily is a
cartoon of the family's daughter, committed at the owner's choice (D35).
`config.legacy.toml` is the **pixel-identical legacy profile** (drawn pond, traced
animals, `play` rule, espeak, every painted feature off); run it with
`--config config.legacy.toml`, and keep it passing when a feature touches old pixels.

**Screen sleep**: after `display.sleep_timeout` (default 300 s) with no keypresses
the engine goes `asleep` — black frame, LEDs blanked, tunes stopped, main loop
throttled to `SLEEP_FPS`. Any *raw* keypress wakes it (`engine.wake()` is called
from the event loop, not from `spawn`, so a lone Shift counts — the escape combo
must never look dead). This is a black picture on a live HDMI output: a Pi 5 has no
software DPMS (`vcgencmd display_power` is gone, the DRM `dpms` node is read-only —
both verified on-device), and dropping the output would risk the hot-plug-detect
deadlock that `video=HDMI-A-1:...D` exists to prevent.

Deployment: `install.sh` (idempotent) + systemd unit + udev rules on Raspberry Pi OS Lite
64-bit (Bookworm), rendering via SDL `kmsdrm` — no desktop environment.

## Conventions

- Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`); commit per phase or
  module group, never one giant commit.
- Python 3.11 compatibility is the floor (Pi OS Bookworm); dev box runs newer.
- Everything hardware-touching sits behind an interface with a mock, so the full app runs
  and tests on a desktop with `--dev`.
- Update `CHANGELOG.md` and this file with every meaningful change.
- No copyrighted characters/assets anywhere **in the repo** — original visuals,
  generated audio (AI-generated art, narration and music are credited per file). The one deliberate exception is `music.background_folder`
  (default `music/`, git-ignored): a parent's own songs for background music,
  local to their device only. Never remove it from `.gitignore` or commit its
  contents.

## Dev quickstart

```bash
pip install -e .[dev]
python -m lilypad --dev       # windowed dev mode, mock lighting
python -m lilypad --dev --smoke 6   # automated full-pipeline self-test
pytest                        # 1772 passed, 5 skipped (~90 s)
python -m lilypad.bench       # frame-time replay of heavy, party and idle scenes
```

On a headless box run `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q`.

## Status / gotchas

- Target OS is Raspberry Pi OS Lite 64-bit **Trixie** (research bumped it from
  the spec's Bookworm — see RESEARCH.md §0); everything hardware-facing is
  unverified on real metal until VERIFY.md is run on-device.
- The lighting keymap (`lighting/keymap.py`) is documentation-derived; ripple
  origins may need on-device nudging (cosmetic only).
- `install.sh` is the single source of deployment truth; keep unit/udev/sysctl
  files in `deploy/` and the installer in sync.
- Windows dev box: line endings are handled by `.gitattributes` (LF forced for
  `.sh`/`.py`/`.service`/`.rules`/`.toml`/`.conf`) — don't fight it.

## Portfolio registry (Ground-Zero) — part of the definition of done
This repo is tracked as `project-lily-pad` in Glytchedup/Ground-Zero (`registry/projects/project-lily-pad.yaml`).
A change is not done until the registry matches reality when the change does any of these:
- deploys, renames, recreates or deletes a Fabric item, semantic model, report, Copilot Studio agent,
  Power Automate flow, Dataverse table or Snowflake task/table;
- changes a refresh or run schedule (update `monitor.success_sla_hours`);
- moves something between environments (use asset `state: planned | active | retiring | retired`);
- changes the project's lifecycle, next steps or blockers.
How: attach Glytchedup/Ground-Zero, edit the YAML on a branch, run `python -m gz validate && python -m gz build`,
open a PR. Never put secrets, row-level data or user lists in the registry.
