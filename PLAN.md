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
                         │  music.py      │   │  → clean exit  │
                         │  synth.py      │   └───────────────┘
                         │  tunes.py      │
                         └────────────────┘
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
| `lilypad/audio/engine.py` | pygame.mixer, mute flag, cue per action, idle background music | ✔ (mixer optional) |
| `lilypad/audio/music.py` | key → C-pentatonic note (from the LED matrix), diatonic triads | ✔ consonance property test |
| `lilypad/audio/synth.py` | generate WAVs: `Voice` instruments, notes, chords, character cues (pure stdlib math/wave) | ✔ unit-tested generator |
| `lilypad/audio/tunes.py` | four original instrumental loops, arranged + rendered to seamless WAVs | ✔ unit tests |
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
- **Audio:** all cues generated at install time by `synth.py` (`Voice` instruments for the
  musical layer, sine/noise envelopes for the character cues — pop, whoosh, boom, animals)
  plus letter/number names via `espeak-ng -w`. Mixer failure (no HDMI audio) degrades to
  silent, never crashes. `mute = true` config short-circuits everything.
- **The keyboard is an instrument.** Every key maps to a note of the C major pentatonic
  scale, derived from the same 6×22 matrix the lighting uses (lower rows = lower notes,
  left→right climbs, folded into MIDI 48–88). That scale has no minor 2nd, tritone or major
  7th in any inversion, so *any* set of keys pressed together is consonant by construction —
  a two-year-old leaning on the keyboard plays a chord, not a cluster. Keep the mapping
  pentatonic; never "fix" a clash downstream. Two-key chords add the diatonic triad their
  lower note roots; mash storms get an open add9 swell.
- **Background tunes:** four original anthemic-pop instrumental loops (`tunes.py`), rendered
  offline into seamless ~20 s WAVs and played through `pygame.mixer.music` during attract
  mode only, fading out on the next keypress. Same key as the key notes, so a child playing
  over a tune is playing in it. `music.tunes = "always" | "off"` overrides.
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
| D11 | Key notes are C major pentatonic | The scale has no minor 2nd / tritone / major 7th in any inversion, so a toddler mashing keys is consonant *by construction* — no runtime filtering, no taste calls |
| D12 | Note layout derived from `lighting/keymap.py` | One layout table, not two: adding a key for the LEDs places it musically at the same time |
| D13 | Tunes are original, in the requested style, not transcriptions | Chord progressions/tempo/production style aren't protectable, specific melodies are; keeps D9's zero-copyright-exposure property intact |
| D14 | Background tunes only during attract mode (default) | Music behind active play competes with the child's own notes; behind an empty room it invites them back |
| D15 | Animals are spec rows + one generic drawer, not 26 bespoke functions | A thousand lines of hand-drawn creatures drift in style and can't be reviewed; a data row per animal keeps the cast editable and the house style uniform. The four originals stay bespoke — they ship and look right |
| D16 | New animals are side-on and cross the screen; the original four stay front-on and peek | Mirroring or walking a *front* view sideways looks broken. Drawing orientation therefore decides the performance, and both stay correct |
| D17 | Sprite construction may be arbitrarily expensive | Everything is cached by (name, height, pose), so masks, alpha-multiply clipping and scaling are free at runtime. Only the per-frame blit budget is sacred |
| D18 | Concurrent animals capped at 5 | Every letter having a creature means a two-handed run stacks a dozen full-height alpha blits per frame — several times dearer on the Pi's software path than on the dev box. The letter and burst still fire, so no key goes dead |
| D19 | Sleep is a black *picture*, not a powered-down output | On a Pi 5 there is no software route to DPMS (`vcgencmd display_power` is gone; the DRM `dpms` node is read-only — both checked on the device), and dropping the output risks the HPD deadlock that `video=HDMI-A-1:...D` exists to prevent |
| D20 | Any raw keypress wakes the screen, not just ones that map to an action | The parent escape combo is Shift+Shift+Backspace; a lone Shift produces no Action, and a hatch that looks dead in front of a black screen is worse than no hatch |
| D21 | Animal *shape* may come from a public-domain outline; everything else stays generated | The drawn cast fails on proportion, not detail — a giraffe is a giraffe because of its neck-to-leg ratio, which stacked ellipses are structurally bad at. A traced silhouette is a stencil, not a picture: colour, shading, markings, eyes, keyline and every bit of motion are still ours. It does depart from "nothing third-party", so it is opt-out via `effects.silhouettes`. D9's concern was *copyright exposure*, and CC0 carries none |
| D22 | Traced art shipped as a three-animal trial first, then the whole side-on cast | The open question was aesthetic, not technical, and no amount of desk review answers it. Three converted animals beside twenty-three drawn ones was the cheapest way to see the difference in situ before committing to thirty outlines, thirty eye anchors and a licence audit |
| D25 | Each outline chosen from up to eight candidates, not the first hit | The first result is frequently unusable in a way that only shows when you look: pterosaurs are usually drawn from above and read as paper kites, the default monkey reads as a blob, and half the "side" views are front-on. Fetching candidates is cheap; picking badly is permanent |
| D26 | A horn and a tusk are drawn procedurally on top of the outline | There is no unicorn to photograph, and every public-domain narwhal is tuskless or drawn from above. Both animals are *defined* by the missing part, and the app already has a white horse and a whale for them to be confused with |
| D27 | Pip rests well above the bottom of the screen (`Frog.floor_y`) | He used to settle with his feet on the last row of pixels, which left literally nowhere to draw what he was sitting on. The lily pad exists in the gap that change created |
| D28 | Pip's lily pad drifts to follow him | A fixed pad cannot promise he is ever actually sitting on one — a toddler will shove him into a corner within seconds. Pads float, so drifting reads as natural rather than as a bug, and it keeps the pad cosmetic: it never blocks him, because a character a child is steering should not catch on scenery |
| D23 | Traced sprites are prebuilt at startup | Assembling one costs tens of milliseconds against about two for a drawn one. Paid lazily that is a handful of dropped frames the first time a child presses that letter — exactly when the app should feel instant. Paid at boot it is ~150 ms nobody is watching |
| D24 | Only CC0 / public-domain silhouettes, checked per image | PhyloPic mixes licences and the image a taxon shows by default is often CC-BY-NC-SA. NonCommercial in this repo would follow everyone who forks it, for art we could replace in an afternoon |
| D29 | Painted AI art, narration and music stay in the repo, credited per file | The painted route is about 380 binary files (22 MB), and keeping them in git means a fresh clone and `install.sh` give the finished look with no extra download. D9's worry was copyright exposure: every file is an original generated from pinned prompts (Gemini images, ElevenLabs narration, Lyria music), with no reference to existing characters, and its `CREDITS.md` row records model, date and style ID so any single file can be found and replaced. D38 bounds the size |
| D30 | Painted is the default, every kit degrades on its own, and `config.legacy.toml` stays pixel-identical | The classic look is the fallback and the A/B. A missing or invalid manifest or frame drops only that kit to the older route (painted -> traced -> drawn, painted FX -> glow, painted letters -> outline font) and logs once, so an art problem cannot leave a child with a blank screen. The legacy profile sets every new switch off and the config tests pin it, so the old look is one `--config config.legacy.toml` away |
| D31 | A party is earned by meeting 8 different animals (`music.reward_rule = "animals"`) | The seconds-or-presses meter rewarded volume, so one mashed key could fill it. Variety is the thing worth rewarding. Repeats, digits and non-animal keys never count. The effect engine reports the animal it actually spawned (`on_animal` -> `AudioEngine.note_animal`), so F7-F12 dinosaur picks count by name. The `"play"` rule stays, set by the legacy profile |
| D32 | The party gap is counted from the previous party's end, and there is none before the first | The gap used to start at the first event of a run, so the first party waited out the whole `reward_min_gap` after launch even with all eight animals met, and a meter filled inside the gap fired only on the next keypress. The gap exists to space parties, so it needs a previous party to space from, and it runs from that party's END so the track's own length does not eat it. Owner feedback after a live test also cut it from 180 s to 120 s. `tick()` releases a meter held back by the gap the frame it expires |
| D33 | Letters are placed clear of the characters (`ctx.occupied()`) | A large painted letter landing on Pip, Lily or a crossing animal hides what the child is watching, and the letter just pressed must stay visible. The engine reports footprints (Pip and his pad, Lily, the storybook card, the album strip, crossing animals, other glyphs); a glyph takes the sky and margins and shrinks up to 15% when crowded rather than overlap. Party fireworks reuse the same footprints |
| D34 | Googly eyes are painted layers sized once at spawn and selected by `animal_art`, not by a new setting | Cream eyes with glossy brown irises make a letter feel alive, and only the pupils (bounce on arrival, wander, blink) move per frame, so the cost stays a few small blits. The same kit gives Pip his gaze, with iris size and travel fitted to his painted eye whites. Reusing `animal_art` means traced and drawn modes keep their original eyes, with no second switch to keep in sync. The first size was enlarged after review. Count-along digits keep their old look |
| D35 | Lily, a cartoon of the owner's daughter, ships in the repo | The owner chose to commit her likeness, as a six-pose gouache cartoon and not a photograph. She is a quiet background companion (six spots, a move every 75 s, waves at arriving animals, cheers on the beat in a party, asleep when the screen is), never a control, so removing her is `scene.lily = false` with nothing else changing |
| D36 | The bundled anthems are pitch-shifted to C major | Every key plays a C-major-pentatonic note (D11, D12). An anthem in another key would clash with a child's key presses, and a child playing over a track is the point of the party. Shifting the four Lyria tracks to C with ffmpeg rubberband extends D11's consonant-by-construction guarantee to the music. Each track ships with a `.beats.json` map so the show can lock to it; a track without one runs on a 120 BPM clock |
| D37 | The narrator is recorded, plays on one reserved mixer channel, and letter names always pre-empt | One channel means two clips can never talk over each other. A letter name cuts anything off, while "X is for Animal!" waits for 0.8 s of quiet and no letter in the last 0.6 s, so a mash speaks only names. A missing clip falls back to espeak (letters, numbers) or silence (phrases, praise), and `audio.voice = "espeak"` restores the old behaviour exactly. The A and E clips were re-recorded and their TTS spellings changed to "A" and "E" because the respellings "Ay" and "Ee" did not produce the letter names |
| D38 | Assets are budgeted and credited by a test, not by review | `tests/test_asset_budget.py` fails over 1.5 MB per file, 2.5 MB for music `.ogg` (anthems stream through `mixer.music` and are never decoded into RAM), 40 MB total, a file with no CREDITS row, or a manifest naming a missing file. AI generation makes adding files cheap, and the Pi's RAM and card are finite, so the rule is enforced where it cannot be forgotten |
| D39 | The "Today's play" card holds its numbers in memory and runs on the exit path under a hard deadline | The SD card has a corruption history, so nothing about a child's play is written to disk and "today" means "since power-on". The card appears after the parent has held the escape combo, so it ignores keys, returns at its deadline, ends at once on a quit signal and never raises: a parent must never be stuck behind a summary |
| D40 | Storybook cards never queue, hide or block input | A card is a reward for three presses of one letter, not a mode. The second press prefetches on one decode thread; a card not ready within 1 s skips the show. Every key still draws over a card, so nothing a child does is swallowed. With `effects.storybook = "off"` no thread exists and no pixel changes |
| D41 | The child keeps control: encounters hand it back at once | Pip's greetings, ducks, rides and jumps are decoration. An arrow press ends a ride immediately, a ride expires after eight seconds, encounters share a six-second cooldown and pause when the frame budget degrades (quality scale under 0.5), and a pause can add at most 1.5 s to a crossing |
| D42 | V is a feathered raptor carrying an orange kitten in a gold crown and sunglasses | Owner request, replacing the earlier velociraptor look. The kitten is an original character, toes are rounded with no claws, and the pose sheet, sprite frames and storybook card V were repainted together so all three agree |
