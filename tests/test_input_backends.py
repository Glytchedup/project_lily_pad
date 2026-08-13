"""The three input backends, including the dev/Pi naming contract.

The project's whole testing story rests on "the full app runs and tests on a
desktop with --dev", and that is only true while the SDL backend and the evdev
backend agree on what to call a key. They did not: pygame reports punctuation
as the printed glyph (",") and evdev as a word ("COMMA"), so the colour and
shape keys worked on the Pi and were dead on a desktop. Hence the parity tests
below, which are the point of this file.
"""

import sys
import types

import pygame
import pytest

from lilypad.input.base import KeyEvent
from lilypad.input.mapper import _COLOR_KEYS, _SHAPE_KEYS, _SPECIALS, classify
from lilypad.input.sdl_backend import SdlInputBackend, _canonical
from lilypad.input.synthetic import SyntheticInputBackend


# --------------------------------------------------------------------------
# SDL backend — naming
# --------------------------------------------------------------------------

@pytest.mark.parametrize("attr,expected", [
    ("K_a", "A"),
    ("K_z", "Z"),
    ("K_RETURN", "ENTER"),
    ("K_ESCAPE", "ESC"),
    ("K_LSHIFT", "LEFTSHIFT"),
    ("K_RSHIFT", "RIGHTSHIFT"),
    ("K_BACKSPACE", "BACKSPACE"),
    ("K_SPACE", "SPACE"),
    ("K_F7", "F7"),
    ("K_UP", "UP"),
])
def test_canonical_names_match_evdev(attr, expected):
    assert _canonical(getattr(pygame, attr)) == expected


@pytest.mark.parametrize("attr,expected", [
    ("K_COMMA", "COMMA"),
    ("K_PERIOD", "DOT"),
    ("K_SLASH", "SLASH"),
    ("K_SEMICOLON", "SEMICOLON"),
    ("K_QUOTE", "APOSTROPHE"),
    ("K_BACKQUOTE", "GRAVE"),
    ("K_MINUS", "MINUS"),
    ("K_EQUALS", "EQUAL"),
    ("K_LEFTBRACKET", "LEFTBRACE"),
    ("K_RIGHTBRACKET", "RIGHTBRACE"),
    ("K_BACKSLASH", "BACKSLASH"),
])
def test_punctuation_uses_evdev_words_not_glyphs(attr, expected):
    """pygame says ",", evdev says "COMMA". The mapper speaks evdev."""
    assert _canonical(getattr(pygame, attr)) == expected


@pytest.mark.parametrize("attr,expected", [
    ("K_KP0", "KP0"),
    ("K_KP7", "KP7"),
    ("K_KP_DIVIDE", "KPSLASH"),
    ("K_KP_MULTIPLY", "KPASTERISK"),
    ("K_KP_PLUS", "KPPLUS"),
    ("K_KP_MINUS", "KPMINUS"),
    ("K_KP_PERIOD", "KPDOT"),
])
def test_numpad_keys_are_distinct_from_the_main_row(attr, expected):
    """"[.]" must not collapse onto "." — they are different keys and the
    numpad ones carry shapes."""
    assert _canonical(getattr(pygame, attr)) == expected


def all_key_codes():
    """Every pygame key constant. (pygame-ce has no K_LAST sentinel.)"""
    return [value for name, value in vars(pygame).items()
            if name.startswith("K_") and isinstance(value, int)]


def reachable_names():
    return {_canonical(code) for code in all_key_codes()}


def test_every_shape_key_is_reachable_in_dev_mode():
    """A key the mapper knows but SDL can never produce is a feature that
    silently only exists on the Pi."""
    missing = set(_SHAPE_KEYS) - reachable_names()
    assert not missing, f"unreachable from a desktop keyboard: {sorted(missing)}"


def test_every_colour_key_is_reachable_in_dev_mode():
    missing = set(_COLOR_KEYS) - reachable_names()
    assert not missing, f"unreachable from a desktop keyboard: {sorted(missing)}"


def test_most_special_keys_are_reachable_in_dev_mode():
    """Media keys legitimately have no desktop equivalent; the rest should."""
    reachable = reachable_names()
    media = {"MUTE", "VOLUMEUP", "VOLUMEDOWN", "PLAYPAUSE",
             "NEXTSONG", "PREVIOUSSONG", "STOPCD", "COMPOSE"}
    missing = set(_SPECIALS) - reachable - media
    assert not missing, f"unreachable from a desktop keyboard: {sorted(missing)}"


def test_canonical_names_never_contain_spaces_or_brackets():
    for code in all_key_codes():
        name = _canonical(code)
        assert " " not in name
        assert "[" not in name and "]" not in name


def test_canonical_is_stable():
    assert _canonical(pygame.K_COMMA) == _canonical(pygame.K_COMMA)


# --------------------------------------------------------------------------
# SDL backend — event handling
# --------------------------------------------------------------------------

def _post(**kwargs):
    pygame.event.post(pygame.event.Event(kwargs.pop("type"), **kwargs))


@pytest.fixture
def sdl():
    pygame.event.clear()
    backend = SdlInputBackend()
    backend.start()
    yield backend
    backend.stop()
    pygame.event.clear()


def test_keydown_becomes_a_pressed_event(sdl):
    _post(type=pygame.KEYDOWN, key=pygame.K_a)
    events = sdl.poll()
    assert [(e.name, e.pressed) for e in events] == [("A", True)]


def test_keyup_becomes_a_released_event(sdl):
    _post(type=pygame.KEYDOWN, key=pygame.K_a)
    sdl.poll()
    _post(type=pygame.KEYUP, key=pygame.K_a)
    assert [(e.name, e.pressed) for e in sdl.poll()] == [("A", False)]


def test_held_keys_track_press_and_release(sdl):
    _post(type=pygame.KEYDOWN, key=pygame.K_a)
    _post(type=pygame.KEYDOWN, key=pygame.K_b)
    sdl.poll()
    assert sdl.held_keys() == frozenset({"A", "B"})
    _post(type=pygame.KEYUP, key=pygame.K_a)
    sdl.poll()
    assert sdl.held_keys() == frozenset({"B"})


def test_quit_sets_the_flag(sdl):
    assert sdl.quit_requested is False
    _post(type=pygame.QUIT)
    sdl.poll()
    assert sdl.quit_requested is True


def test_stop_clears_held_keys(sdl):
    _post(type=pygame.KEYDOWN, key=pygame.K_a)
    sdl.poll()
    sdl.stop()
    assert sdl.held_keys() == frozenset()


def test_poll_with_no_events_is_empty(sdl):
    assert sdl.poll() == []


def test_a_shape_key_survives_the_whole_dev_path(sdl):
    """End to end: SDL event -> canonical name -> a shape action."""
    _post(type=pygame.KEYDOWN, key=pygame.K_COMMA)
    (event,) = sdl.poll()
    action = classify(event.name)
    assert action.kind == "shape" and action.letter == "circle"


# --------------------------------------------------------------------------
# Synthetic backend
# --------------------------------------------------------------------------

def drain(backend, limit=5.0):
    """Poll until the backend says it is done. Real wall-clock, so it is
    bounded rather than spun on."""
    import time
    deadline = time.monotonic() + limit
    out = []
    while not backend.quit_requested and time.monotonic() < deadline:
        out.extend(backend.poll())
    return out


def test_synthetic_generates_events_then_stops():
    backend = SyntheticInputBackend(duration=0.2, events_per_second=200)
    backend.start()
    seen = drain(backend)
    assert seen
    assert backend.quit_requested


def test_synthetic_presses_and_releases_stay_consistent():
    backend = SyntheticInputBackend(duration=0.3, events_per_second=200)
    backend.start()
    held = set()
    import time
    deadline = time.monotonic() + 5.0
    while not backend.quit_requested and time.monotonic() < deadline:
        for ev in backend.poll():
            if ev.pressed:
                assert ev.name not in held, "pressed a key already held"
                held.add(ev.name)
            else:
                assert ev.name in held, "released a key that was not held"
                held.discard(ev.name)
    assert backend.held_keys() == frozenset(held)


def test_synthetic_fires_a_mash_burst():
    """Chaos mode is only exercised on-device if the smoke run triggers it."""
    backend = SyntheticInputBackend(duration=0.3, events_per_second=200)
    backend.start()
    batches = []
    import time
    deadline = time.monotonic() + 5.0
    while not backend.quit_requested and time.monotonic() < deadline:
        got = backend.poll()
        if got:
            batches.append(got)
    assert any(len(b) >= 5 for b in batches), "no mash burst in the smoke run"


def test_synthetic_reaches_every_effect_family():
    """The smoke run is the on-device self-test; a family it never presses is
    a family nobody finds broken until a toddler does."""
    from lilypad.input.synthetic import _KEYS
    kinds = {classify(name).kind for name in _KEYS}
    assert {"letter", "number", "space", "enter", "arrow", "special",
            "shape", "color"} <= kinds


def test_synthetic_stop_clears_state():
    backend = SyntheticInputBackend(duration=0.2, events_per_second=200)
    backend.start()
    backend.poll()
    backend.stop()
    assert backend.held_keys() == frozenset()


# --------------------------------------------------------------------------
# evdev backend — against a fake `evdev` module
# --------------------------------------------------------------------------

class FakeEcodes:
    EV_KEY = 1
    KEY_A = 30
    KEY_PLAYPAUSE = 164
    KEY = {30: "KEY_A", 44: "KEY_Z", 51: "KEY_COMMA",
           164: "KEY_PLAYPAUSE", 99: ["KEY_SYSRQ", "KEY_PRINT"]}


class FakeInputEvent:
    def __init__(self, type_, code, value):
        self.type, self.code, self.value = type_, code, value


class FakeDevice:
    def __init__(self, path, name="Razer BlackWidow Chroma", caps=None,
                 grab_error=None, events=None):
        self.path, self.name = path, name
        self._caps = caps if caps is not None else [FakeEcodes.KEY_A]
        self._grab_error = grab_error
        self._events = list(events or [])
        self.grabbed = self.ungrabbed = self.closed = False
        self.read_error = None

    def capabilities(self):
        return {FakeEcodes.EV_KEY: self._caps}

    def grab(self):
        if self._grab_error:
            raise self._grab_error
        self.grabbed = True

    def ungrab(self):
        self.ungrabbed = True

    def close(self):
        self.closed = True

    def fileno(self):
        return 0

    def read(self):
        if self.read_error:
            raise self.read_error
        events, self._events = self._events, []
        return events


@pytest.fixture
def fake_evdev(monkeypatch):
    """Install a fake `evdev` package so the Pi backend is testable anywhere."""
    devices: dict[str, FakeDevice] = {}
    module = types.ModuleType("evdev")
    ecodes_mod = types.ModuleType("evdev.ecodes")
    for attr in ("EV_KEY", "KEY_A", "KEY_PLAYPAUSE", "KEY"):
        setattr(ecodes_mod, attr, getattr(FakeEcodes, attr))
    module.ecodes = ecodes_mod
    module.list_devices = lambda: sorted(devices)
    module.InputDevice = lambda path: devices[path]
    monkeypatch.setitem(sys.modules, "evdev", module)
    monkeypatch.setitem(sys.modules, "evdev.ecodes", ecodes_mod)
    # select.select is used to find readable devices; make everything readable.
    monkeypatch.setattr("lilypad.input.evdev_backend.select.select",
                        lambda r, w, x, t: (list(r), [], []))
    return devices


def make_backend(devices, **kw):
    from lilypad.input.evdev_backend import EvdevInputBackend
    return EvdevInputBackend(**kw)


def test_evdev_grabs_every_keyboard(fake_evdev):
    fake_evdev["/dev/input/event0"] = FakeDevice("/dev/input/event0")
    fake_evdev["/dev/input/event1"] = FakeDevice(
        "/dev/input/event1", caps=[FakeEcodes.KEY_PLAYPAUSE])
    backend = make_backend(fake_evdev)
    backend.start()
    assert all(d.grabbed for d in fake_evdev.values())


def test_evdev_skips_non_keyboards(fake_evdev):
    fake_evdev["/dev/input/event0"] = FakeDevice("/dev/input/event0")
    fake_evdev["/dev/input/event1"] = FakeDevice("/dev/input/event1", caps=[])
    backend = make_backend(fake_evdev)
    backend.start()
    assert fake_evdev["/dev/input/event1"].closed
    assert not fake_evdev["/dev/input/event1"].grabbed


def test_evdev_raises_when_nothing_could_be_grabbed(fake_evdev):
    """A silent failure here is a keyboard that still reaches the console."""
    fake_evdev["/dev/input/event0"] = FakeDevice(
        "/dev/input/event0", grab_error=OSError("busy"))
    with pytest.raises(RuntimeError, match="no keyboard event devices"):
        make_backend(fake_evdev).start()


def test_evdev_name_filter_selects_devices(fake_evdev):
    fake_evdev["/dev/input/event0"] = FakeDevice("/dev/input/event0", name="Razer X")
    fake_evdev["/dev/input/event1"] = FakeDevice("/dev/input/event1", name="Dell KB")
    backend = make_backend(fake_evdev, name_filter="razer")
    backend.start()
    assert fake_evdev["/dev/input/event0"].grabbed
    assert not fake_evdev["/dev/input/event1"].grabbed


def test_evdev_translates_key_codes_to_names(fake_evdev):
    dev = FakeDevice("/dev/input/event0", events=[
        FakeInputEvent(FakeEcodes.EV_KEY, 30, 1),     # A down
        FakeInputEvent(FakeEcodes.EV_KEY, 51, 1),     # COMMA down
        FakeInputEvent(FakeEcodes.EV_KEY, 30, 0),     # A up
    ])
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    assert [(e.name, e.pressed) for e in backend.poll()] == [
        ("A", True), ("COMMA", True), ("A", False)]


def test_evdev_names_match_the_mapper(fake_evdev):
    """The name evdev produces for a comma is the name the mapper expects."""
    dev = FakeDevice("/dev/input/event0",
                     events=[FakeInputEvent(FakeEcodes.EV_KEY, 51, 1)])
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    (event,) = backend.poll()
    assert classify(event.name).kind == "shape"


def test_evdev_ignores_key_repeats(fake_evdev):
    dev = FakeDevice("/dev/input/event0", events=[
        FakeInputEvent(FakeEcodes.EV_KEY, 30, 2),     # repeat
    ])
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    assert backend.poll() == []


def test_evdev_ignores_non_key_events(fake_evdev):
    dev = FakeDevice("/dev/input/event0",
                     events=[FakeInputEvent(99, 30, 1)])   # EV_SYN etc.
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    assert backend.poll() == []


def test_evdev_ignores_unknown_codes(fake_evdev):
    dev = FakeDevice("/dev/input/event0",
                     events=[FakeInputEvent(FakeEcodes.EV_KEY, 4242, 1)])
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    assert backend.poll() == []


def test_evdev_resolves_aliased_codes(fake_evdev):
    """Some codes map to a list of names; take the first."""
    dev = FakeDevice("/dev/input/event0",
                     events=[FakeInputEvent(FakeEcodes.EV_KEY, 99, 1)])
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    assert [e.name for e in backend.poll()] == ["SYSRQ"]


def test_evdev_tracks_held_keys(fake_evdev):
    dev = FakeDevice("/dev/input/event0", events=[
        FakeInputEvent(FakeEcodes.EV_KEY, 30, 1),
        FakeInputEvent(FakeEcodes.EV_KEY, 44, 1),
    ])
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    backend.poll()
    assert backend.held_keys() == frozenset({"A", "Z"})


def test_evdev_drops_a_device_that_vanishes(fake_evdev):
    """Unplugging the keyboard mid-play must not take the app down with it."""
    dev = FakeDevice("/dev/input/event0")
    dev.read_error = OSError("no such device")
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    assert backend.poll() == []
    assert backend._devices == []
    assert dev.closed


def test_evdev_poll_without_devices_is_empty(fake_evdev):
    backend = make_backend(fake_evdev)
    assert backend.poll() == []


def test_evdev_stop_ungrabs_and_closes(fake_evdev):
    dev = FakeDevice("/dev/input/event0")
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()
    backend.stop()
    assert dev.ungrabbed and dev.closed
    assert backend.held_keys() == frozenset()


def test_evdev_stop_survives_a_dead_device(fake_evdev):
    dev = FakeDevice("/dev/input/event0")
    fake_evdev["/dev/input/event0"] = dev
    backend = make_backend(fake_evdev)
    backend.start()

    def boom():
        raise OSError("gone")

    dev.ungrab = boom
    dev.close = boom
    backend.stop()                       # must not raise
    assert backend._devices == []


def test_evdev_skips_devices_that_cannot_be_opened(fake_evdev, monkeypatch):
    fake_evdev["/dev/input/event0"] = FakeDevice("/dev/input/event0")
    fake_evdev["/dev/input/event1"] = FakeDevice("/dev/input/event1")

    import evdev
    real = evdev.InputDevice

    def flaky(path):
        if path.endswith("event0"):
            raise OSError("permission denied")
        return real(path)

    monkeypatch.setattr(evdev, "InputDevice", flaky)
    backend = make_backend(fake_evdev)
    backend.start()
    assert len(backend._devices) == 1


def test_all_three_backends_share_an_interface():
    """The app swaps these freely; a missing method is a runtime crash on the
    Pi and nowhere else."""
    from lilypad.input.evdev_backend import EvdevInputBackend
    for cls in (SdlInputBackend, SyntheticInputBackend, EvdevInputBackend):
        for method in ("start", "poll", "held_keys", "stop"):
            assert callable(getattr(cls, method)), f"{cls.__name__}.{method}"
        assert hasattr(cls(), "quit_requested")


def test_key_event_is_hashable_and_comparable():
    a = KeyEvent(name="A", pressed=True, ts=1.0)
    assert a == KeyEvent(name="A", pressed=True, ts=1.0)
