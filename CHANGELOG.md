# Changelog

All notable changes to Project Lily Pad (Toddler Keyboard Playground) are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is
pre-1.0, so everything lands under Unreleased until first on-device verification.

## [Unreleased]

### Added
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
