"""Pi input backend: python-evdev with an exclusive EVIOCGRAB grab.

Grabs EVERY event device that looks like a keyboard (the BlackWidow Chroma
exposes its media/macro keys on a second HID interface with its own event
node), so no keystroke of any kind can reach the console — no VT switching,
no SysRq, no Ctrl+Alt+Del. See RESEARCH.md §2.

Import of ``evdev`` is deferred so this module can be imported (for tests)
on non-Linux machines.
"""

from __future__ import annotations

import logging
import select
import time

from .base import KeyEvent

log = logging.getLogger(__name__)


class EvdevInputBackend:
    def __init__(self, name_filter: str | None = None) -> None:
        """``name_filter``: case-insensitive substring to select devices
        (e.g. "razer"). None grabs all keyboard-capable devices — the safe
        default for a locked-down appliance."""
        self._name_filter = name_filter
        self._devices: list = []
        self._held: set[str] = set()
        self.quit_requested = False  # parity with the SDL backend

    def start(self) -> None:
        import evdev
        from evdev import ecodes

        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            caps = dev.capabilities().get(ecodes.EV_KEY, [])
            is_keyboard = ecodes.KEY_A in caps or ecodes.KEY_PLAYPAUSE in caps
            if not is_keyboard:
                dev.close()
                continue
            if self._name_filter and self._name_filter.lower() not in dev.name.lower():
                dev.close()
                continue
            try:
                dev.grab()  # EVIOCGRAB — exclusive access
            except OSError as exc:
                log.warning("could not grab %s (%s): %s", path, dev.name, exc)
                dev.close()
                continue
            log.info("grabbed %s (%s)", path, dev.name)
            self._devices.append(dev)

        if not self._devices:
            raise RuntimeError(
                "no keyboard event devices could be grabbed — is the keyboard "
                "plugged in, and is the service running as root?"
            )

    def poll(self) -> list[KeyEvent]:
        from evdev import ecodes

        events: list[KeyEvent] = []
        if not self._devices:
            return events
        readable, _, _ = select.select(self._devices, [], [], 0)
        now = time.monotonic()
        for dev in readable:
            try:
                for ev in dev.read():
                    if ev.type != ecodes.EV_KEY:
                        continue
                    if ev.value == 2:  # key repeat — mapper ignores anyway
                        continue
                    keyname = ecodes.KEY.get(ev.code)
                    if keyname is None:
                        continue
                    if isinstance(keyname, list):  # some codes alias
                        keyname = keyname[0]
                    name = keyname.removeprefix("KEY_")
                    pressed = ev.value == 1
                    if pressed:
                        self._held.add(name)
                    else:
                        self._held.discard(name)
                    events.append(KeyEvent(name=name, pressed=pressed, ts=now))
            except OSError as exc:
                log.warning("device %s vanished: %s", dev.path, exc)
                self._drop(dev)
        return events

    def held_keys(self) -> frozenset[str]:
        return frozenset(self._held)

    def _drop(self, dev) -> None:
        if dev in self._devices:
            self._devices.remove(dev)
        try:
            dev.close()
        except OSError:
            pass

    def stop(self) -> None:
        for dev in self._devices:
            try:
                dev.ungrab()
            except OSError:
                pass
            try:
                dev.close()
            except OSError:
                pass
        self._devices.clear()
        self._held.clear()
