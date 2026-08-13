# Swap protocol — moving the SD card from the test Pi to the Pi 5

This card is meant to move. You set it up and test it on one Raspberry Pi, and
when you are happy you swap the same card into the Pi 5 that lives in the
bedroom. One Raspberry Pi OS image boots every model from Pi 3 up, so the card
itself travels fine — but a few things are properties of the *board*, not the
card, and this is the checklist that catches them.

`--doctor` (see [README](README.md#diagnostics)) was built for exactly this
moment: run it first on the new board and it tells you what to re-check.

## What actually differs between the boards

| | Test Pi (e.g. Pi 3) | Pi 5 | Travels with the card? |
|---|---|---|---|
| CPU / speed | slower | faster | n/a — the engine degrades gracefully |
| HDMI ports | **one** (`HDMI-A-1`), full-size | **two** (`HDMI-A-1`/`HDMI-A-2`), micro-HDMI | no — see below |
| HDMI audio ALSA card | board-specific index | board-specific index | **self-corrects** every boot |
| Power | 2.5 A micro-USB (Pi 3) | 27 W USB-C | different physical supply |
| Wi-Fi bands | 2.4 GHz (Pi 3B) | 2.4 / 5 GHz | regdom applies on cold boot |

Two of these can leave you with a **black screen and nothing in any log**, so
they are the ones the protocol is really about:

- **The `video=` pin in `cmdline.txt`.** If you pinned a mode on the test Pi
  (`video=HDMI-A-1:…`), the Pi 5 may not have that connector live — its near
  port (`HDMI-A-1`, closest to USB-C) had **dead DDC lines** on the bring-up
  board, so the working port there was `HDMI-A-2`. A pin naming a dead or
  absent connector drives nothing. `install.sh` stamps the board it ran on and
  `--doctor` compares, so the `Card swap` and `Forced HDMI mode` lines flag
  this for you.
- **The HDMI audio card** re-derives itself at every boot
  (`lilypad-audio.service` → `hdmi_audio.py`), so it needs no action — but if
  it ever looks wrong, `journalctl -u lilypad-audio` shows the connector it
  chose and the card it mapped to.

## The protocol

### 1. Finalise the software on the test Pi

Do this while the card is still in the machine you have been testing on, so the
Pi 5 boots the exact build you signed off.

```bash
# If you enabled the read-only overlay, turn it off first or changes won't stick:
sudo raspi-config nonint do_overlayfs 1 && sudo reboot
# then, after it comes back:
cd ~/project_lily_pad
git pull
sudo ./install.sh          # re-stamps the board, regenerates everything
sudo poweroff              # clean shutdown before pulling the card
```

Pull the card only once the green LED has stopped blinking.

### 2. Physical swap to the Pi 5

- **Power:** use the official **27 W USB-C** supply. The Pi 3's 2.5 A micro-USB
  brick is the wrong connector *and* not enough for a Pi 5 under load — under
  it you will see `throttled` flags and the app will stall in ways that look
  like software bugs.
- **HDMI:** the Pi 5 uses **micro-HDMI**, so you need a micro-HDMI→HDMI cable
  (the Pi 3's full-size cable will not fit). Start with the port next to USB-C;
  if you get no picture or no sound, try the **other** port before suspecting
  the cable — see fault 2 in the [CHANGELOG](CHANGELOG.md).
- Insert the card, connect the keyboard and the monitor, then power on.

### 3. Validate on the Pi 5 — before you trust it

SSH in (the hostname is unchanged) and run the doctor **first**:

```bash
sudo /opt/lilypad/venv/bin/python -m lilypad --doctor
```

Walk the report:

- [ ] **`Board model`** reads `Raspberry Pi 5`.
- [ ] **`Card swap`** is a WARN naming the old board — that is expected, it is
      telling you which settings to re-check, not reporting a fault.
- [ ] **`HDMI EDID`** shows which connector is live. If the port you plugged
      reads `0 bytes`, move the cable to the other one and reboot.
- [ ] **`Forced HDMI mode`** points at a connector this board actually has. If
      it flags a mismatch, edit the `video=…` value on the single line in
      `/boot/firmware/cmdline.txt` to the live connector and reboot. (SDL
      inherits the mode negotiated at boot, so a reboot is required — restarting
      the service is not enough.)
- [ ] **`ALSA default card`** passes on its own. If not,
      `journalctl -u lilypad-audio` shows what it picked.
- [ ] **`Wi-Fi regulatory domain`** is not a `00`/global split. The Pi 5 does
      5 GHz where a Pi 3B did not, so if your router is 5 GHz-only the radio
      needs a **cold boot** to pick up the country — see fault 3.
- [ ] **`Power / throttling`** is `throttled=0x0` on the 27 W supply.

### 4. Re-stamp and re-verify

```bash
sudo ./install.sh          # refresh the hardware stamp to the Pi 5
```

- [ ] Re-run **[VERIFY.md](VERIFY.md) §6 (performance)** on the Pi 5. The test
      Pi was a valid *functional* check but not a frame-rate one — this is the
      real target, so frame rate matters now.
- [ ] Walk **VERIFY.md §11** if you want the full swap checklist alongside this.

### 5. Lock it down for the bedroom

```bash
sudo raspi-config nonint do_overlayfs 0 && sudo reboot   # read-only root
```

With the overlay on, a toddler pulling the power can never corrupt the card.
Remember to turn it back off (`… do_overlayfs 1`) before any future
`git pull && sudo ./install.sh`.

## One-line summary

Overlay off → `git pull` → `install.sh` → `poweroff` on the test Pi → move card
+ 27 W USB-C + micro-HDMI to the Pi 5 → boot → `--doctor` → fix the `video=`
pin if flagged → `install.sh` → re-verify performance → overlay on.
