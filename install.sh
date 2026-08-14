#!/usr/bin/env bash
# Lily Pad installer for a fresh Raspberry Pi OS Lite 64-bit (Trixie; Bookworm
# also works). Idempotent: safe to re-run after a git pull to upgrade.
#
# Usage:  sudo ./install.sh
# Then:   sudo reboot   (the app starts on boot)
#
# What it does (see README.md for the full walkthrough):
#   1. apt packages: venv/toolchain, Mesa KMSDRM/EGL runtime, ALSA, espeak-ng
#   2. venv at /opt/lilypad/venv with this checkout installed (pygame-ce,
#      evdev, pyusb)
#   3. sound generation (synth cues + espeak-ng voice) into /opt/lilypad/sounds
#   4. /etc/lilypad/config.toml (kept if it already exists)
#   5. systemd units + udev replug rule + sysrq-off sysctl
#   6. console hardening: getty@tty1 off, quiet boot cmdline
#   7. appliance tuning: drop the network wait, stamp the board, self-check
#
# Note this card is expected to move between a test Pi and the Pi 5, so
# anything board-specific (the HDMI ALSA card) is derived at every boot by
# lilypad-audio.service rather than written here. See src/lilypad/hdmi_audio.py.
set -euo pipefail

APP_DIR=/opt/lilypad
CONFIG_DIR=/etc/lilypad
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CMDLINE=/boot/firmware/cmdline.txt

say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARN: %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo ./install.sh" >&2; exit 1; }
command -v apt-get >/dev/null || { echo "This installer expects Raspberry Pi OS (apt)." >&2; exit 1; }

say "1/6 Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
# --no-install-recommends keeps Debian's generic kernel/headers off the Pi
# (RESEARCH.md §1) and the footprint small.
apt-get install -y --no-install-recommends \
    python3-venv python3-dev build-essential \
    libegl1 libgles2 libgbm1 libdrm2 libegl-dev \
    alsa-utils \
    espeak-ng

say "2/6 Creating venv and installing lilypad"
mkdir -p "$APP_DIR"
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/venv/bin/pip" install "$REPO_DIR[pi]"

# Notes, chords, character cues and four ~20 s instrumental tunes, all
# synthesized in pure Python — a minute or so on a Pi, then never again.
say "3/6 Generating sounds (notes, chords, tunes + espeak-ng voice) — takes a minute"
"$APP_DIR/venv/bin/python" -m lilypad.audio.synth "$APP_DIR/sounds"

say "4/6 Config"
mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_DIR/config.toml" ]; then
    echo "keeping existing $CONFIG_DIR/config.toml"
else
    install -m 0644 "$REPO_DIR/config.toml" "$CONFIG_DIR/config.toml"
fi

say "5/7 systemd units, udev rule, sysctl"
install -m 0644 "$REPO_DIR/deploy/lilypad.service"        /etc/systemd/system/lilypad.service
install -m 0644 "$REPO_DIR/deploy/lilypad-audio.service"  /etc/systemd/system/lilypad-audio.service
install -m 0644 "$REPO_DIR/deploy/lilypad-replug.service" /etc/systemd/system/lilypad-replug.service
install -m 0644 "$REPO_DIR/deploy/99-lilypad.rules"       /etc/udev/rules.d/99-lilypad.rules
install -m 0644 "$REPO_DIR/deploy/90-lilypad-sysctl.conf" /etc/sysctl.d/90-lilypad.conf
systemctl daemon-reload
udevadm control --reload-rules
sysctl -q -p /etc/sysctl.d/90-lilypad.conf || true
systemctl enable lilypad.service
systemctl enable lilypad-audio.service

say "6/7 Console hardening (getty off tty1, quiet boot)"
systemctl disable getty@tty1.service || true
if [ -f "$CMDLINE" ]; then
    for param in quiet loglevel=1 logo.nologo vt.global_cursor_default=0 consoleblank=0; do
        key="${param%%=*}"
        # Append only if the key isn't already present (with or without a value).
        if ! tr ' ' '\n' < "$CMDLINE" | grep -q "^${key}\(=\|$\)"; then
            sed -i "1s/\$/ $param/" "$CMDLINE"
        fi
    done
    echo "cmdline: $(cat "$CMDLINE")"
else
    warn "$CMDLINE not found — skipping quiet-boot params (not a Pi?)"
fi

say "7/7 Appliance tuning and self-check"
# NetworkManager-wait-online can stall boot for up to a minute when the network
# is absent, and cloud-init pulls network-online.target in behind it. The app
# has no network dependency of any kind — every cue is generated to disk right
# here at install time — so the wait buys nothing and costs a toddler a minute
# of black screen. Verified on-device: disabling it was part of the 7.1 s boot.
if systemctl list-unit-files NetworkManager-wait-online.service >/dev/null 2>&1; then
    systemctl disable NetworkManager-wait-online.service >/dev/null 2>&1 || true
    echo "disabled NetworkManager-wait-online (the app is fully offline)"
fi

# Pick the HDMI audio card now so sound works before the first reboot; the
# boot-time unit re-derives it every time after that.
"$APP_DIR/venv/bin/python" -m lilypad.hdmi_audio || \
    warn "could not set the HDMI audio card — run --doctor after rebooting"

# Record which board this was set up on, so --doctor can say "this card has
# moved" rather than leaving a stale video= pin to fail silently.
"$APP_DIR/venv/bin/python" - <<'PY' || true
from pathlib import Path
from lilypad.doctor import write_stamp
write_stamp(Path("/"))
PY

"$APP_DIR/venv/bin/python" -m lilypad --doctor || \
    warn "the doctor reported faults — see the remedies above"

say "Done"
cat <<'EOF'
Next steps:
  sudo reboot                 -> Lily Pad starts fullscreen on boot
  Parent escape hatch:        hold BOTH Shifts + Backspace for 5 seconds
  Start again after escape:   sudo systemctl start lilypad
  Watch logs:                 journalctl -u lilypad -f
  Diagnose anything odd:      sudo /opt/lilypad/venv/bin/python -m lilypad --doctor
  On-device self-test:        sudo systemctl stop lilypad
                              sudo /opt/lilypad/venv/bin/python -m lilypad --kiosk --smoke 15

Moving this card to another Pi (e.g. testing here, then into the Pi 5): just
swap it — one Raspberry Pi OS image boots every model from Pi 3 up. Run
`--doctor` on the new board; it compares against the stamp written above and
tells you if the video= pin in cmdline.txt names a connector this board hasn't
got. The HDMI audio card re-derives itself on every boot, so it needs nothing.

Optional (recommended once VERIFY.md passes) - survive power pulls with a
read-only root overlay:
  sudo raspi-config nonint do_overlayfs 0    # enable  (disable: ... 1)
  (Disable it again before running install.sh updates.)
EOF
