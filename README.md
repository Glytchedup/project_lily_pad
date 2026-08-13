# 🐸 Project Lily Pad — Toddler Keyboard Playground

A locked-down, fullscreen Raspberry Pi app for a 2-year-old. Every key on a
**Razer BlackWidow Chroma** does something delightful on the HDMI screen — giant
letters, count-along shapes, confetti, fireworks, a bouncing frog — and the
keyboard's own RGB lights react with ripples and rainbows. The toddler cannot
exit the app, reach the OS, or trigger anything unexpected.

- **Letters** → giant colored letter + burst + **an animal for every letter** (+ spoken letter)
- **Numbers** → that many shapes pop in, count-along (+ spoken number)
- **Space** → confetti storm · **Enter** → fireworks · **Arrows** → shove Pip the frog
- **F7–F12** → 🦖 a dinosaur thunders across the screen
- **Esc / Windows / other F-keys / media keys** → fun effects, never OS actions
- **Two keys at once** → chord supernova · **Mashing 5+ keys** → rainbow chaos mode
- **Keyboard RGB**: pressed keys flash, ripples spread, idle breathing, mash strobe
- **After 5 quiet minutes** the screen goes black and the keys go dark; any key wakes it

**Parent escape hatch: hold BOTH Shifts + Backspace for 5 seconds.** A small
progress bar appears bottom-right while you hold. The app exits cleanly and
stays exited until you `sudo systemctl start lilypad` (or reboot).

Docs: [RESEARCH.md](RESEARCH.md) · [PLAN.md](PLAN.md) · [BOM.md](BOM.md) ·
[VERIFY.md](VERIFY.md) · [CHANGELOG.md](CHANGELOG.md)

---

## Hardware

See [BOM.md](BOM.md). Short version: **Raspberry Pi 5 (2 GB, given 2026 memory
prices — 4 GB is fine too) + official 27 W USB-C PSU** (the 27 W supply is
required — it unlocks the 1.6 A USB budget the keyboard's lighting needs),
32 GB A2 microSD, micro-HDMI→HDMI cable, case with fan. You already have the
keyboard and monitor.

## Flash → playing, start to finish

### 1. Flash the SD card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your PC.
2. Choose OS → **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite (64-bit)**
   (Trixie; Bookworm Lite 64-bit also works).
3. Click the ⚙️ / **Edit settings** before writing:
   - **Hostname**: `lilypad`
   - **Username/password**: user `pi`, a password you'll remember
   - **Wi-Fi**: your SSID + password (or skip if using Ethernet)
   - **Services tab: enable SSH** (password auth is fine)
4. Write the card, then boot the Pi with it (keyboard in any USB port). Start
   with **HDMI0**, the micro-HDMI port next to the USB-C connector — but if you
   get no sound or a resolution stuck at 1024x768, **try the other port before
   suspecting the cable or the TV**. On the Pi 5 used for bring-up HDMI0 had
   dead DDC lines: it reported `connected` while reading 0 bytes of EDID, so
   video worked at fallback modes and nothing looked broken. `--doctor` names
   this in one line (see [Diagnostics](#diagnostics)).

### 2. Install Lily Pad

From your PC (the Pi needs internet on first install):

```bash
ssh pi@lilypad.local
git clone https://github.com/Glytchedup/project_lily_pad.git
cd project_lily_pad
sudo ./install.sh
sudo reboot
```

That's it. After the reboot the screen goes straight to the playground —
hand over the keyboard.

`install.sh` is idempotent — re-run it any time (e.g. after `git pull`) to
upgrade. It installs the venv to `/opt/lilypad`, sounds to
`/opt/lilypad/sounds`, config to `/etc/lilypad/config.toml`, and the systemd
unit that boots to the app with the login console disabled.

### 3. First-boot checks

Work through [VERIFY.md](VERIFY.md) once — it verifies the exclusive keyboard
grab, the RGB backend, 60 fps, the escape hatch, and power-pull recovery, and
tells you what to do if a step fails.

### 4. Optional: survive power pulls (recommended)

Once VERIFY.md passes, make the SD card read-only so yanking the power cord
can never corrupt it:

```bash
sudo raspi-config nonint do_overlayfs 0   # enable overlay (read-only root)
```

To update the app later: disable the overlay (`... do_overlayfs 1`), reboot,
`git pull && sudo ./install.sh`, re-enable, reboot.

> On Trixie this installs Debian's `overlayroot` package and prepends
> `overlayroot=tmpfs` to `cmdline.txt` — it does **not** write `boot=overlay`.
> Check it with `mount | grep -i overlay`; grepping for `boot=overlay` gives a
> false negative on a system where the overlay is very much on.

---

## Diagnostics

One command answers "why is it doing that":

```bash
sudo /opt/lilypad/venv/bin/python -m lilypad --doctor
```

It checks the board model, whether the card has moved to a different Pi, HDMI
EDID per connector, which ALSA card the live port maps to, the `video=` pin,
the Wi-Fi regulatory domain, `authorized_keys`, the root overlay, under-voltage,
the service, and the generated sounds — and prints the remedy next to anything
that isn't right. It touches neither the display nor the keyboard, so it's safe
to run while the playground is up. `install.sh` runs it at the end. Exit status
is 1 if anything failed, so it drops straight into a script.

Each check exists because that exact fault cost real hours during the first
bring-up; the write-ups are in [CHANGELOG.md](CHANGELOG.md).

## Moving the card between Pis

Testing on one Pi and then swapping the microSD into the Pi 5 works — a single
Raspberry Pi OS image carries a kernel and device trees for every model, so the
card boots whatever you put it in (**Pi 3 or newer**; 64-bit Pi OS won't run on
a Pi 1/2/Zero W, and `--doctor` says so plainly rather than letting it look like
a bad flash).

Two things are properties of the *board*, not the card:

- **The HDMI ALSA card index.** A Pi 3 exposes one `vc4hdmi`; a Pi 4/5 exposes
  `vc4hdmi0` and `vc4hdmi1`. Nothing to do — `lilypad-audio.service` re-derives
  this at every boot from whichever connector returned EDID, which is also why
  moving the cable between ports fixes itself after a reboot.
- **The `video=` pin in `cmdline.txt`**, if you added one. A Pi 5 has two HDMI
  connectors and a Pi 3 has one, so a pin written on one board can name a
  connector the other hasn't got — and that failure mode is a black screen with
  no error anywhere. `install.sh` records the board it ran on, and `--doctor`
  compares, so after a swap it tells you whether the pin still points somewhere
  real.

So the routine after a swap is: boot it, run `--doctor`, fix anything it flags,
and re-run `install.sh` if you want the stamp updated. Performance differs of
course — the effect engine degrades gracefully, so an older Pi is a valid
functional test but not a frame-rate one.

---

## The sound

The keyboard is a musical instrument. Every key plays a note of the C major
pentatonic scale, laid out like a piano — lower rows are lower notes, left to
right climbs. That scale has no clashing intervals, so *any* combination of
keys pressed at once is a chord: a toddler lying on the keyboard still makes
music. Two keys inside the chord window add the diatonic triad their lower note
roots; a mash storm brings a wide open swell.

**When nobody is playing, it goes quiet.** After `display.idle_timeout` the
attract animation runs in silence, and after `display.sleep_timeout` the screen
goes black too. A playground that serenades an empty room is just noise in the
house.

There are four original instrumental tunes if you want them — set
`music.tunes = "idle"` to have one fade in behind the attract animation and
fade straight out on the next keypress, or `"always"` to loop. They are in the
same key as the keys, so playing over them lands in tune. The default is
`"off"`.

## The animals

Every letter of the alphabet brings a creature with it, each with its own
call:

| | | | |
|---|---|---|---|
| **A** alligator | **H** horse | **O** owl | **V** velociraptor 🦖 |
| **B** bear | **I** iguana | **P** pig | **W** whale |
| **C** cow | **J** jellyfish | **Q** quail | **X** x-ray fish |
| **D** duck | **K** koala | **R** rabbit | **Y** yak |
| **E** elephant | **L** lion | **S** sheep | **Z** zebra |
| **F** fox | **M** monkey | **T** T. rex 🦖 | |
| **G** giraffe | **N** narwhal | **U** unicorn | |

They don't just appear — they travel. Quadrupeds walk across with a two-beat
bob; rabbits, monkeys and the two dinosaurs hop in arcs, squashing and kicking
up dust on every landing; owls, quail, jellyfish and the pterodactyl fly;
whales, narwhals and the x-ray fish swim. Each one faces the way it's going.
The four original farm animals still pop up from the bottom edge and now take
a couple of little jumps while they're there.

**F7 to F12 summon a dinosaur** — stegosaurus, triceratops, brachiosaurus and
pterodactyl join the T. rex and velociraptor there. (F1–F6 still do balloons.)

To swap a letter's animal, edit one row of
`src/lilypad/effects/animal_specs.py` and the matching entry in
`ANIMAL_LETTERS` / `ANIMAL_VOICES` in `src/lilypad/effects/animals.py`.

## Bedtime

After `display.sleep_timeout` — 5 minutes by default — with nobody touching
the keyboard, the screen goes fully black, the keyboard lights go out and the
background music stops. Pressing any key brings it all straight back.

This is a black picture on a live HDMI output, not a powered-down one. A Pi 5
has no software route to switching the output off (`vcgencmd display_power` is
gone from the firmware and the DRM `dpms` node is read-only — both checked on
the actual device), and cutting the signal would risk the monitor dropping
hot-plug detect, which is the deadlock the forced `video=` mode exists to
prevent. If you want the backlight off too, use the monitor's own power saving.

## Configuration

Edit `/etc/lilypad/config.toml` (dev mode uses `./config.toml`), then
`sudo systemctl restart lilypad`:

| Setting | Default | Notes |
|---|---|---|
| `audio.mute` | `false` | `true` = fully silent |
| `audio.volume` | `0.8` | keypress cue level, 0–1 |
| `music.key_notes` | `true` | every key plays a musical note |
| `music.tunes` | `"off"` | background tunes: `off` \| `idle` \| `always` |
| `music.tune_volume` | `0.45` | background music level, 0–1 |
| `lighting.backend` | `"auto"` | `razer_hid` → `openrazer` → `mock` fallback chain |
| `lighting.brightness` | `0.9` | keyboard LEDs, 0–1 |
| `escape.combo` | both Shifts + Backspace | evdev key names |
| `escape.hold_seconds` | `5.0` | |
| `display.idle_timeout` | `60` | seconds until the attract animation |
| `display.sleep_timeout` | `300` | seconds until the screen goes black; `0` = never |
| `effects.silhouettes` | `true` | traced-outline art for all 26 side-on animals; `false` = the older drawn versions |

## Dev mode (no Pi needed)

Runs windowed on Windows/macOS/Linux with normal keyboard input and a mock
lighting backend that logs LED frames:

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m lilypad --dev        # play in a window; same escape combo exits
pytest                         # 880 unit tests
python -m lilypad --dev --smoke 6   # 6s automated self-test, exit code 0 = healthy
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Black screen at boot | `journalctl -u lilypad -e` over SSH. `EGL not initialized` → re-run `install.sh` (installs Mesa/EGL). Two displays/cards: set `SDL_KMSDRM_DEVICE_INDEX=1` in the unit. |
| Keyboard RGB dead but app fine | `journalctl -u lilypad | grep lighting` — if `razer_hid` failed, try the OpenRazer fallback: install per [openrazer.github.io](https://openrazer.github.io/) (use `--no-install-recommends` on Pi OS), set `lighting.backend = "openrazer"`. |
| Keyboard lights flicker / disconnect | Underpowered USB. Confirm the official 27 W PSU (Pi 5); lower `lighting.brightness`; last resort: powered hub (BOM contingency). |
| Screen black; log says `no display yet` | The monitor is off, asleep, or on another input — the Pi genuinely can't see it, because a sleeping monitor often drops HDMI hot-plug detect. Wake the monitor and the app takes the screen within ~3 s on its own. To stop it happening at all, force a mode: append `video=<connector>:1920x1080@60D` to the single line in `/boot/firmware/cmdline.txt` and reboot. **Use the connector that actually has the monitor** — `--doctor` prints it, and pinning the wrong one leaves the Pi driving nothing. **Recommended before enabling overlayfs.** |
| No sound, and/or resolution stuck at 1024x768 | One cause, two symptoms: the HDMI link read **0 bytes of EDID**, so the sink advertised no audio capability and ALSA returns error 524. Check with `wc -c < /sys/class/drm/card1-HDMI-A-1/edid` — zero means EDID, not ALSA. Move the cable to the **other HDMI port** and reboot (restarting the service won't help: SDL inherits the mode the CRTC negotiated at boot). `--doctor` does this whole diagnosis for you. |
| Sound only after moving ports | The far port is a different ALSA card. `lilypad-audio.service` re-derives this at every boot, so it should fix itself — `journalctl -u lilypad-audio` shows what it picked. Failing that, `--doctor` reports the mismatch. |
| Wi-Fi says `ssid-not-found` with an empty scan list | Not a wrong password. Check `iw reg get` for a `global country US` / `phy#0 country 00` split — regdom `00` makes 5 GHz unusable, so a 5/6 GHz router is invisible. The fix is a **cold boot**, not a command: `brcmfmac` reads its country at load time. |
| SSH key auth fails but permissions look right | `ssh-keygen -lf ~/.ssh/authorized_keys` — a key pushed over a pipe from PowerShell can land as a 0-byte file with perfect 600/700 permissions. Compare the fingerprint; don't trust `ls`. |
| Keys leak to a console after escape | They shouldn't — getty@tty1 is disabled. Get a shell via SSH, not the console. |
| Forgot the escape combo | It's in `/etc/lilypad/config.toml` — or just pull power; the app restarts on boot (enable overlayfs and the card doesn't care). |

## Architecture

Python 3.11+, pygame-ce on SDL KMSDRM (no desktop), python-evdev with an
exclusive `EVIOCGRAB` grab, and direct-USB Razer lighting with OpenRazer and
mock fallbacks. See [PLAN.md](PLAN.md) for the module map and
[RESEARCH.md](RESEARCH.md) for why each piece was chosen. All sounds are
procedurally generated (synth + espeak-ng) — no copyrighted assets. The
background tunes are original compositions written for this project.

## License

MIT — see [LICENSE](LICENSE). Original code and art; inspired by
the spirit of BabySmash and bambam (see RESEARCH.md §6), sharing no code.
