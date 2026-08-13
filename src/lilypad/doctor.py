"""On-device diagnostics — the four bring-up faults, in one command.

The first real bring-up (CHANGELOG, 2026-08-12) lost most of a session to four
faults that all *look* like something else:

* a dead-DDC HDMI port reads as "no audio + stuck at 1024x768", not as a video
  fault, because hot-plug detect is a separate pin from the DDC lines;
* a regulatory-domain split reads as "wrong Wi-Fi password";
* a 0-byte ``authorized_keys`` reads as "SSH key auth is broken" while every
  permission check looks right;
* and the Trixie read-only overlay is invisible to the ``boot=overlay`` grep
  that every older guide tells you to run.

Each one has a single command that identifies it conclusively. This module is
those commands, run together, with the remedy printed next to the finding:

    sudo /opt/lilypad/venv/bin/python -m lilypad --doctor

Nothing here touches the display, the keyboard or the audio device, so it is
safe to run while the service is up.

Everything reads through an injected ``root`` and an injected command runner,
so the whole module is testable on a dev box with no Pi attached — which is the
only reason these checks have tests at all.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

#: A check outcome. ``skip`` means "this machine isn't a Pi / the file isn't
#: there", which is not a failure — the doctor runs on a dev box too.
PASS, FAIL, WARN, SKIP = "pass", "fail", "warn", "skip"

_MARK = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN", SKIP: "skip"}


@dataclass(frozen=True)
class Check:
    """One diagnostic result.

    ``remedy`` is the thing a tired parent actually needs at 11pm: what to type
    next. It is only meaningful for FAIL/WARN and is omitted from the report
    otherwise.
    """

    name: str
    status: str
    detail: str
    remedy: str = ""


Runner = Callable[[Sequence[str]], "str | None"]


def shell_runner(cmd: Sequence[str]) -> str | None:
    """Run a command, returning stdout or ``None`` if it can't be run.

    A missing binary is not an error here — ``vcgencmd`` doesn't exist on a dev
    box and ``iw`` may not be installed on a wired-only Pi. Both cases become a
    ``skip``, never a false alarm.
    """
    try:
        proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


# --------------------------------------------------------------------------
# Fault 2 — HDMI EDID, the ALSA card, and the pinned mode
# --------------------------------------------------------------------------

#: A full EDID block is 128 bytes; 256 when a CEA extension block (the one that
#: advertises audio) is present. Anything under 128 is a broken read, not a
#: modest monitor.
EDID_BLOCK = 128


@dataclass(frozen=True)
class Connector:
    """A DRM connector as the kernel sees it."""

    name: str               # e.g. "HDMI-A-1"
    card: str               # e.g. "card1"
    status: str             # "connected" / "disconnected"
    edid_bytes: int

    @property
    def live(self) -> bool:
        """Connected *and* talking. The whole point of fault 2 is that these
        two are independent: HPD is a pin, EDID comes over the DDC lines."""
        return self.status == "connected" and self.edid_bytes >= EDID_BLOCK


def find_connectors(root: Path = Path("/")) -> list[Connector]:
    """Enumerate DRM connectors under ``sys/class/drm``.

    Sorted by name so HDMI-A-1 is always reported before HDMI-A-2 — the report
    reads as "the near port, then the far port", matching the physical board.
    """
    drm = root / "sys" / "class" / "drm"
    if not drm.is_dir():
        return []
    out: list[Connector] = []
    for entry in sorted(drm.iterdir()):
        # Directory names look like "card1-HDMI-A-1"; the plain "card1" node
        # and the "renderD128" nodes have no connector suffix.
        if not entry.is_dir() or "-" not in entry.name:
            continue
        card, _, connector = entry.name.partition("-")
        if not card.startswith("card"):
            continue
        out.append(Connector(
            name=connector,
            card=card,
            status=_read_text(entry / "status").strip() or "unknown",
            edid_bytes=_read_size(entry / "edid"),
        ))
    return out


def check_hdmi_edid(root: Path = Path("/")) -> Check:
    """Fault 2's one-command diagnosis, generalised over every connector.

    Zero bytes on a *connected* port is the signature: video works at generic
    fallback modes, so nothing looks broken, but the sink advertised no audio
    capability and ALSA will return error 524 on every open.
    """
    connectors = [c for c in find_connectors(root) if c.name.startswith("HDMI")]
    if not connectors:
        return Check("HDMI EDID", SKIP, "no HDMI connectors in sysfs (not a Pi?)")

    live = [c for c in connectors if c.live]
    summary = ", ".join(f"{c.name}={c.edid_bytes}B/{c.status}" for c in connectors)

    if live:
        return Check("HDMI EDID", PASS,
                     f"{live[0].name} returned {live[0].edid_bytes} bytes ({summary})")

    mute = [c for c in connectors if c.status == "connected" and c.edid_bytes == 0]
    if mute:
        others = [c.name for c in connectors if c not in mute]
        return Check(
            "HDMI EDID", FAIL,
            f"{mute[0].name} reports connected but read 0 bytes of EDID ({summary})",
            "Dead DDC lines on this port — video still works at fallback modes, "
            "but there is no audio and no native resolution. Move the cable to "
            + (f"{others[0]}" if others else "the other HDMI port")
            + " and reboot (SDL inherits the mode the CRTC negotiated at boot, "
              "so restarting the service alone will not lift it off 1024x768).")

    return Check("HDMI EDID", WARN, f"no connected HDMI output ({summary})",
                 "Monitor off, asleep, or on another input. The app waits for a "
                 "display on its own, so this is only a problem if it persists.")


def _hdmi_alsa_cards(root: Path = Path("/")) -> list[tuple[int, str]]:
    """(index, name) for every ALSA card that looks like an HDMI sink.

    ``/proc/asound/cards`` lays each card out over two lines::

        1 [vc4hdmi1       ]: vc4-hdmi - vc4-hdmi-1
                             vc4-hdmi-1
    """
    text = _read_text(root / "proc" / "asound" / "cards")
    found: list[tuple[int, str]] = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+\[([^\]]*)\]", line)
        if m:
            index, name = int(m.group(1)), m.group(2).strip()
            if "hdmi" in name.lower() or "hdmi" in line.lower():
                found.append((index, name))
    return found


def _configured_alsa_card(root: Path = Path("/")) -> int | None:
    """The card index ``/etc/asound.conf`` pins, if it pins one."""
    m = re.search(r"^\s*defaults\.pcm\.card\s+(\d+)",
                  _read_text(root / "etc" / "asound.conf"), re.MULTILINE)
    return int(m.group(1)) if m else None


def check_alsa_card(root: Path = Path("/")) -> Check:
    """Is the default ALSA card the HDMI port that actually has a monitor?

    On the far port the sink is card 1, not the default card 0, so audio is
    silent until ``/etc/asound.conf`` says so. This is the second half of
    fault 2 and the half that survives a reboot.
    """
    cards = _hdmi_alsa_cards(root)
    if not cards:
        return Check("ALSA default card", SKIP, "no HDMI ALSA cards (not a Pi?)")

    configured = _configured_alsa_card(root)
    listed = ", ".join(f"card {i} ({n})" for i, n in cards)

    if configured is None:
        if len(cards) == 1 and cards[0][0] == 0:
            return Check("ALSA default card", PASS,
                         f"only HDMI sink is card 0; the ALSA default is correct ({listed})")
        return Check(
            "ALSA default card", WARN,
            f"no /etc/asound.conf, and the HDMI sinks are {listed}",
            "ALSA will use card 0. If the live monitor is on a different card "
            "there is no sound. install.sh writes this file; re-run it, or set "
            "defaults.pcm.card / defaults.ctl.card by hand.")

    if any(index == configured for index, _ in cards):
        return Check("ALSA default card", PASS,
                     f"/etc/asound.conf pins card {configured} ({listed})")
    return Check(
        "ALSA default card", FAIL,
        f"/etc/asound.conf pins card {configured}, which is not an HDMI sink ({listed})",
        f"Point it at one of: {listed}. Re-running install.sh does this "
        "automatically from the connector that returned EDID.")


def check_mode_pinned(root: Path = Path("/")) -> Check:
    """Is ``video=`` pinned, and pinned to the port that has the monitor?

    Pinning stops a sleeping monitor from dropping hot-plug detect and leaving
    the Pi with no display — but pinning the *wrong* connector is worse than
    not pinning at all, which is exactly what following the old HDMI0-only
    advice produced on a board whose near port has dead DDC lines.
    """
    cmdline_path = root / "boot" / "firmware" / "cmdline.txt"
    text = _read_text(cmdline_path)
    if not text:
        return Check("Forced HDMI mode", SKIP, "no /boot/firmware/cmdline.txt (not a Pi?)")

    live = [c.name for c in find_connectors(root) if c.live]
    m = re.search(r"video=([A-Za-z0-9\-]+):(\S+)", text)

    if not m:
        target = live[0] if live else "HDMI-A-1"
        return Check(
            "Forced HDMI mode", WARN, "no video= parameter in cmdline.txt",
            f"Optional but recommended before enabling overlayfs: append "
            f"video={target}:1920x1080@60D to the single line in cmdline.txt "
            "and reboot, so a sleeping monitor can't take the display away.")

    pinned, mode = m.group(1), m.group(2)
    if live and pinned not in live:
        return Check(
            "Forced HDMI mode", FAIL,
            f"cmdline.txt pins video={pinned}:{mode}, but the live output is "
            f"{', '.join(live)}",
            f"Retarget it: video={live[0]}:{mode}. A mode forced onto a "
            "connector with no monitor leaves the Pi driving nothing.")
    return Check("Forced HDMI mode", PASS, f"video={pinned}:{mode}")


# --------------------------------------------------------------------------
# Fault 3 — the regulatory-domain split
# --------------------------------------------------------------------------

def check_wifi_regdom(runner: Runner = shell_runner) -> Check:
    """Global vs phy0 country mismatch — reads as a wrong Wi-Fi password.

    ``brcmfmac`` is self-managed and reads its country at *load* time, so
    ``iw phy phy0 set country US`` on a running system achieves nothing. The
    fix is a reboot, which is why this is worth surfacing before anyone starts
    retyping credentials.
    """
    out = runner(["iw", "reg", "get"])
    if out is None:
        return Check("Wi-Fi regulatory domain", SKIP, "iw unavailable")

    glob = re.search(r"global\s*\ncountry\s+([A-Z0-9]{2})", out, re.IGNORECASE)
    phy = re.search(r"phy#0\s*\ncountry\s+([A-Z0-9]{2})", out, re.IGNORECASE)
    if not glob and not phy:
        return Check("Wi-Fi regulatory domain", SKIP, "could not parse `iw reg get`")

    g = glob.group(1).upper() if glob else "?"
    p = phy.group(1).upper() if phy else g

    if p == "00":
        return Check(
            "Wi-Fi regulatory domain", FAIL,
            f"phy#0 country is 00 (DFS-UNSET) while global is {g}",
            "Regdom 00 makes 5 GHz unusable, so a 5/6 GHz-only router is "
            "invisible and `nmcli device wifi list` returns nothing — it looks "
            "exactly like a wrong password. Imager already writes "
            "cfg80211.ieee80211_regdom=US into cmdline.txt; a *cold boot* "
            "applies it. Setting it on a running system does nothing.")
    if glob and phy and g != p:
        return Check("Wi-Fi regulatory domain", WARN,
                     f"global country {g} but phy#0 is {p}",
                     "Reboot so the driver reloads its country at init.")
    return Check("Wi-Fi regulatory domain", PASS, f"country {p}")


# --------------------------------------------------------------------------
# Fault 4 — the silently empty authorized_keys
# --------------------------------------------------------------------------

def check_authorized_keys(path: Path) -> Check:
    """Non-empty and shaped like a key.

    Pushing a key over a pipe from PowerShell creates the file with correct
    600/700 permissions and no content, so every permission check passes and
    key auth still fails. ``ls`` shows a file; only the size gives it away.
    """
    if not path.exists():
        return Check("SSH authorized_keys", SKIP, f"{path} not present")
    size = path.stat().st_size
    if size == 0:
        return Check(
            "SSH authorized_keys", FAIL, f"{path} is 0 bytes",
            "The push produced an empty file — permissions look right and auth "
            "still fails. Re-copy the key and confirm with "
            "`ssh-keygen -lf ~/.ssh/authorized_keys`, comparing the fingerprint "
            "rather than trusting `ls`.")
    keys = [ln for ln in _read_text(path).splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    if not keys:
        return Check("SSH authorized_keys", FAIL,
                     f"{path} has {size} bytes but no key lines",
                     "File contains only blanks or comments. Re-copy the key.")
    return Check("SSH authorized_keys", PASS,
                 f"{len(keys)} key(s), {size} bytes")


# --------------------------------------------------------------------------
# Card-swap awareness
# --------------------------------------------------------------------------
#
# This card is meant to move: it is set up and tested on one Pi and then
# swapped into the Pi 5 that actually lives in the bedroom. Raspberry Pi OS
# handles that part — one image carries a kernel and DTBs for every model — but
# two of the settings below are derived from the *board*, not from the card:
#
#   * connector names (a Pi 5 and a Pi 4 have HDMI-A-1 and HDMI-A-2; a Pi 3 or
#     Zero 2 W has a single HDMI-A-1), so a pinned ``video=`` can point at a
#     connector the new board doesn't have;
#   * the HDMI ALSA card index, which is why /etc/asound.conf is regenerated at
#     every boot rather than written once by install.sh.
#
# So the installer records what it saw, and the doctor notices when the board
# underneath has changed.

STAMP_PATH = "etc/lilypad/hardware.stamp"


def read_model(root: Path = Path("/")) -> str:
    """Board model from the device tree, e.g. 'Raspberry Pi 5 Model B Rev 1.1'."""
    for rel in ("proc/device-tree/model", "sys/firmware/devicetree/base/model"):
        text = _read_text(root / rel).strip("\x00 \t\r\n")
        if text:
            return text
    return ""


def check_model(root: Path = Path("/")) -> Check:
    """Report the board, and flag a 32-bit-only one before anything else fails.

    64-bit Raspberry Pi OS needs a Pi 3 or newer. A Pi 1, 2 or original Zero
    will not boot this card at all, which is worth saying plainly rather than
    letting it look like a corrupt image.
    """
    model = read_model(root)
    if not model:
        return Check("Board model", SKIP, "no device-tree model (not a Pi?)")
    if re.search(r"Pi (Model B|2 Model|Zero(?! 2))", model) or "Pi 1" in model:
        return Check("Board model", FAIL, model,
                     "This board is 32-bit only; Raspberry Pi OS Lite 64-bit "
                     "needs a Pi 3 or newer. Use a Pi 3/4/5 or Zero 2 W for "
                     "testing, or the card will not boot.")
    return Check("Board model", PASS, model)


def write_stamp(root: Path = Path("/")) -> None:
    """Record the board this card was last configured on."""
    path = root / STAMP_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    live = [c.name for c in find_connectors(root) if c.live]
    cards = _hdmi_alsa_cards(root)
    path.write_text(
        f"model={read_model(root)}\n"
        f"connectors={','.join(live)}\n"
        f"alsa={','.join(str(i) for i, _ in cards)}\n",
        encoding="utf-8")


def _read_stamp(root: Path = Path("/")) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _read_text(root / STAMP_PATH).splitlines():
        key, _, value = line.partition("=")
        if key:
            out[key.strip()] = value.strip()
    return out


def check_card_swap(root: Path = Path("/")) -> Check:
    """Did this card move to a different board since it was set up?

    Not a fault in itself — moving the card to the Pi 5 is the plan. It matters
    because a ``video=`` pin written for the old board may name a connector
    this one does not have, and that failure mode is a black screen with no
    error anywhere.
    """
    stamp = _read_stamp(root)
    if not stamp:
        return Check("Card swap", SKIP, "no hardware stamp (install.sh writes it)")
    was, now = stamp.get("model", ""), read_model(root)
    if not now:
        return Check("Card swap", SKIP, "no device-tree model to compare")
    if was == now:
        return Check("Card swap", PASS, f"same board as last install ({now})")

    live = [c.name for c in find_connectors(root) if c.live]
    old_connectors = stamp.get("connectors", "")
    return Check(
        "Card swap", WARN,
        f"this card was set up on {was!r} and is now in {now!r}",
        "Expected if you have just moved it to the Pi 5. Two things do not "
        f"travel with the card: the video= pin in cmdline.txt (was {old_connectors or 'unset'}, "
        f"this board has {', '.join(live) or 'no live output'}) and the HDMI ALSA "
        "card index. The ALSA side is regenerated at every boot by "
        "lilypad-audio.service, so it fixes itself; check the video= line "
        "below, then re-run install.sh to update this stamp.")


# --------------------------------------------------------------------------
# Deployment state
# --------------------------------------------------------------------------

def check_overlay(root: Path = Path("/")) -> Check:
    """Read-only root overlay, detected the way that actually works on Trixie.

    ``raspi-config nonint do_overlayfs 0`` installs Debian's ``overlayroot``
    and prepends ``overlayroot=tmpfs`` to cmdline.txt — it does *not* write
    ``boot=overlay``, so grepping for that string reports "off" on a system
    where the overlay is very much on. Read the mount instead.
    """
    mounts = _read_text(root / "proc" / "mounts")
    if not mounts:
        return Check("Read-only root overlay", SKIP, "no /proc/mounts")
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "/":
            if parts[2] == "overlay":
                return Check("Read-only root overlay", PASS, "/ is mounted as overlay")
            return Check(
                "Read-only root overlay", WARN, f"/ is {parts[2]}, not overlay",
                "Optional, but it makes the card survive a toddler pulling the "
                "power: sudo raspi-config nonint do_overlayfs 0, then reboot. "
                "Disable it again before running install.sh updates.")
    return Check("Read-only root overlay", SKIP, "no / entry in /proc/mounts")


_THROTTLE_BITS = {
    0: "under-voltage now",
    1: "ARM frequency capped now",
    2: "currently throttled",
    3: "soft temperature limit now",
    16: "under-voltage has occurred",
    17: "ARM frequency capping has occurred",
    18: "throttling has occurred",
    19: "soft temperature limit has occurred",
}


def check_power(runner: Runner = shell_runner) -> Check:
    """``vcgencmd get_throttled`` — under-voltage corrupts cards and freezes apps."""
    out = runner(["vcgencmd", "get_throttled"])
    if out is None:
        return Check("Power / throttling", SKIP, "vcgencmd unavailable")
    m = re.search(r"throttled=0x([0-9a-fA-F]+)", out)
    if not m:
        return Check("Power / throttling", SKIP, f"unparsed: {out.strip()}")
    bits = int(m.group(1), 16)
    if bits == 0:
        return Check("Power / throttling", PASS, "throttled=0x0")
    flags = [text for bit, text in _THROTTLE_BITS.items() if bits & (1 << bit)]
    live = bits & 0xF
    return Check(
        "Power / throttling", FAIL if live else WARN,
        f"throttled=0x{bits:x} — {'; '.join(flags)}",
        "Use the official 27 W USB-C PSU and a short, thick cable. Under-voltage "
        "corrupts SD cards and stalls the app in ways that look like software bugs.")


def check_service(root: Path = Path("/")) -> Check:
    """Is the unit installed and enabled? A missing symlink means no autostart."""
    unit = root / "etc" / "systemd" / "system" / "lilypad.service"
    if not unit.is_file():
        return Check("lilypad.service", SKIP, "unit not installed (not a Pi?)")
    wants = root / "etc" / "systemd" / "system" / "multi-user.target.wants" / "lilypad.service"
    if wants.exists() or wants.is_symlink():
        return Check("lilypad.service", PASS, "installed and enabled")
    return Check("lilypad.service", FAIL, "installed but not enabled",
                 "sudo systemctl enable lilypad.service — without this the "
                 "playground does not come back after a power pull.")


def check_sounds(root: Path = Path("/"), app_dir: str = "/opt/lilypad") -> Check:
    """The generated cues must exist on disk; the app has no fallback tone."""
    sounds = root / app_dir.lstrip("/") / "sounds"
    if not sounds.is_dir():
        return Check("Generated sounds", SKIP, f"{sounds} not present (not a Pi?)")
    wavs = list(sounds.glob("*.wav"))
    if not wavs:
        return Check("Generated sounds", FAIL, f"{sounds} is empty",
                     "Re-run phase 3 of install.sh: "
                     "sudo /opt/lilypad/venv/bin/python -m lilypad.audio.synth "
                     "/opt/lilypad/sounds")
    return Check("Generated sounds", PASS, f"{len(wavs)} cues in {sounds}")


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.status == WARN]

    @property
    def ok(self) -> bool:
        return not self.failed


def run_all(root: Path = Path("/"), runner: Runner = shell_runner,
            home: Path | None = None) -> Report:
    """Every check, in the order a bring-up actually hits them."""
    keys = (home or root / "home" / "pi") / ".ssh" / "authorized_keys"
    return Report([
        check_model(root),
        check_card_swap(root),
        check_hdmi_edid(root),
        check_alsa_card(root),
        check_mode_pinned(root),
        check_wifi_regdom(runner),
        check_authorized_keys(keys),
        check_overlay(root),
        check_power(runner),
        check_service(root),
        check_sounds(root),
    ])


def format_report(report: Report, width: int = 78) -> str:
    """Human-readable, remedies indented under the findings that need them."""
    lines = ["", "Lily Pad doctor", "=" * width]
    for check in report.checks:
        lines.append(f"[{_MARK[check.status]:>4}] {check.name}: {check.detail}")
        if check.remedy and check.status in (FAIL, WARN):
            lines.extend(f"        {ln}" for ln in _wrap(check.remedy, width - 8))
    lines.append("=" * width)
    if report.failed:
        lines.append(f"{len(report.failed)} fault(s) need attention"
                     + (f", {len(report.warned)} warning(s)" if report.warned else ""))
    elif report.warned:
        lines.append(f"No faults; {len(report.warned)} warning(s) worth a look")
    else:
        lines.append("All checks passed")
    return "\n".join(lines) + "\n"


def _wrap(text: str, width: int) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width) or [""]


def _read_text(path: Path) -> str:
    """Sysfs reads race with hot-plug and can raise; a missing file is normal."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _read_size(path: Path) -> int:
    """Size of a sysfs file — which ``stat`` reports as 0, so it must be read."""
    try:
        return len(path.read_bytes())
    except (OSError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    """``python -m lilypad --doctor``. Exit 1 if anything failed."""
    import argparse
    parser = argparse.ArgumentParser(prog="lilypad --doctor",
                                     description="Lily Pad on-device diagnostics")
    parser.add_argument("--root", default="/", help="filesystem root (testing)")
    args = parser.parse_args(argv)
    report = run_all(Path(args.root))
    print(format_report(report), end="")
    return 1 if report.failed else 0
