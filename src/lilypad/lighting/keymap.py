"""Key name → (row, col) position on the BlackWidow Chroma's 6×22 LED matrix.

Layout follows OpenRazer's matrix convention for the original BlackWidow
Chroma (PID 0x0203): row 0 is the Esc/F-key row, column 0 is the M1–M5 macro
column. Positions only feed ripple-origin math, so an off-by-one on an exotic
key is cosmetically harmless; VERIFY.md includes an on-device probe check.
"""

from __future__ import annotations

ROWS = 6
COLS = 22

KEY_MATRIX: dict[str, tuple[int, int]] = {
    # Row 0 — Esc + function row
    "ESC": (0, 1),
    "F1": (0, 3), "F2": (0, 4), "F3": (0, 5), "F4": (0, 6),
    "F5": (0, 7), "F6": (0, 8), "F7": (0, 9), "F8": (0, 10),
    "F9": (0, 11), "F10": (0, 12), "F11": (0, 13), "F12": (0, 14),
    "SYSRQ": (0, 15), "SCROLLLOCK": (0, 16), "PAUSE": (0, 17),
    # Row 1 — number row
    "MACRO1": (1, 0), "GRAVE": (1, 1),
    "1": (1, 2), "2": (1, 3), "3": (1, 4), "4": (1, 5), "5": (1, 6),
    "6": (1, 7), "7": (1, 8), "8": (1, 9), "9": (1, 10), "0": (1, 11),
    "MINUS": (1, 12), "EQUAL": (1, 13), "BACKSPACE": (1, 14),
    "INSERT": (1, 15), "HOME": (1, 16), "PAGEUP": (1, 17),
    "NUMLOCK": (1, 18), "KPSLASH": (1, 19), "KPASTERISK": (1, 20), "KPMINUS": (1, 21),
    # Row 2 — QWERTY row
    "MACRO2": (2, 0), "TAB": (2, 1),
    "Q": (2, 2), "W": (2, 3), "E": (2, 4), "R": (2, 5), "T": (2, 6),
    "Y": (2, 7), "U": (2, 8), "I": (2, 9), "O": (2, 10), "P": (2, 11),
    "LEFTBRACE": (2, 12), "RIGHTBRACE": (2, 13), "BACKSLASH": (2, 14),
    "DELETE": (2, 15), "END": (2, 16), "PAGEDOWN": (2, 17),
    "KP7": (2, 18), "KP8": (2, 19), "KP9": (2, 20), "KPPLUS": (2, 21),
    # Row 3 — home row
    "MACRO3": (3, 0), "CAPSLOCK": (3, 1),
    "A": (3, 2), "S": (3, 3), "D": (3, 4), "F": (3, 5), "G": (3, 6),
    "H": (3, 7), "J": (3, 8), "K": (3, 9), "L": (3, 10),
    "SEMICOLON": (3, 11), "APOSTROPHE": (3, 12), "ENTER": (3, 14),
    "KP4": (3, 18), "KP5": (3, 19), "KP6": (3, 20),
    # Row 4 — shift row
    "MACRO4": (4, 0), "LEFTSHIFT": (4, 1),
    "Z": (4, 3), "X": (4, 4), "C": (4, 5), "V": (4, 6), "B": (4, 7),
    "N": (4, 8), "M": (4, 9), "COMMA": (4, 10), "DOT": (4, 11),
    "SLASH": (4, 12), "RIGHTSHIFT": (4, 14),
    "UP": (4, 16),
    "KP1": (4, 18), "KP2": (4, 19), "KP3": (4, 20), "KPENTER": (4, 21),
    # Row 5 — bottom row
    "MACRO5": (5, 0), "LEFTCTRL": (5, 1), "LEFTMETA": (5, 2), "LEFTALT": (5, 3),
    "SPACE": (5, 7),
    "RIGHTALT": (5, 11), "FN": (5, 12), "MENU": (5, 13), "COMPOSE": (5, 13),
    "RIGHTCTRL": (5, 14),
    "LEFT": (5, 15), "DOWN": (5, 16), "RIGHT": (5, 17),
    "KP0": (5, 19), "KPDOT": (5, 20),
}

CENTER = (2, 8)  # ripple origin for keys we can't place


def position(name: str) -> tuple[int, int]:
    return KEY_MATRIX.get(name, CENTER)
