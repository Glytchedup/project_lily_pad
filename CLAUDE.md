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
  trails, milestones), registry (action → effect factory), particles (+ additive glow,
  shaped fireworks), letters (outline/rainbow/googly eyes), numbers (countable
  objects), scenery (pond background), bubbles, animals (peekaboo cast), comet
  (key-hold rainbows), ambient/idle attract.
- `lighting/` — `LightingBackend` interface with three implementations: `razer_hid`
  (direct USB control, primary on Pi), `openrazer_backend` (fallback), `mock` (dev).
  `keymap.py` maps keycodes to the BlackWidow's (row, col) matrix for ripple math.
- `audio/` — pygame.mixer cues; all sounds procedurally generated (synth chimes + espeak-ng
  letter names) — zero copyrighted assets.
- `escape.py` — parent escape hatch state machine.
- `config.py` — TOML config (volume/mute, brightness, escape combo, effect toggles).

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
pytest                        # 175 unit tests (mapper, registry, config, escape, lighting, synth, threading, effects)
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
