"""Direct USB lighting backend for the Razer BlackWidow Chroma (PID 0x0203).

Speaks OpenRazer's wire protocol (RESEARCH.md §1) via pyusb — no kernel
module, no daemon:

- 90-byte reports sent as HID SET_REPORT control transfers:
  bmRequestType 0x21, bRequest 0x09, wValue 0x0300, wIndex 0x02.
- Report: status, transaction_id (0xFF), remaining_packets(2), protocol_type,
  data_size, command_class, command_id, args[80], crc (XOR of bytes 2..87),
  reserved.
- Custom frame: per row class 0x03 cmd 0x0B args [0xFF, row, 0, 21, RGB×22],
  then class 0x03 cmd 0x0A args [0x05, 0x00] to display it.

Only interface 2 (the control/macro HID interface) is detached from usbhid —
interfaces 0/1 keep delivering keystrokes to evdev.
"""

from __future__ import annotations

import logging
import time

from .base import Grid, LightingBackend
from .keymap import COLS, ROWS

log = logging.getLogger(__name__)

VENDOR_ID = 0x1532
PRODUCT_ID = 0x0203          # BlackWidow Chroma (original)
CONTROL_INTERFACE = 0x02

_CLASS_MISC = 0x00
_CLASS_MATRIX = 0x03
_CMD_SET_DEVICE_MODE = 0x04
_CMD_BRIGHTNESS = 0x03
_CMD_MATRIX_EFFECT = 0x0A
_CMD_MATRIX_FRAME_ROW = 0x0B
_EFFECT_SPECTRUM = 0x04
_EFFECT_CUSTOMFRAME = 0x05
_DEVICE_MODE_DRIVER = 0x03
_DEVICE_MODE_NORMAL = 0x00
_VARSTORE = 0x01
_BACKLIGHT_LED = 0x05


def build_report(command_class: int, command_id: int, args: bytes) -> bytes:
    """Assemble a 90-byte razer report with XOR checksum."""
    if len(args) > 80:
        raise ValueError("razer report arguments exceed 80 bytes")
    report = bytearray(90)
    report[0] = 0x00                 # status: new command
    report[1] = 0xFF                 # transaction id
    # bytes 2-3: remaining packets = 0; byte 4: protocol_type = 0
    report[5] = len(args)            # data_size
    report[6] = command_class
    report[7] = command_id
    report[8:8 + len(args)] = args
    crc = 0
    for b in report[2:88]:
        crc ^= b
    report[88] = crc                 # byte 89 reserved = 0
    return bytes(report)


class RazerHidBackend(LightingBackend):
    name = "razer_hid"

    def __init__(self) -> None:
        import usb.core
        import usb.util

        self._usb_util = usb.util
        self._dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if self._dev is None:
            raise RuntimeError(
                "BlackWidow Chroma (1532:0203) not found on USB"
            )
        self._detached = False
        if self._dev.is_kernel_driver_active(CONTROL_INTERFACE):
            self._dev.detach_kernel_driver(CONTROL_INTERFACE)
            self._detached = True
        usb.util.claim_interface(self._dev, CONTROL_INTERFACE)
        self._send(_CLASS_MISC, _CMD_SET_DEVICE_MODE,
                   bytes((_DEVICE_MODE_DRIVER, 0x00)))
        log.info("razer_hid: device claimed, driver mode enabled")

    def _send(self, command_class: int, command_id: int, args: bytes) -> None:
        report = build_report(command_class, command_id, args)
        self._dev.ctrl_transfer(
            0x21,               # Host→Device | Class | Interface
            0x09,               # HID SET_REPORT
            0x0300,             # feature report 0
            CONTROL_INTERFACE,
            report,
        )
        time.sleep(0.001)       # razer devices need a breather between reports

    def apply(self, grid: Grid) -> None:
        for row_idx in range(ROWS):
            rgb = bytearray()
            for col_idx in range(COLS):
                rgb.extend(grid[row_idx][col_idx])
            args = bytes((0xFF, row_idx, 0x00, COLS - 1)) + bytes(rgb)
            self._send(_CLASS_MATRIX, _CMD_MATRIX_FRAME_ROW, args)
        self._send(_CLASS_MATRIX, _CMD_MATRIX_EFFECT,
                   bytes((_EFFECT_CUSTOMFRAME, 0x00)))

    def set_brightness(self, value: float) -> None:
        raw = max(0, min(255, int(value * 255)))
        self._send(_CLASS_MATRIX, _CMD_BRIGHTNESS,
                   bytes((_VARSTORE, _BACKLIGHT_LED, raw)))

    def close(self) -> None:
        try:
            # Leave the keyboard doing something pretty, back in normal mode.
            self._send(_CLASS_MATRIX, _CMD_MATRIX_EFFECT, bytes((_EFFECT_SPECTRUM,)))
            self._send(_CLASS_MISC, _CMD_SET_DEVICE_MODE,
                       bytes((_DEVICE_MODE_NORMAL, 0x00)))
        except Exception:                      # noqa: BLE001 — best-effort restore
            log.warning("razer_hid: restore-on-close failed", exc_info=True)
        try:
            self._usb_util.release_interface(self._dev, CONTROL_INTERFACE)
            if self._detached:
                self._dev.attach_kernel_driver(CONTROL_INTERFACE)
        except Exception:                      # noqa: BLE001
            log.warning("razer_hid: interface release failed", exc_info=True)
