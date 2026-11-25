"""Storybook letter cards: a painted page that replaces the pond for a few seconds.

Press the same letter three times (each within 1.2 s of the last) and the pond
dissolves into that letter's card; in attract mode the cards become a slow
slideshow. The card is a *background swap*: the pond is handed the page through
``set_card`` and everything the child presses keeps drawing on top, so no key is
ever queued or hidden.

Three pieces, all inert when ``effects.storybook`` is ``"off"``:

* ``Encore``: the pure, time-injected detector (2nd press prefetches, 3rd shows).
* ``_Decoder``: one daemon worker with a latest-wins slot, so a stale decode can
  never sit in front of the one that matters.
* ``Storybook``: the manifest, the two-card cache, the hold timers and the
  dissolve. ``set_card`` is a hard swap and the pond draws shore strips over its
  plate, so the dissolve is a snapshot of the frame as drawn, taken on the
  frame the swap happens, faded out on top (the same ``set_alpha`` trick as the
  pond's mood cross-fade). ``draw`` therefore has to run right after the pond.

Nothing here touches ``ctx.rng``. Decode and every loader error stay off the
input path: a failure logs once and the show is silently skipped.
"""

from __future__ import annotations

import logging
import threading
import tomllib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pygame

from . import assets

log = logging.getLogger(__name__)

MODES = ("encore", "attract", "both", "off")
ENCORE_WINDOW_S = 1.2        # max gap between presses of a run
DISSOLVE_S = 0.4
HOLD_S = 4.0                 # an encore card stays this long before dissolving out
READY_TIMEOUT_S = 1.0        # a show waits this long for a slow decode, then is skipped
ATTRACT_PERIOD_S = 8.0       # a new slideshow card every 8 s of attract mode
ATTRACT_PREFETCH_LEAD_S = 2.0
MAX_CARDS = 2                # decoded cards kept in memory: the current one and a prefetch
SWAP_FAILSAFE_S = 0.25       # a swap whose draw never came (asleep) just happens
SCHEMA = 1

Loader = Callable[[Path, "tuple[int, int]"], pygame.Surface]
ShowHook = Callable[[str, "str | None", str], None]


class Encore:
    """Same key three times in a row: ``press`` returns ``"prefetch"`` on the 2nd
    and ``"show"`` on the 3rd. A different key or a gap over the window resets;
    after a show the same key needs a fresh run of three. Pass ``None`` (or any
    non-card key) to reset the run."""

    def __init__(self, window: float = ENCORE_WINDOW_S) -> None:
        self.window = window
        self.reset()

    def reset(self) -> None:
        self._key: object = None
        self._count = 0
        self._last = 0.0

    def press(self, key: object, t: float) -> str | None:
        if key is None:
            self.reset()
            return None
        if key == self._key and self._count and t - self._last <= self.window + 1e-9:
            self._count += 1
        else:
            self._key, self._count = key, 1
        self._last = t
        if self._count == 2:
            return "prefetch"
        if self._count >= 3:
            self.reset()
            return "show"
        return None


@dataclass(frozen=True)
class CardRow:
    letter: str
    path: Path
    animal: str | None


def load_manifest(path: Path) -> dict[str, CardRow]:
    """Read ``[cards.<A-Z>] file=, animal=``; anything malformed is skipped with
    one warning. A missing or empty manifest simply means no cards."""
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Ignoring storybook manifest: %s", exc)
        return {}
    if data.get("schema") != SCHEMA:
        if data:
            log.warning("Ignoring storybook manifest: schema must be %d", SCHEMA)
        return {}
    rows = data.get("cards", {})
    if not isinstance(rows, dict):
        log.warning("Ignoring storybook manifest: cards must be a table")
        return {}
    cards: dict[str, CardRow] = {}
    for key, row in rows.items():
        try:
            letter = key.upper()
            if len(letter) != 1 or not ("A" <= letter <= "Z"):
                raise ValueError("card name must be one letter A-Z")
            rel = Path(row["file"])
            if rel.anchor or ".." in rel.parts:
                raise ValueError("file must be relative to the manifest")
            animal = row.get("animal")
            cards[letter] = CardRow(letter, path.parent / rel,
                                    animal if isinstance(animal, str) else None)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            log.warning("Ignoring storybook card %s: %s", key, exc)
    return dict(sorted(cards.items()))


def decode_card(path: Path, size: tuple[int, int]) -> pygame.Surface:
    """Decode one card to an opaque, display-format surface already at ``size``,
    so the pond's own plate conversion is a no-op on the press frame."""
    image = pygame.image.load(str(path))
    if image.get_bitsize() not in (24, 32):
        image = image.convert(24)
    if image.get_size() != size:
        image = pygame.transform.smoothscale(image, size)
    if pygame.display.get_surface() is not None:
        return image.convert()
    return image.convert(24) if image.get_flags() & pygame.SRCALPHA else image


class _Decoder:
    """One worker thread, started on the first request. The slot holds only the
    newest request (latest wins); results are collected from the main thread."""

    def __init__(self, loader: Loader) -> None:
        self._loader = loader
        self._cond = threading.Condition()
        self._slot: tuple[str, Path, tuple[int, int]] | None = None
        self._results: list[tuple[str, pygame.Surface | None, Exception | None]] = []
        self._thread: threading.Thread | None = None
        self._closed = False

    @property
    def started(self) -> bool:
        return self._thread is not None

    def request(self, key: str, path: Path, size: tuple[int, int]) -> str | None:
        """Queue a decode; returns the key of a request this one displaced."""
        with self._cond:
            if self._closed:
                return None
            dropped = self._slot[0] if self._slot else None
            self._slot = (key, path, size)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True,
                                                name="storybook-decoder")
                self._thread.start()
            self._cond.notify()
            return dropped

    def collect(self) -> list[tuple[str, pygame.Surface | None, Exception | None]]:
        with self._cond:
            results, self._results = self._results, []
        return results

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._slot is None and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                key, path, size = self._slot
                self._slot = None
            try:
                outcome = (key, self._loader(path, size), None)
            except Exception as exc:  # noqa: BLE001 - decode problems never reach the child
                outcome = (key, None, exc)
            with self._cond:
                if not self._closed:
                    self._results.append(outcome)

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._slot = None
            self._results = []
            self._cond.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)


class Storybook:
    """See the module docstring. ``mode`` is the ``effects.storybook`` choice.

    ``pond`` needs ``set_card(surface | None)`` and, optionally, ``painted``;
    cards are only shown over a painted pond (the legacy pond ignores
    ``set_card``, so nothing would change on screen). ``on_show`` hooks receive
    ``(letter, animal, source)`` when a card actually starts to show, with
    ``source`` ``"encore"`` or ``"attract"``; a skipped, failed or blocked show
    never fires them."""

    def __init__(self, size: tuple[int, int], mode: str = "both", *, pond=None,
                 root: Path | None = None, manifest: Path | None = None,
                 loader: Loader | None = None) -> None:
        if mode not in MODES:
            raise ValueError(f"storybook mode must be one of {MODES}, got {mode!r}")
        self.size = (int(size[0]), int(size[1]))
        self.mode = mode
        self.pond = pond
        self.on_show: list[ShowHook] = []
        self._encore: Encore | None = None
        self._cards: dict[str, CardRow] = {}
        self._decoder: _Decoder | None = None
        self._cache: OrderedDict[str, pygame.Surface] = OrderedDict()
        self._inflight: set[str] = set()
        self._failed: set[str] = set()
        self._shown: str | None = None       # letter whose card is (or is about to be) the pond plate
        self._source = "encore"
        self._hold_left: float | None = None  # None: held until told otherwise (attract)
        self._want: list | None = None        # [letter, source, waited] while a decode is awaited
        self._swap: tuple | None = None       # ("set", surface) | ("clear",), run by draw()
        self._swap_age = 0.0
        self._installed = False
        self._snap: pygame.Surface | None = None
        self._snap_t: float | None = None
        self._attract_t = 0.0
        self._attract_index = 0
        self._attract_prefetched = False
        self._closed = False
        self._loader: Loader = loader or decode_card
        if mode == "off":
            return                            # nothing loaded, no thread, no state
        if manifest is None:
            base = root if root is not None else assets.asset_root(kiosk=True)
            manifest = base / "storybook" / "manifest.toml"
        self._cards = load_manifest(manifest)
        if not self._cards:
            return
        self._encore = Encore()

    # ------------------------------------------------------------------ state

    @property
    def enabled(self) -> bool:
        return (self.mode != "off" and not self._closed and bool(self._cards)
                and bool(getattr(self.pond, "painted", True)))

    @property
    def showing(self) -> str | None:
        """Letter of the card currently (or just about to be) on screen."""
        return self._shown

    @property
    def cached_letters(self) -> list[str]:
        return list(self._cache)

    @property
    def thread_started(self) -> bool:
        return self._decoder is not None and self._decoder.started

    @property
    def dissolving(self) -> bool:
        return self._snap_t is not None or self._swap is not None

    def _encore_on(self) -> bool:
        return self.mode in ("encore", "both")

    def _attract_on(self) -> bool:
        return self.mode in ("attract", "both")

    # ------------------------------------------------------------------ input

    def press(self, key: str | None, t: float, *, party_active: bool = False) -> str | None:
        """Feed every press (``None`` for non-letter keys, which reset the run).
        Returns the detector's verdict; a ``show`` only acts when allowed."""
        if self._encore is None or not self._encore_on():
            return None
        letter = key.upper() if isinstance(key, str) and len(key) == 1 else None
        if letter is not None and not ("A" <= letter <= "Z"):
            letter = None
        verdict = self._encore.press(letter, t)
        if self._want is not None and self._want[1] == "encore" and self._want[0] != letter:
            self._want = None                  # the child moved on
        if not self.enabled or party_active or letter is None or letter not in self._cards:
            return verdict
        if verdict == "prefetch":
            self._request(letter)
        elif verdict == "show":
            self._show(letter, "encore")
        return verdict

    # ------------------------------------------------------------- frame loop

    def update(self, dt: float, *, party_active: bool = False,
               attract_active: bool = False) -> None:
        """The one per-frame entry. ``party_active`` clears any card at once;
        ``attract_active`` is whether attract mode is live this frame."""
        if self.mode == "off" or self._closed:
            return
        if party_active:
            self.clear()
            self._attract_t = 0.0
            return
        self._collect()
        if self._snap_t is not None:
            self._snap_t += dt
            if self._snap_t >= DISSOLVE_S:
                self._snap_t = None
        if self._swap is not None:
            self._swap_age += dt
            if self._swap_age > SWAP_FAILSAFE_S:
                self._run_swap(None)           # no draw arrived (asleep): swap without a fade
        if self._want is not None:
            self._want[2] += dt
            letter, source, waited = self._want
            if letter in self._cache:
                self._want = None
                self._begin(letter, source)
            elif letter in self._failed or waited >= READY_TIMEOUT_S:
                self._want = None              # slow or broken decode: skip silently
        if self._hold_left is not None and self._shown is not None and self._swap is None:
            self._hold_left -= dt
            if self._hold_left <= 0:
                self._end()
        self.attract_tick(dt, attract_active)

    def attract_tick(self, dt: float, active: bool) -> None:
        """Slideshow clock. Idempotent when inactive; leaves an attract card
        with a dissolve-out the moment attract mode ends."""
        if not self.enabled or not self._attract_on():
            return
        if not active:
            self._attract_t = 0.0
            self._attract_prefetched = False
            if self._shown is not None and self._source == "attract":
                self._end()
            if self._want is not None and self._want[1] == "attract":
                self._want = None
            return
        if self._source == "encore" and (self._shown is not None or self._want is not None):
            return
        if self._want is not None:
            return
        letters = list(self._cards)
        letters = [c for c in letters if c not in self._failed]
        if not letters:
            return
        self._attract_t += dt
        nxt = letters[self._attract_index % len(letters)]
        if not self._attract_prefetched and self._attract_t >= ATTRACT_PERIOD_S - ATTRACT_PREFETCH_LEAD_S:
            self._attract_prefetched = True
            self._request(nxt)
        if self._attract_t >= ATTRACT_PERIOD_S:
            self._attract_t = 0.0
            self._attract_prefetched = False
            self._attract_index = (self._attract_index + 1) % len(letters)
            self._show(nxt, "attract")

    def draw(self, target: pygame.Surface) -> None:
        """Call straight after the pond draws onto ``target`` (same surface)."""
        if self._swap is not None:
            self._run_swap(target)
        if self._snap_t is not None and self._snap is not None:
            alpha = round(255 * (1.0 - self._snap_t / DISSOLVE_S))
            if alpha > 0:
                self._snap.set_alpha(alpha)
                target.blit(self._snap, (0, 0))

    # --------------------------------------------------------------- internals

    def _request(self, letter: str) -> None:
        if (letter in self._cache or letter in self._inflight or letter in self._failed
                or letter not in self._cards or self._closed):
            return
        if self._decoder is None:
            self._decoder = _Decoder(self._loader)
        dropped = self._decoder.request(letter, self._cards[letter].path, self.size)
        if dropped is not None:
            self._inflight.discard(dropped)
        self._inflight.add(letter)

    def _collect(self) -> None:
        if self._decoder is None:
            return
        for letter, surface, error in self._decoder.collect():
            self._inflight.discard(letter)
            if surface is None:
                if letter not in self._failed:
                    log.warning("Storybook card %s failed to decode (%s); skipping it",
                                letter, error)
                self._failed.add(letter)
                continue
            self._cache[letter] = surface
            self._cache.move_to_end(letter)
            self._trim()

    def _trim(self) -> None:
        keep = {self._shown, self._want[0] if self._want else None}
        for letter in list(self._cache):
            if len(self._cache) <= MAX_CARDS:
                break
            if letter not in keep:
                del self._cache[letter]

    def _show(self, letter: str, source: str) -> None:
        if letter == self._shown and not self._want:
            if source == "encore":
                self._source = "encore"
                self._hold_left = HOLD_S       # same card again: just keep it up longer
            return
        if letter in self._cache:
            self._begin(letter, source)
            return
        if letter in self._failed:
            return
        self._want = [letter, source, 0.0]
        self._request(letter)

    def _begin(self, letter: str, source: str) -> None:
        surface = self._cache.get(letter)
        if surface is None or not self.enabled:
            return
        self._cache.move_to_end(letter)
        self._shown, self._source = letter, source
        self._hold_left = HOLD_S if source == "encore" else None
        self._swap, self._swap_age = ("set", surface), 0.0
        self._trim()
        row = self._cards[letter]
        for hook in list(self.on_show):
            try:
                hook(letter, row.animal, source)
            except Exception:
                log.exception("storybook on_show hook failed")

    def _end(self) -> None:
        self._shown = None
        self._hold_left = None
        if self._installed or (self._swap is not None and self._swap[0] == "set"):
            self._swap, self._swap_age = ("clear",), 0.0
        self._trim()

    def _run_swap(self, target: pygame.Surface | None) -> None:
        swap, self._swap = self._swap, None
        if swap is None:
            return
        if target is not None:
            if self._snap is None or self._snap.get_size() != target.get_size():
                self._snap = pygame.Surface(target.get_size())
                if pygame.display.get_surface() is not None:
                    self._snap = self._snap.convert()
            self._snap.set_alpha(None)
            self._snap.blit(target, (0, 0))
            self._snap_t = 0.0
        if swap[0] == "set":
            self._set_card(swap[1])
            self._installed = True
        elif self._installed:
            self._set_card(None)
            self._installed = False

    def _set_card(self, surface: pygame.Surface | None) -> None:
        if self.pond is None:
            return
        try:
            self.pond.set_card(surface)
        except Exception:
            log.exception("pond.set_card failed")

    # ---------------------------------------------------------------- teardown

    def clear(self) -> None:
        """Drop any card at once, with no dissolve (party, sleep, shutdown)."""
        self._shown = None
        self._hold_left = None
        self._want = None
        self._swap = None
        self._snap_t = None
        if self._installed:
            self._installed = False
            self._set_card(None)

    def close(self) -> None:
        """Clear the card, stop the decode thread and drop every cached card."""
        if self._closed:
            return
        self.clear()
        self._closed = True
        if self._decoder is not None:
            self._decoder.close()
        self._cache.clear()
        self._inflight.clear()
        self._snap = None
