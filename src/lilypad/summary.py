"""The parent's "today's play" card, shown for a few seconds as the app exits.

SAFETY-CRITICAL: this runs on the exit path, after the parent has already held
the escape combo. It must never delay shutdown beyond its deadline, never raise,
and never trap anybody:

* ``run_summary`` returns at ``deadline`` (an absolute value of the injected
  ``clock``) or as soon as ``poll()`` is truthy, whichever comes first. Setup is
  checked against both between every unit of work, and the frame loop is capped,
  so the worst case is the deadline plus one small step.
* Every ``Exception`` is caught here, logged, and turned into a plain return.
* Keys are ignored. ``poll()`` exists only to keep the input grab drained and to
  report a quit/SIGTERM flag: it must return a bool (truthy = stop now) and must
  *not* hand the raw event list back, or any keypress would end the card.
* Nothing is written to disk and no randomness is used.
"""

from __future__ import annotations

import logging
import math
import time

import pygame

from .effects import album
from .effects.animals import ANIMAL_LETTERS

log = logging.getLogger(__name__)

DESIGN_W, DESIGN_H = 1920, 1080
FPS = 30
FADE_IN = 0.5
FADE_OUT = 0.4

TEXT = (240, 245, 255)
MUTED = (150, 170, 205)
GOLD = (255, 214, 102)
PANEL = (10, 20, 42, 190)
PANEL_EDGE = (120, 165, 235, 150)

_NAMES = {"trex": "T. rex", "xrayfish": "X-ray fish"}


def animal_title(name: str) -> str:
    return _NAMES.get(name, name.replace("_", " ").title())


def format_duration(seconds: float) -> str:
    """Parent-friendly time: ``0 min``, ``<1 min``, ``42 min``, ``1 h 05 min``."""
    seconds = max(0.0, float(seconds)) if math.isfinite(seconds) else 0.0
    if seconds <= 0:
        return "0 min"
    if seconds < 60:
        return "<1 min"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _fit_font(text: str, max_width: int, size: int) -> pygame.font.Font:
    while size > 12:
        font = album._font(size)
        if font.size(text)[0] <= max_width:
            return font
        size -= 4
    return album._font(12)


def _gradient(size: tuple[int, int]) -> pygame.Surface:
    w, h = size
    surface = pygame.Surface(size)
    top, bottom = (9, 15, 32), (22, 44, 78)
    for y in range(h):
        k = y / max(1, h - 1)
        pygame.draw.line(surface, tuple(round(a + (b - a) * k) for a, b in zip(top, bottom)),
                         (0, y), (w, y))
    return surface


def _panel(surface: pygame.Surface, rect: pygame.Rect, radius: int) -> None:
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(layer, PANEL, layer.get_rect(), border_radius=radius)
    pygame.draw.rect(layer, PANEL_EDGE, layer.get_rect(), width=2, border_radius=radius)
    surface.blit(layer, rect.topleft)


def _text(surface, text, size, colour, *, center=None, midleft=None, max_width=None):
    font = _fit_font(text, max_width, size) if max_width else album._font(size)
    image = font.render(text, True, colour)
    rect = image.get_rect()
    if center is not None:
        rect.center = center
    elif midleft is not None:
        rect.midleft = midleft
    surface.blit(image, rect)
    return rect


def render_card(size: tuple[int, int], stats, root=None, halt=None) -> pygame.Surface | None:
    """Draw the whole card once. ``halt()`` is polled between portraits; if it
    reports True the build is abandoned and ``None`` is returned."""
    w, h = size
    s = min(w / DESIGN_W, h / DESIGN_H)
    ox, oy = (w - DESIGN_W * s) / 2, (h - DESIGN_H * s) / 2

    def X(v):
        return round(ox + v * s)

    def Y(v):
        return round(oy + v * s)

    def S(v):
        return max(1, round(v * s))

    backdrop = album.load_backdrop(album.album_assets(root).get("card"), size)
    card = backdrop.copy() if backdrop is not None else _gradient(size)
    if card.get_bitsize() < 24:
        card = card.convert()

    _text(card, "Today's play", S(110), TEXT, center=(X(960), Y(88)))

    letters = frozenset(stats.letters_found)
    favourite = stats.favourite

    # --- three stat tiles --------------------------------------------------
    tiles = (
        (format_duration(stats.time_played), "Time played"),
        (str(stats.parties), "Parties earned" if stats.parties != 1 else "Party earned"),
        (format_duration(stats.longest_streak), "Longest streak"),
    )
    tile_w, tile_h, tile_gap = 310, 250, 30
    for i, (value, label) in enumerate(tiles):
        rect = pygame.Rect(X(128 + i * (tile_w + tile_gap)), Y(200), S(tile_w), S(tile_h))
        _panel(card, rect, S(28))
        _text(card, value, S(92), GOLD, center=(rect.centerx, rect.y + S(110)),
              max_width=S(tile_w - 40))
        _text(card, label, S(40), MUTED, center=(rect.centerx, rect.y + S(196)),
              max_width=S(tile_w - 40))

    # --- favourite animal --------------------------------------------------
    fav_rect = pygame.Rect(X(1170), Y(200), S(622), S(tile_h))
    _panel(card, fav_rect, S(28))
    _text(card, "Favourite animal", S(40), MUTED, center=(fav_rect.centerx, fav_rect.y + S(40)))
    if favourite is not None and not (halt and halt()):
        art = album.portrait(favourite, S(160))
        card.blit(art, (fav_rect.x + S(36), fav_rect.y + S(68)))
        times = stats.animal_counts.get(favourite, 0)
        _text(card, animal_title(favourite), S(66), TEXT,
              midleft=(fav_rect.x + S(36 + 160 + 28), fav_rect.y + S(128)),
              max_width=S(622 - 36 - 160 - 28 - 24))
        _text(card, f"{times} time{'s' if times != 1 else ''}", S(40), MUTED,
              midleft=(fav_rect.x + S(36 + 160 + 28), fav_rect.y + S(188)))
    else:
        _text(card, "Not met yet", S(56), MUTED, center=(fav_rect.centerx, fav_rect.y + S(150)))

    # --- A-Z grid ----------------------------------------------------------
    found = sum(1 for letter in ANIMAL_LETTERS if letter in letters)
    _text(card, f"Letters found: {found} of 26", S(54), TEXT, center=(X(960), Y(548)))
    cols, cell_w, cell_h, edge = 13, 128, 184, 108
    x0 = 960 - cols * cell_w / 2
    for index, (letter, animal) in enumerate(ANIMAL_LETTERS.items()):
        if halt and halt():
            return None
        col, row = index % cols, index // cols
        cx = x0 + col * cell_w + cell_w / 2
        top = 604 + row * (cell_h + 16)
        lit = letter in letters
        art = (album.portrait if lit else album.dim_portrait)(animal, S(edge))
        card.blit(art, (round(X(cx) - art.get_width() / 2), Y(top)))
        _text(card, letter, S(40), GOLD if lit else (95, 108, 135),
              center=(X(cx), Y(top + edge + 26)))
    return card


def run_summary(screen, stats, deadline, poll, clock=time.monotonic, *,
                sleep=time.sleep, fps=FPS, root=None) -> None:
    """Show the card until ``deadline`` (absolute, on ``clock``) or until
    ``poll()`` is truthy. Never raises; never overruns by more than a frame."""
    try:
        start = clock()
        frame = 1.0 / max(1, fps)
        halted = False

        def halt() -> bool:
            nonlocal halted
            halted = halted or clock() >= deadline or bool(poll())
            return halted

        if halt():
            return
        card = render_card(screen.get_size(), stats, root, halt)
        if card is None or halt():
            return
        try:
            card = card.convert()
        except pygame.error:
            pass
        # A stalled clock must not hold the exit hostage.
        max_frames = int(max(0.0, deadline - start) * fps * 2) + 30
        for _ in range(max_frames):
            now = clock()
            if now >= deadline or poll():
                return
            fade = min(1.0, (now - start) / FADE_IN, max(0.0, (deadline - now)) / FADE_OUT)
            if fade < 1.0:
                screen.fill((0, 0, 0))
                card.set_alpha(round(255 * max(0.0, fade)))
            else:
                card.set_alpha(None)
            screen.blit(card, (0, 0))
            pygame.display.flip()
            sleep(max(0.0, min(frame, deadline - clock())))
    except Exception:
        log.exception("summary card failed; continuing to exit")
