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

## Architecture (summary — details in PLAN.md)

Python 3.11+ package `lilypad/`, src-layout:

- `input/` — backend interface; `evdev_backend` (Pi: exclusive `EVIOCGRAB` grab) vs
  `sdl_backend` (dev: normal pygame events); `mapper.py` turns keycodes into semantic
  actions and detects 2-key chords + mash storms (5+ keys → chaos mode).
- `effects/` — pygame renderer: engine (60 fps budget, graceful degradation, motion
  trails, milestones, **screen sleep**), registry (action → effect factory), particles
  (+ additive glow, shaped fireworks), letters (outline/rainbow/googly eyes), numbers
  (countable objects), **shapes** (colours + shapes — see below), scenery (pond
  background), bubbles, comet (key-hold rainbows), ambient/idle attract. The
  animal cast is a small package. `animal_specs.py` is the cast list (one data
  row per creature — edit this to recast a letter). `animal_art.py` is the
  **front door**: the public sprite API and the caches, and the module everything
  else imports from. The drawing behind it is split by purpose —
  `animal_paint.py` (palette + primitives; depends on nothing),
  `animal_farm.py` (the four hand-drawn front-on originals),
  `animal_parts.py` (where ears, muzzles, tails and features attach),
  `animal_body.py` (six builders, one per body plan), `animal_mini.py`
  (countable objects). Imports run one way, into `animal_paint`; a back-edge
  makes a cycle. And `animals.py` owns who appears for which key,
  what they sound like (`ANIMAL_VOICES`, imported by the audio engine so the two
  can't drift), and how they move. Every letter A–Z has a creature; six are
  dinosaurs, four of which live on F7–F12. Side-on animals **cross the screen**
  (walk/hop/fly/swim, mirrored to face their direction); the four original front-on
  farm animals keep their peekaboo. Sprite construction is arbitrarily expensive
  because everything is cached by (name, height, pose) — only the per-frame blit
  budget is sacred, which is also why concurrent animals are capped at
  `MAX_ANIMALS`. **All 26 side-on creatures get their *shape* from a traced
  public-domain outline** (`animal_stencil.py`) — see below.
- `lighting/` — `LightingBackend` interface with three implementations: `razer_hid`
  (direct USB control, primary on Pi), `openrazer_backend` (fallback), `mock` (dev).
  `keymap.py` maps keycodes to the BlackWidow's (row, col) matrix for ripple math.
- `audio/` — pygame.mixer cues, all procedurally generated (zero copyrighted assets).
  `music.py` is the theory core: every key maps to a **C major pentatonic** note,
  derived from `lighting/keymap.py`'s matrix (lower rows = lower notes, left→right
  climbs). That scale has no minor 2nd / tritone / major 7th in any inversion, so any
  simultaneous keypress combination is consonant *by construction* — don't "fix" a
  clash by filtering, keep the mapping pentatonic. `synth.py` renders `Voice`
  instruments (per-harmonic decay, chorus, brightness rolloff, reverb) plus the
  character cues (animals, whoosh, boom — deliberately not musical). `tunes.py` holds
  four original anthemic-pop instrumental loops, rendered to seamless WAVs and played
  as idle background music via `pygame.mixer.music`. Letter/number names come from
  espeak-ng.
- `doctor.py` — on-device diagnostics (`python -m lilypad --doctor`), one check
  per fault the first bring-up hit. Every filesystem root and command runner is
  injected, which is the only reason it is testable off-Pi — keep it that way.
- `hdmi_audio.py` — picks the ALSA card matching whichever HDMI connector
  returned EDID. Runs at **every boot** via `lilypad-audio.service`, not once at
  install, because the card index is a property of the board and this SD card is
  expected to move between a test Pi and the Pi 5.
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

**Colours and shapes** (`effects/shapes.py`) are the third lesson, on the
punctuation keys. The two effects are deliberately opposite: `GiantShape`
holds the shape constant and randomises the colour, `ColorSplash` holds the
colour constant and varies the shapes — a circle that is always blue teaches
"blue circle" as one word, so *don't* "fix" the randomness. Art is cel-shaded
like Pip and drawn at `SUPERSAMPLE`× then scaled down. Colour is a
`BLEND_RGB_MULT` tint over one cached **white** master per `(kind, size)`, so
the palette is nearly free; the dark keyline survives the multiply on purpose,
and it is load-bearing — five same-coloured shapes sit side by side in a
splash and would otherwise merge. `audio/synth.py:build_voice` imports
`NAMED_COLORS` and `SHAPE_KINDS` rather than repeating them, so a new shape
cannot ship without a spoken word.

**Pip the frog** (`effects/critter.py`) is cel-shaded — flat colour, hard-edged
shadow/highlight bands, one heavy keyline stamped around the *union* of head
and body so no seam crosses his face — and sits on his own lily pad. His sprite
is cached by `(radius, pose)`; only the squash is continuous, applied as a
cheap `scale` at draw time. `Frog.floor_y` is his resting height and is
deliberately well above the bottom of the screen: that gap is what the pad
occupies. Anything that needs to know where he lands must ask `floor_y` rather
than assume `h - r`. **His resting test is frame-rate relative** — a landing
counts as a bounce only if it beats `h * GRAVITY * dt * REST_FACTOR`. The old
fixed threshold made a *stationary* frog register an impact every frame below
~37 fps, squashing and spawning ripples forever; never reintroduce a constant
there. He rides the pad's bob only while `resting`.

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
- No copyrighted characters/assets anywhere — original visuals, generated audio.

## Dev quickstart

```bash
pip install -e .[dev]
python -m lilypad --dev       # windowed dev mode, mock lighting
python -m lilypad --dev --smoke 6   # automated full-pipeline self-test
python -m lilypad --doctor    # on-device diagnostics (safe to run anywhere)
pytest                        # 1009 unit tests (mapper, registry, config, escape, lighting, music, synth, tunes, threading, effects, animals, sleep, stencil, critter, shapes, doctor, hdmi_audio)
```

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
