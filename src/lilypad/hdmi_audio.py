"""Point ALSA at whichever HDMI port actually has a monitor. Runs at boot.

Two independent problems make a fixed ``/etc/asound.conf`` the wrong answer:

**The port can be wrong.** On the Pi 5 used for bring-up, the near HDMI port
(HDMI-A-1, closest to USB-C) has dead DDC lines: it reports ``connected``,
because hot-plug detect is a separate pin, but reads 0 bytes of EDID. With no
CEA extension block the sink advertises no audio capability, ``vc4-hdmi``
refuses to open a PCM, and ALSA returns error 524. The far port works, and it
is ALSA **card 1**, not the default card 0 — so audio stays silent until
something says otherwise.

**The board can be wrong.** This card is developed and tested on one Pi and
then swapped into the Pi 5 in the bedroom. HDMI ALSA card indices are a
property of the board, not the card: a Pi 3 exposes a single ``bcm2835 HDMI``,
a Pi 4/5 exposes ``vc4hdmi0`` and ``vc4hdmi1``. An index written by install.sh
on one board is a guess on the next one.

So this is a boot-time oneshot rather than an installer step. It costs
milliseconds, it is idempotent, and it composes with the read-only overlay for
free: under ``overlayroot`` the write lands in tmpfs and is discarded at
shutdown, which is exactly right — it gets re-derived on the next boot anyway.

    python -m lilypad.hdmi_audio            # write /etc/asound.conf
    python -m lilypad.hdmi_audio --dry-run  # print what it would do
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .doctor import Connector, _hdmi_alsa_cards, find_connectors

log = logging.getLogger("lilypad.hdmi_audio")

ASOUND_CONF = "etc/asound.conf"

#: Marker so we only ever rewrite our own file. A hand-written asound.conf is
#: someone making a deliberate choice, and stomping it would be rude.
HEADER = "# Written by lilypad-audio.service — regenerated at every boot."

TEMPLATE = """{header}
# Live HDMI output: {connector} -> ALSA card {index} ({name})
defaults.pcm.card {index}
defaults.ctl.card {index}
"""


def alsa_card_for(connector: Connector, cards: list[tuple[int, str]]) -> int | None:
    """Match a DRM connector to its ALSA card.

    One HDMI sink is unambiguous — that is the Pi 3 / Zero 2 W case, and also a
    Pi 4/5 with only one HDMI driver instance bound.

    With two, match on the trailing digit: the kernel names them ``vc4hdmi0``
    and ``vc4hdmi1`` against ``HDMI-A-1`` and ``HDMI-A-2``, i.e. offset by one.
    Deliberately *not* matched via ``/proc/asound/card*/eld`` — that keeps a
    stale ELD after a cable is unplugged, so a populated ``monitor_name`` there
    is not proof the port is live.
    """
    if not cards:
        return None
    if len(cards) == 1:
        return cards[0][0]

    m = re.search(r"(\d+)$", connector.name)
    if not m:
        return cards[0][0]
    want = int(m.group(1)) - 1           # HDMI-A-1 -> vc4hdmi0

    for index, name in cards:
        suffix = re.search(r"(\d+)$", name)
        if suffix and int(suffix.group(1)) == want:
            return index
    return cards[0][0]


def desired_conf(root: Path = Path("/")) -> tuple[str, str] | None:
    """The asound.conf this machine should have, or ``None`` to leave it alone.

    Returns ``(contents, human_summary)``. ``None`` means we could not tell —
    no live output or no HDMI sink — and in that case doing nothing is strictly
    better than guessing, because a wrong pin is silent audio rather than
    default audio.
    """
    live = [c for c in find_connectors(root) if c.live and c.name.startswith("HDMI")]
    if not live:
        return None
    cards = _hdmi_alsa_cards(root)
    index = alsa_card_for(live[0], cards)
    if index is None:
        return None
    name = next((n for i, n in cards if i == index), "?")
    summary = f"{live[0].name} -> ALSA card {index} ({name})"
    return TEMPLATE.format(header=HEADER, connector=live[0].name,
                           index=index, name=name), summary


def apply(root: Path = Path("/"), dry_run: bool = False) -> str:
    """Write ``/etc/asound.conf`` if it should change. Returns what happened."""
    path = root / ASOUND_CONF
    existing = ""
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""

    if existing and HEADER not in existing:
        return f"leaving hand-written {path} alone"

    wanted = desired_conf(root)
    if wanted is None:
        return "no live HDMI output with an audio sink — leaving ALSA defaults"

    contents, summary = wanted
    if existing == contents:
        return f"already correct: {summary}"
    if dry_run:
        return f"would write {path}: {summary}"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".conf.tmp")
    tmp.write_text(contents, encoding="utf-8")
    tmp.replace(path)                      # atomic; never a half-written config
    return f"wrote {path}: {summary}"


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="lilypad.hdmi_audio",
        description="Point ALSA at the HDMI port that has a monitor")
    parser.add_argument("--root", default="/", help="filesystem root (testing)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log.info("%s", apply(Path(args.root), dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
