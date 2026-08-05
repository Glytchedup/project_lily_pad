# RESEARCH.md — Verified findings behind every platform decision

Researched 2026-08-05 against current sources (not training memory). Each section ends with a
**Decision** used by PLAN.md.

---

## 0. OS baseline (affects everything below)

The spec assumed Raspberry Pi OS Lite 64-bit **Bookworm**, but as of October 2025 the current
stable Raspberry Pi OS is **Trixie** (Debian 13, kernel 6.12 LTS, supported to ~2030)
([raspberrypi.com announcement](https://www.raspberrypi.com/news/trixie-the-new-version-of-raspberry-pi-os/),
[RaspberryTips version overview](https://raspberrytips.com/raspberry-pi-os-versions/)).
Nothing in this project depends on Bookworm specifics — we use a venv with pip-installed
pygame-ce precisely so the distro's Python packaging doesn't matter.

**Decision:** Target **Raspberry Pi OS Lite 64-bit (Trixie)**, current image from Raspberry Pi
Imager. Everything also works on Bookworm Lite 64-bit if you have an older image; README notes
the one package-name caveat.

---

## 1. BlackWidow Chroma RGB control on Linux/ARM64

### Option A — OpenRazer (DKMS kernel driver + userspace daemon)

- OpenRazer supports the BlackWidow Chroma (VID `0x1532`, PID `0x0203`) and is the reference
  implementation ([openrazer.github.io](https://openrazer.github.io/)).
- It is **not packaged for Raspberry Pi OS**; Debian carries it only in newer suites
  ([Debian sid package](https://packages.debian.org/sid/openrazer-driver-dkms)), and ARM64 DKMS
  builds on Pi kernels have documented failures ("Bad return status for module build",
  [openrazer#1423](https://github.com/openrazer/openrazer/issues/1423)).
- DKMS on Pi OS has a classic footgun: apt pulls Debian's generic aarch64 kernel headers instead
  of the Pi kernel's unless you install with `--no-install-recommends`
  ([Pi forums t=357549](https://forums.raspberrypi.com/viewtopic.php?t=357549)).
- Every kernel update re-triggers a DKMS rebuild — exactly the kind of silent breakage a
  toddler appliance must not have. It also drags in a D-Bus daemon stack we don't need.

### Option B — Direct USB control (pyusb), speaking OpenRazer's wire protocol

The protocol is fully documented by OpenRazer's driver source and independent
reverse-engineering wikis
([razer_chroma_drivers wiki](https://github.com/pez2001/razer_chroma_drivers/wiki/Reverse-Engineering-USB-Protocol),
[rbrick/razer-drivers wiki](https://github.com/rbrick/razer-drivers/wiki/Reverse-Engineering-USB-Protocol)),
with multiple standalone Python implementations as prior art
([blackwidowcontrol](https://github.com/Martchus/blackwidowcontrol),
[razer-chroma-keyboard on PyPI](https://pypi.org/project/razer-chroma-keyboard)).

Implementation facts (from
[`razercommon.c`](https://github.com/openrazer/openrazer/blob/master/driver/razercommon.c),
[`razercommon.h`](https://github.com/openrazer/openrazer/blob/master/driver/razercommon.h),
[`razerchromacommon.c`](https://github.com/openrazer/openrazer/blob/master/driver/razerchromacommon.c)):

- **Transport:** 90-byte HID feature report via USB control transfer.
  Send: `bmRequestType=0x21` (Class | Interface | Out), `bRequest=0x09` (SET_REPORT),
  `wValue=0x0300`, `wIndex=0x02` (the keyboard's control interface). Read responses with
  `0xA1`/`0x01` (GET_REPORT), same wValue. A short delay (~1 ms plus) between send and receive.
- **Report layout (90 bytes):** status(1), transaction_id(1, use `0xFF`),
  remaining_packets(2), protocol_type(1)=0, data_size(1), command_class(1), command_id(1),
  arguments(80), crc(1), reserved(1)=0. **CRC = XOR of bytes 2..87**, stored at byte 88.
- **Commands (standard/non-extended matrix, which the 2014 BW Chroma uses):**
  - Set custom frame row: class `0x03`, cmd `0x0B`, args `[0xFF, row, start_col, stop_col, RGB×N]`.
  - Show custom frame: class `0x03`, cmd `0x0A`, args `[0x05 (MATRIX_EFFECT_CUSTOMFRAME), 0x00]`.
  - Effects via class `0x03` cmd `0x0A`: `0x00` off, `0x01` wave, `0x02` reactive,
    `0x03` breathing, `0x04` spectrum, `0x06` static+RGB.
  - Brightness: class `0x03`, cmd `0x03`, args `[VARSTORE=0x01, led_id, 0..255]`.
  - Device mode (driver mode enables custom frames): class `0x00`, cmd `0x04`.
- **Matrix:** 6 rows × 22 columns (OpenRazer device metadata for PID 0x0203).
- **Interface note:** `wIndex=0x02` targets the keyboard's third HID interface (macro/control).
  With pyusb we detach the kernel driver + claim **only interface 2** — interfaces 0/1 (the
  actual key input) stay bound to `usbhid`, so evdev input keeps flowing.
- pyusb runs anywhere libusb does — no ARM64 concerns, no kernel module, no daemon.

### Decision

**Primary: direct USB control via pyusb** (`lighting/razer_hid.py`) — no DKMS fragility, no
kernel-update breakage, no daemon, and we only need one known device's protocol, which is
thoroughly documented and mirrored by several working open-source implementations.
**Fallback: OpenRazer** (`lighting/openrazer_backend.py`) — if the direct backend misbehaves
on real hardware, OpenRazer's daemon API is a drop-in behind our `LightingBackend` interface;
install path and DKMS caveats documented in README troubleshooting.
**Dev: mock backend** that renders the LED matrix to the console/log.

---

## 2. Exclusive keyboard capture

- `python-evdev`'s `InputDevice.grab()` issues **`EVIOCGRAB`**, giving the process exclusive
  access: grabbed events reach *only* our fd — nothing propagates to the console keyboard
  handler, so **no VT switching (Ctrl+Alt+F2), no SysRq, no Ctrl+Alt+Del**
  ([python-evdev tutorial](https://python-evdev.readthedocs.io/en/latest/tutorial.html),
  [whizse/exclusive-keyboard-access](https://github.com/whizse/exclusive-keyboard-access) —
  a purpose-built proof of concept for exactly this).
- The BlackWidow Chroma exposes **multiple event nodes** (main keys + media/macro keys on the
  second HID interface). We must grab **every** event device that advertises keyboard keys,
  not just the first — otherwise media keys leak to the console.
- Belt and braces (documented in install): `kernel.sysrq=0` sysctl, and getty removed from
  tty1 (§4), so even an ungrabbed keystroke would land on a dead console.
- Permissions: the app runs as a **root systemd service** (simplest correct choice for a
  single-purpose appliance: evdev grab, DRM master, and USB control transfers all need
  elevated access; a udev rule + groups dance buys nothing here since the whole OS is ours).

**Decision:** `evdev` backend grabs all keyboard-capable event nodes with `EVIOCGRAB`; runs as
root; sysrq disabled; SDL's own keyboard path is unused on the Pi (SDL sees no input because
evdev owns it — we feed events into the loop ourselves).

---

## 3. Kiosk rendering without a desktop

- On Lite (no X/Wayland), SDL2's **KMSDRM** driver is the supported path; the legacy `rpi`/
  framebuffer drivers are gone from modern SDL
  ([Pi forums t=352136](https://forums.raspberrypi.com/viewtopic.php?t=352136)).
- Distro `python3-pygame` on Lite has a history of shipping SDL builds that fall back to the
  useless `offscreen` driver ([pygame#4061](https://github.com/pygame/pygame/issues/4061)).
  The reliable recipe on Bookworm/Trixie Lite: **pip-installed pygame-ce in a venv** (bundles
  a current SDL2 with KMSDRM enabled in its manylinux aarch64 wheels) plus the Mesa EGL/GBM
  runtime — `libegl-dev` pulls the needed DRM interface on Lite
  ([Pi forums t=367519](https://forums.raspberrypi.com/viewtopic.php?t=367519),
  [Bookworm KMS/DRM walkthrough](https://dontpressthat.wordpress.com/2025/09/20/bookworm-drm/)).
- `SDL_VIDEODRIVER=kmsdrm`; HDMI is typically DRM device index 0 (set
  `SDL_KMSDRM_DEVICE_INDEX` if a second card exists —
  [Pi forums t=365776](https://forums.raspberrypi.com/viewtopic.php?t=365776)).
- Alternative considered: **Cage** (Wayland kiosk compositor). It adds a compositor, seat
  manager, and XDG plumbing between us and the display for zero benefit — SDL would still do
  the drawing. More processes to harden, more failure modes.
- 60 fps: 1080p60 alpha-blended blits are comfortable on Pi 4/5 GPUs via KMSDRM/GLES; our
  engine caps particle counts and degrades gracefully (fewer particles, simpler trails) if
  frame time exceeds budget.

**Decision:** pygame-ce (pip, venv) directly on **KMSDRM**, fullscreen at the display's native
mode, hidden cursor, no compositor. `kmstest`/`modetest` listed in VERIFY.md as a first-boot
sanity check.

---

## 4. Boot hardening

Sources: [Linux Junkies Pi kiosk guide](https://linuxjunkies.org/guides/raspberry-pi-kiosk-mode),
[Andy Gock kiosk HOW-TO](https://gock.net/blog/2020/raspberry-pi-kiosk),
[Pi forums splash thread](https://forums.raspberrypi.com/viewtopic.php?t=355814),
[raspi-config overlayfs issue #279](https://github.com/rpi-distro/raspi-config/issues/279),
[raspberrypi/linux#6968](https://github.com/raspberrypi/linux/issues/6968).

- **systemd unit:** `lilypad.service`, `Restart=always`, `RestartSec=2`, ordered
  `After=systemd-user-sessions.service`, `Conflicts=getty@tty1.service` +
  `systemctl disable getty@tty1` → no login prompt ever owns the console.
- **Quiet boot** (`/boot/firmware/cmdline.txt`): `quiet loglevel=1 logo.nologo
  vt.global_cursor_default=0 consoleblank=0 plymouth.ignore-serial-consoles`.
- **SysRq off:** `kernel.sysrq=0` via `/etc/sysctl.d/`.
- **Power-pull survival:** raspi-config's overlay file system
  (`raspi-config nonint do_overlayfs 0`) makes the root fs read-only with a RAM overlay —
  ideal once the unit is verified. Caveats: must be disabled to update software, and there is
  a known failure when extra partitions exist on the SD card (raspberrypi/linux#6968) — we
  use a stock 2-partition image, so not affected. install.sh prints the enable/disable
  commands rather than enabling it blindly (first boots need read-write for logs/tweaks).

**Decision:** all of the above in `install.sh` (idempotent), overlayfs as a documented
opt-in final step after VERIFY.md passes.

---

## 5. Power draw — is a powered hub required?

No authoritative mA figure for the BlackWidow Chroma is published, but the engineering
bounds are solid:

- The original BlackWidow Chroma (RZ03-0122x) is a **single-cable USB 2.0 device with no
  passthrough port** ([Razer support](https://mysupport.razer.com/app/answers/detail/a_id/3651/~/razer-blackwidow-chroma-%7C-rz03-0122x-support-%26-faqs)),
  so by USB 2.0 spec it cannot legitimately draw more than **500 mA** — and full-RGB
  keyboards of this class sit near that ceiling.
- **Pi 4B:** 1.2 A total USB budget — 500 mA fits with >2× margin
  ([Pi USB documentation](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/usb-bus-on-raspberry-pi.adoc)).
- **Pi 5:** USB budget is **600 mA by default**, raised to **1.6 A only when a 5 V/5 A
  (27 W) USB-PD supply is negotiated** (or `usb_max_current_enable=1` is forced)
  ([Pi power documentation](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/power-supplies.adoc)).
  A near-500 mA keyboard on a 600 mA budget is margin-free — **the official 27 W PSU is
  therefore a hard BOM requirement for Pi 5**, not an upsell.

**Decision:** No powered hub in the base BOM. Pi 5 **must** pair with the official 27 W USB-C
PD supply (Pi 4 with the official 15 W). A powered hub is listed as a $15 contingency only if
VERIFY.md's full-brightness stress step shows disconnects/flicker.

---

## 6. Prior art (inspiration only)

- **[BabySmash](https://github.com/shanselman/babysmash)** (Scott Hanselman, WPF/Windows) —
  the canonical "every key does something delightful" app; blocks OS shortcuts.
- **[bambam](https://github.com/porridge/bambam)** (Python/pygame, Linux) — keyboard/mouse
  masher for toddlers; closest architectural cousin (pygame loop, per-key sounds/images).
- **[babytux](https://github.com/jaredly/babytux)** — BabySmash-inspired Linux variant.

Takeaways adopted: letters get spoken + shown huge; variety per key matters more than depth;
lock-down is the hard part and deserves first-class engineering. **All code and assets in this
repo are original**; sounds are procedurally synthesized or generated with espeak-ng — no
copyrighted characters or assets.

---

## Decision summary

| Topic | Choice | Fallback |
|---|---|---|
| OS | Raspberry Pi OS Lite 64-bit (Trixie, Debian 13) | Bookworm Lite 64-bit |
| RGB control | Direct USB (pyusb, OpenRazer wire protocol) | OpenRazer DKMS+daemon |
| Input | python-evdev + EVIOCGRAB on all keyboard nodes, root service | — |
| Rendering | pygame-ce (pip venv) on SDL KMSDRM, no compositor | Cage/Wayland (rejected: complexity) |
| Boot | systemd + getty@tty1 off + quiet cmdline + sysrq=0 | — |
| Resilience | raspi-config overlayfs (opt-in after verification) | — |
| Power | Pi 5 + official 27 W PSU (1.6 A USB budget); no hub | Powered hub contingency |
