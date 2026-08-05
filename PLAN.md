# PLAN.md — Architecture & decision log

Built from RESEARCH.md findings. The optional post-research interview was skipped: research
confirmed the pre-registered hypotheses (direct-HID lighting primary, KMSDRM rendering), and
the only deviation from the original spec — targeting Raspberry Pi OS **Trixie** rather than
Bookworm — is a straight version bump with no architectural impact.

## Target platform

- **Board:** Raspberry Pi 5 (4 GB) — see BOM.md (Pi 4 works too; config is identical)
- **OS image:** Raspberry Pi OS **Lite 64-bit (Trixie / Debian 13)**, current release via
  Raspberry Pi Imager
- **Python:** 3.11+ floor (Trixie ships 3.13; dev box runs 3.14)
- **Rendering:** pygame-ce on SDL2 KMSDRM, fullscreen native mode, no desktop/compositor
- **Input:** python-evdev, `EVIOCGRAB` exclusive grab, root systemd service
- **Lighting:** direct USB (pyusb) speaking the OpenRazer wire protocol; OpenRazer daemon as
  fallback backend; mock backend for dev

## Architecture

```
                 ┌─────────────────────────────────────────────────┐
                 │                 main loop (60 fps)               │
                 │  __main__.py — mode select (--dev/--kiosk),      │
                 │  config load, backend wiring, frame clock        │
                 └───────┬──────────────┬──────────────┬───────────┘
                         │              │              │
              KeyEvents  │              │ actions      │ frame tick
                         │              │              │
   ┌─────────────────────┴──┐   ┌───────┴────────┐   ┌─┴──────────────────┐
   │ input/                 │   │ effects/       │   │ lighting/          │
   │  base.py (interface)   │   │  registry.py   │   │  base.py (iface)   │
   │  evdev_backend.py (Pi) │──▶│  engine.py     │──▶│  razer_hid.py (Pi) │
   │  sdl_backend.py (dev)  │   │  particles.py  │   │  openrazer_…py     │
   │  mapper.py             │   │  letters.py    │   │  mock.py (dev)     │
   │   keycode → action     │   │  numbers.py    │   │  keymap.py 6×22    │
   │   chords, mash-storm   │   │  ambient.py    │   │  effects: ripple,  │
   └────────────────────────┘   └───────┬────────┘   │  breathe, strobe   │
                                        │            └────────────────────┘
                         ┌──────────────┴─┐   ┌───────────────┐
                         │ audio/         │   │ escape.py      │
                         │  engine.py     │   │  ⇧+⇧+⌫ held 5s │
                         │  synth.py      │   │  → clean exit  │
                         └────────────────┘   └───────────────┘
```

**Event flow:** input backend produces normalized `KeyEvent`s (keycode, pressed/released,
monotonic time) → `mapper` classifies into semantic `Action`s (letter/number/space/arrow/
enter/special + chord/mash detection) → `engine` asks `registry` for effect instances and
runs them; every action is also forwarded to `lighting` (key ripple) and `audio` (cue).
`escape` watches raw key state independently of the mapper so no toddler input path can
mask it.

## Module breakdown

| Module | Responsibility | Testable without hardware |
|---|---|---|
| `lilypad/config.py` | TOML load/validate/defaults (stdlib `tomllib`) | ✔ unit tests |
| `lilypad/input/base.py` | `KeyEvent`, `InputBackend` protocol | ✔ |
| `lilypad/input/evdev_backend.py` | find all keyboard event nodes, `grab()`, non-blocking read | Pi only (VERIFY.md) |
| `lilypad/input/sdl_backend.py` | pygame KEYDOWN/KEYUP → `KeyEvent` | ✔ dev mode |
| `lilypad/input/mapper.py` | keycode→`Action`; 2-key chords; 5+ key mash-storm state machine | ✔ unit tests |
| `lilypad/effects/engine.py` | active-effect list, frame budget, degradation | ✔ unit tests (headless surface) |
| `lilypad/effects/registry.py` | action→effect factories, weighted random pick | ✔ unit tests |
| `lilypad/effects/particles.py` | bursts, fireworks, confetti | ✔ headless |
| `lilypad/effects/letters.py` | giant glyphs, bright palette | ✔ headless |
| `lilypad/effects/numbers.py` | N objects count-along | ✔ headless |
| `lilypad/effects/ambient.py` | idle attract (60 s), rainbow-chaos overlay | ✔ headless |
| `lilypad/lighting/base.py` | `LightingBackend` iface + shared frame math (ripple/breathe/strobe computed host-side into a 6×22 RGB grid) | ✔ unit tests |
| `lilypad/lighting/razer_hid.py` | pyusb: 90-byte reports, CRC, custom frame rows, brightness | Pi only (VERIFY.md) |
| `lilypad/lighting/openrazer_backend.py` | same iface via openrazer daemon | Pi only |
| `lilypad/lighting/mock.py` | logs/records frames | ✔ used by tests |
| `lilypad/lighting/keymap.py` | evdev keycode → (row, col) on BW Chroma 6×22 | ✔ unit tests |
| `lilypad/audio/engine.py` | pygame.mixer, mute flag, cue per action | ✔ (mixer optional) |
| `lilypad/audio/synth.py` | generate WAVs: chimes, pops, booms (pure stdlib math/wave) | ✔ unit-tested generator |
| `lilypad/escape.py` | hold-to-exit state machine (default: both Shifts + Backspace, 5 s) | ✔ unit tests |

## Key design points

- **Every key does something.** The mapper has a total mapping: unknown/oddball keycodes fall
  through to a "sparkle" action — Esc, Fn-emitted media codes, Windows key included. On the
  Pi nothing can reach the OS anyway (exclusive grab); mappings are about fun, not safety.
- **Chords:** two simultaneously-held mapped keys within 150 ms trigger a chord effect
  (color-mix supernova). **Mash-storm:** ≥5 keys held → rainbow chaos mode (screen overlay +
  keyboard strobe-rainbow) until held-count drops below 3.
- **Lighting frames host-side:** all animation math produces a 6×22 RGB grid at ~30 Hz;
  backends only ship the grid (rows 0x0B + custom-frame 0x0A) — so ripple/breathe/strobe are
  identical (and unit-testable) across razer_hid / openrazer / mock.
- **Escape hatch** reads raw held-key state (both Shifts + Backspace, continuous 5 s,
  config-overridable) → clean shutdown: restore keyboard to spectrum effect, release grabs,
  exit 0. systemd `Restart=always` would restart the app, so the service also ships
  `lilypad-stop` (`systemctl stop lilypad`) invoked via the escape path's exit code:
  escape exit uses code 0 + `SuccessExitStatus` and `Restart=on-failure`… simpler: escape
  exit runs `systemctl stop lilypad` when running under systemd (detected via
  `INVOCATION_ID`), plain `sys.exit(0)` in dev.
- **Audio:** all cues generated at install time by `synth.py` (sine/noise envelopes — chime,
  pop, whoosh, boom) plus letter/number names via `espeak-ng -w`. Mixer failure (no HDMI
  audio) degrades to silent, never crashes. `mute = true` config short-circuits everything.
- **60 fps budget:** engine tracks EMA frame time; over budget → halves particle caps and
  disables trail effects first, then reduces to single-effect mode. Never drops input.
- **Config** (`/etc/lilypad/config.toml`, dev: `./config.toml`): volume, mute, brightness,
  escape combo + hold seconds, idle timeout, particle caps, lighting backend selection
  (`auto` → razer_hid → openrazer → mock).

## Decision log

| # | Decision | Rationale (research §) |
|---|---|---|
| D1 | Pi OS Lite 64-bit Trixie | Current stable, kernel 6.12 LTS, 5-yr support (§0) |
| D2 | Direct-HID lighting primary, OpenRazer fallback | DKMS on Pi is the fragile path; protocol fully documented (§1) |
| D3 | pygame-ce from pip in venv | Distro pygame ships broken SDL for Lite; pip wheels bundle KMSDRM-enabled SDL (§3) |
| D4 | KMSDRM direct, no compositor | Fewest moving parts at 60 fps (§3) |
| D5 | Root systemd service | evdev grab + DRM + USB control all need privilege; single-purpose appliance (§2) |
| D6 | evdev grab of ALL keyboard nodes | BW Chroma splits media keys onto a second event node (§2) |
| D7 | Pi 5 + official 27 W PSU, no hub | 1.6 A USB budget only with PD 5A; keyboard ≤500 mA (§5) |
| D8 | Overlayfs opt-in after verification | Read-only root survives power pulls but blocks updates (§4) |
| D9 | Sounds synthesized + espeak-ng at install | Zero copyright exposure in a public repo (§6) |
| D10 | Lighting math host-side, backends dumb | One implementation of ripple/breathe/strobe, fully unit-testable |
