"""On-demand frame dump: let a remote operator see what the app is drawing.

``kill -USR1 <pid>`` sets a flag; the main loop calls :func:`service_request`
right after ``pygame.display.flip()`` and the frame just presented is written
to ``<dir>/frame.png`` (``/run/lilypad`` in kiosk mode, the system temp dir in
dev mode). The handler does nothing but set a flag, and the save can never
raise or stall the kiosk beyond one PNG encode.
"""

from __future__ import annotations

import logging
import os
import signal
import tempfile
from pathlib import Path

log = logging.getLogger("lilypad")

KIOSK_DIR = Path("/run/lilypad")
FRAME_NAME = "frame.png"

_requested = False


def _request(_signum=None, _frame=None) -> None:
    global _requested
    _requested = True


def install() -> bool:
    """Route SIGUSR1 to the flag. False where the platform has no SIGUSR1."""
    global _requested
    _requested = False
    if not hasattr(signal, "SIGUSR1"):
        return False
    signal.signal(signal.SIGUSR1, _request)
    return True


def frame_dir(kiosk: bool) -> Path:
    return KIOSK_DIR if kiosk else Path(tempfile.gettempdir())


def dump_frame(surface, directory: Path) -> Path | None:
    """Atomically write ``surface`` to ``directory/frame.png``.

    Returns the path, or None (after a warning) on any failure. Never raises.
    """
    try:
        import pygame

        directory = Path(directory)
        os.makedirs(directory, exist_ok=True)
        final = directory / FRAME_NAME
        tmp = directory / (FRAME_NAME + ".tmp")
        # A file object plus namehint: the ".tmp" suffix must not pick the format.
        with open(tmp, "wb") as fh:
            pygame.image.save(surface, fh, FRAME_NAME)
        os.replace(tmp, final)
        log.info("frame dumped to %s", final)
        return final
    except Exception as exc:  # noqa: BLE001 - a snapshot must never hurt the kiosk
        log.warning("frame dump failed: %s", exc)
        return None


def service_request(surface, kiosk: bool) -> Path | None:
    """If SIGUSR1 arrived since the last call, dump ``surface``. Cheap otherwise."""
    global _requested
    if not _requested:
        return None
    _requested = False
    return dump_frame(surface, frame_dir(kiosk))
