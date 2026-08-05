# 🐸 Project Lily Pad — Toddler Keyboard Playground

A locked-down, fullscreen Raspberry Pi app for a 2-year-old. Every key on a
**Razer BlackWidow Chroma** does something delightful on the HDMI screen — giant
letters, count-along shapes, confetti, fireworks, a bouncing frog — and the
keyboard's own RGB lights react with ripples and rainbows. The toddler cannot
exit the app, reach the OS, or trigger anything unexpected.

- **Letters** → giant colored letter + burst (+ spoken letter)
- **Numbers** → that many shapes pop in, count-along (+ spoken number)
- **Space** → confetti storm · **Enter** → fireworks · **Arrows** → shove Pip the frog
- **Esc / Windows / F-keys / media keys** → fun effects, never OS actions
- **Two keys at once** → chord supernova · **Mashing 5+ keys** → rainbow chaos mode
- **Keyboard RGB**: pressed keys flash, ripples spread, idle breathing, mash strobe

**Parent escape hatch: hold BOTH Shifts + Backspace for 5 seconds.** A small
progress bar appears bottom-right while you hold. The app exits cleanly and
stays exited until you `sudo systemctl start lilypad` (or reboot).

Docs: [RESEARCH.md](RESEARCH.md) · [PLAN.md](PLAN.md) · [BOM.md](BOM.md) ·
[VERIFY.md](VERIFY.md) · [CHANGELOG.md](CHANGELOG.md)

---

## Hardware

See [BOM.md](BOM.md). Short version: **Raspberry Pi 5 (4 GB) + official 27 W
USB-C PSU** (the 27 W supply is required — it unlocks the 1.6 A USB budget the
keyboard's lighting needs), 32 GB A2 microSD, micro-HDMI→HDMI cable, case with
fan. You already have the keyboard and monitor.

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
4. Write the card, then boot the Pi with it (HDMI0 — the micro-HDMI port next
   to the USB-C power connector — keyboard plugged into any USB port).

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

---

## Configuration

Edit `/etc/lilypad/config.toml` (dev mode uses `./config.toml`), then
`sudo systemctl restart lilypad`:

| Setting | Default | Notes |
|---|---|---|
| `audio.mute` | `false` | `true` = fully silent |
| `audio.volume` | `0.8` | 0–1 |
| `lighting.backend` | `"auto"` | `razer_hid` → `openrazer` → `mock` fallback chain |
| `lighting.brightness` | `0.9` | keyboard LEDs, 0–1 |
| `escape.combo` | both Shifts + Backspace | evdev key names |
| `escape.hold_seconds` | `5.0` | |
| `display.idle_timeout` | `60` | seconds until the attract animation |

## Dev mode (no Pi needed)

Runs windowed on Windows/macOS/Linux with normal keyboard input and a mock
lighting backend that logs LED frames:

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m lilypad --dev        # play in a window; same escape combo exits
pytest                         # 47 unit tests
python -m lilypad --dev --smoke 6   # 6s automated self-test, exit code 0 = healthy
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Black screen at boot | `journalctl -u lilypad -e` over SSH. `EGL not initialized` → re-run `install.sh` (installs Mesa/EGL). Two displays/cards: set `SDL_KMSDRM_DEVICE_INDEX=1` in the unit. |
| Keyboard RGB dead but app fine | `journalctl -u lilypad | grep lighting` — if `razer_hid` failed, try the OpenRazer fallback: install per [openrazer.github.io](https://openrazer.github.io/) (use `--no-install-recommends` on Pi OS), set `lighting.backend = "openrazer"`. |
| Keyboard lights flicker / disconnect | Underpowered USB. Confirm the official 27 W PSU (Pi 5); lower `lighting.brightness`; last resort: powered hub (BOM contingency). |
| No sound | Monitor may need HDMI audio selected; test `speaker-test -t wav` over SSH. Or set `audio.mute = true` and enjoy the silence. |
| Keys leak to a console after escape | They shouldn't — getty@tty1 is disabled. Get a shell via SSH, not the console. |
| Forgot the escape combo | It's in `/etc/lilypad/config.toml` — or just pull power; the app restarts on boot (enable overlayfs and the card doesn't care). |

## Architecture

Python 3.11+, pygame-ce on SDL KMSDRM (no desktop), python-evdev with an
exclusive `EVIOCGRAB` grab, and direct-USB Razer lighting with OpenRazer and
mock fallbacks. See [PLAN.md](PLAN.md) for the module map and
[RESEARCH.md](RESEARCH.md) for why each piece was chosen. All sounds are
procedurally generated (synth + espeak-ng) — no copyrighted assets.

## License

MIT — see [pyproject.toml](pyproject.toml). Original code and art; inspired by
the spirit of BabySmash and bambam (see RESEARCH.md §6), sharing no code.
