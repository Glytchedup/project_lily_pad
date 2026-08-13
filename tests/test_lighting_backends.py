"""Lighting backends and the auto-fallback chain, against fake hardware.

`make_backend` is the code that decides whether a toddler gets a lit keyboard
or a dark one, and every branch of it is a hardware branch — so all of it was
untested. The fakes below stand in for pyusb and the OpenRazer daemon so the
selection logic, the wire protocol and the restore-on-close paths are all
exercised on a machine with no Razer anything attached.
"""

import sys
import types

import pytest

from lilypad.lighting import make_backend
from lilypad.lighting.base import LightingBackend
from lilypad.lighting.keymap import COLS, ROWS
from lilypad.lighting.mock import MockLightingBackend
from lilypad.lighting.razer_hid import (
    CONTROL_INTERFACE,
    PRODUCT_ID,
    VENDOR_ID,
    RazerHidBackend,
    build_report,
)
from lilypad.lighting.threaded import ThreadedLightingBackend


def blank_grid():
    return [[(0, 0, 0) for _ in range(COLS)] for _ in range(ROWS)]


# --------------------------------------------------------------------------
# The report format
# --------------------------------------------------------------------------

def test_report_is_ninety_bytes():
    assert len(build_report(0x03, 0x0A, b"\x05\x00")) == 90


def test_report_header_fields():
    report = build_report(0x03, 0x0B, b"\x01\x02\x03")
    assert report[0] == 0x00            # status: new command
    assert report[1] == 0xFF            # transaction id
    assert report[5] == 3               # data_size
    assert report[6] == 0x03            # command class
    assert report[7] == 0x0B            # command id
    assert report[8:11] == b"\x01\x02\x03"


def test_report_checksum_is_xor_of_the_body():
    report = build_report(0x03, 0x0B, b"\x01\x02\x03")
    expected = 0
    for byte in report[2:88]:
        expected ^= byte
    assert report[88] == expected
    assert report[89] == 0              # reserved


def test_report_rejects_oversized_arguments():
    with pytest.raises(ValueError, match="80 bytes"):
        build_report(0x03, 0x0B, bytes(81))


def test_report_accepts_exactly_eighty_argument_bytes():
    assert len(build_report(0x03, 0x0B, bytes(80))) == 90


def test_empty_arguments_are_valid():
    assert build_report(0x00, 0x04, b"")[5] == 0


# --------------------------------------------------------------------------
# Fake pyusb
# --------------------------------------------------------------------------

class FakeUsbDevice:
    def __init__(self, kernel_active=True):
        self.transfers = []
        self.kernel_active = kernel_active
        self.detached = self.attached = False

    def is_kernel_driver_active(self, interface):
        return self.kernel_active

    def detach_kernel_driver(self, interface):
        self.detached = True

    def attach_kernel_driver(self, interface):
        self.attached = True

    def ctrl_transfer(self, req_type, request, value, index, data):
        self.transfers.append((req_type, request, value, index, bytes(data)))


@pytest.fixture
def fake_usb(monkeypatch):
    """Install a fake `usb.core` / `usb.util` and hand back the state."""
    state = {"device": FakeUsbDevice(), "claimed": [], "released": []}

    core = types.ModuleType("usb.core")
    core.find = lambda **kw: state["device"]
    util = types.ModuleType("usb.util")
    util.claim_interface = lambda dev, i: state["claimed"].append(i)
    util.release_interface = lambda dev, i: state["released"].append(i)
    pkg = types.ModuleType("usb")
    pkg.core, pkg.util = core, util

    monkeypatch.setitem(sys.modules, "usb", pkg)
    monkeypatch.setitem(sys.modules, "usb.core", core)
    monkeypatch.setitem(sys.modules, "usb.util", util)
    # No real sleeping between reports in tests.
    monkeypatch.setattr("lilypad.lighting.razer_hid.time.sleep", lambda _s: None)
    return state


# --------------------------------------------------------------------------
# razer_hid
# --------------------------------------------------------------------------

def test_hid_claims_the_control_interface(fake_usb):
    RazerHidBackend()
    assert fake_usb["claimed"] == [CONTROL_INTERFACE]


def test_hid_detaches_the_kernel_driver_when_active(fake_usb):
    RazerHidBackend()
    assert fake_usb["device"].detached


def test_hid_leaves_the_kernel_driver_alone_when_inactive(fake_usb):
    fake_usb["device"].kernel_active = False
    backend = RazerHidBackend()
    assert not fake_usb["device"].detached
    backend.close()
    assert not fake_usb["device"].attached, "must not attach what it never took"


def test_hid_enters_driver_mode_on_open(fake_usb):
    RazerHidBackend()
    (transfer,) = fake_usb["device"].transfers
    report = transfer[4]
    assert report[6] == 0x00 and report[7] == 0x04     # misc / set device mode
    assert report[8] == 0x03                           # driver mode


def test_hid_raises_when_the_keyboard_is_absent(fake_usb, monkeypatch):
    import usb.core
    monkeypatch.setattr(usb.core, "find", lambda **kw: None)
    with pytest.raises(RuntimeError, match="1532:0203"):
        RazerHidBackend()


def test_hid_looks_for_the_right_device(fake_usb, monkeypatch):
    seen = {}
    import usb.core
    monkeypatch.setattr(usb.core, "find",
                        lambda **kw: seen.update(kw) or fake_usb["device"])
    RazerHidBackend()
    assert seen == {"idVendor": VENDOR_ID, "idProduct": PRODUCT_ID}


def test_hid_control_transfer_uses_the_hid_set_report_parameters(fake_usb):
    RazerHidBackend()
    req_type, request, value, index, _ = fake_usb["device"].transfers[0]
    assert (req_type, request, value, index) == (0x21, 0x09, 0x0300,
                                                 CONTROL_INTERFACE)


def test_hid_apply_sends_one_report_per_row_then_a_display(fake_usb):
    backend = RazerHidBackend()
    fake_usb["device"].transfers.clear()
    backend.apply(blank_grid())
    transfers = fake_usb["device"].transfers
    assert len(transfers) == ROWS + 1
    for row, transfer in enumerate(transfers[:ROWS]):
        report = transfer[4]
        assert report[6] == 0x03 and report[7] == 0x0B      # matrix frame row
        assert report[8] == 0xFF
        assert report[9] == row
        assert report[11] == COLS - 1
    final = transfers[-1][4]
    assert final[6] == 0x03 and final[7] == 0x0A            # matrix effect
    assert final[8] == 0x05                                 # custom frame


def test_hid_apply_carries_the_pixel_colours(fake_usb):
    grid = blank_grid()
    grid[0][0] = (10, 20, 30)
    grid[0][COLS - 1] = (40, 50, 60)
    backend = RazerHidBackend()
    fake_usb["device"].transfers.clear()
    backend.apply(grid)
    report = fake_usb["device"].transfers[0][4]
    assert tuple(report[12:15]) == (10, 20, 30)
    assert tuple(report[12 + 3 * (COLS - 1):15 + 3 * (COLS - 1)]) == (40, 50, 60)


@pytest.mark.parametrize("value,expected", [
    (0.0, 0), (1.0, 255), (0.5, 127), (-1.0, 0), (2.0, 255),
])
def test_hid_brightness_is_clamped(fake_usb, value, expected):
    backend = RazerHidBackend()
    fake_usb["device"].transfers.clear()
    backend.set_brightness(value)
    report = fake_usb["device"].transfers[0][4]
    assert report[6] == 0x03 and report[7] == 0x03
    assert report[10] == expected


def test_hid_close_restores_spectrum_and_normal_mode(fake_usb):
    backend = RazerHidBackend()
    fake_usb["device"].transfers.clear()
    backend.close()
    reports = [t[4] for t in fake_usb["device"].transfers]
    assert reports[0][7] == 0x0A and reports[0][8] == 0x04   # spectrum
    assert reports[1][7] == 0x04 and reports[1][8] == 0x00   # normal mode
    assert fake_usb["released"] == [CONTROL_INTERFACE]
    assert fake_usb["device"].attached


def test_hid_close_survives_a_dead_device(fake_usb):
    """Unplugged mid-shutdown must not turn a clean exit into a crash."""
    backend = RazerHidBackend()

    def boom(*_a, **_k):
        raise OSError("device gone")

    fake_usb["device"].ctrl_transfer = boom
    import usb.util
    usb.util.release_interface = boom
    backend.close()                     # must not raise


# --------------------------------------------------------------------------
# Fake OpenRazer
# --------------------------------------------------------------------------

class FakeMatrix:
    def __init__(self):
        self.cells = {}
        self.draws = 0

    def __setitem__(self, key, value):
        self.cells[key] = value

    def draw(self):
        self.draws += 1


class FakeFx:
    def __init__(self, advanced=True):
        self.advanced = types.SimpleNamespace(matrix=FakeMatrix()) if advanced else None
        self.spectrum_calls = 0

    def spectrum(self):
        self.spectrum_calls += 1


class FakeKeyboard:
    def __init__(self, type_="keyboard", advanced=True, name="BlackWidow Chroma"):
        self.type, self.name = type_, name
        self.fx = FakeFx(advanced)
        self.brightness = 0.0


@pytest.fixture
def fake_openrazer(monkeypatch):
    state = {"devices": [FakeKeyboard()]}
    client = types.ModuleType("openrazer.client")
    client.DeviceManager = lambda: types.SimpleNamespace(devices=state["devices"])
    pkg = types.ModuleType("openrazer")
    pkg.client = client
    monkeypatch.setitem(sys.modules, "openrazer", pkg)
    monkeypatch.setitem(sys.modules, "openrazer.client", client)
    return state


def test_openrazer_picks_the_keyboard(fake_openrazer):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    fake_openrazer["devices"] = [
        FakeKeyboard(type_="mouse"), FakeKeyboard(type_="keyboard")]
    backend = OpenRazerBackend()
    assert backend._kbd.type == "keyboard"


def test_openrazer_raises_without_a_keyboard(fake_openrazer):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    fake_openrazer["devices"] = [FakeKeyboard(type_="mouse")]
    with pytest.raises(RuntimeError, match="no keyboard"):
        OpenRazerBackend()


def test_openrazer_raises_without_matrix_support(fake_openrazer):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    fake_openrazer["devices"] = [FakeKeyboard(advanced=False)]
    with pytest.raises(RuntimeError, match="per-key matrix"):
        OpenRazerBackend()


def test_openrazer_apply_writes_every_cell_then_draws(fake_openrazer):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    backend = OpenRazerBackend()
    grid = blank_grid()
    grid[1][2] = (7, 8, 9)
    backend.apply(grid)
    matrix = backend._kbd.fx.advanced.matrix
    assert len(matrix.cells) == ROWS * COLS
    assert matrix.cells[(1, 2)] == (7, 8, 9)
    assert matrix.draws == 1


@pytest.mark.parametrize("value,expected", [
    (0.0, 0.0), (1.0, 100.0), (0.4, 40.0), (-1.0, 0.0), (5.0, 100.0),
])
def test_openrazer_brightness_is_clamped(fake_openrazer, value, expected):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    backend = OpenRazerBackend()
    backend.set_brightness(value)
    assert backend._kbd.brightness == pytest.approx(expected)


def test_openrazer_brightness_failure_is_not_fatal(fake_openrazer):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    backend = OpenRazerBackend()
    type(backend._kbd).brightness = property(
        lambda self: 0.0,
        lambda self, v: (_ for _ in ()).throw(OSError("daemon gone")))
    try:
        backend.set_brightness(0.5)     # must not raise
    finally:
        del type(backend._kbd).brightness


def test_openrazer_close_restores_spectrum(fake_openrazer):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    backend = OpenRazerBackend()
    backend.close()
    assert backend._kbd.fx.spectrum_calls == 1


def test_openrazer_close_survives_a_dead_daemon(fake_openrazer):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    backend = OpenRazerBackend()

    def boom():
        raise OSError("daemon gone")

    backend._kbd.fx.spectrum = boom
    backend.close()                     # must not raise


# --------------------------------------------------------------------------
# make_backend — the selection chain
# --------------------------------------------------------------------------

def test_explicit_mock_is_not_threaded():
    backend = make_backend("mock")
    assert isinstance(backend, MockLightingBackend)
    assert not isinstance(backend, ThreadedLightingBackend)


def test_hardware_backends_are_wrapped_in_a_thread(fake_usb):
    """USB I/O blocks; it must never run on the render loop."""
    backend = make_backend("razer_hid")
    assert isinstance(backend, ThreadedLightingBackend)
    assert backend.name.startswith("razer_hid")
    backend.close()


def test_openrazer_is_also_threaded(fake_openrazer):
    backend = make_backend("openrazer")
    assert isinstance(backend, ThreadedLightingBackend)
    assert backend.name.startswith("openrazer")
    backend.close()


def test_auto_prefers_razer_hid(fake_usb, fake_openrazer):
    backend = make_backend("auto")
    assert backend.name.startswith("razer_hid")
    backend.close()


def test_auto_falls_back_to_openrazer(fake_openrazer, monkeypatch):
    """No pyusb at all is the ordinary case on a machine without it."""
    monkeypatch.setitem(sys.modules, "usb", None)
    monkeypatch.setitem(sys.modules, "usb.core", None)
    backend = make_backend("auto")
    assert backend.name.startswith("openrazer")
    backend.close()


def test_auto_falls_back_to_mock_when_nothing_works(monkeypatch):
    monkeypatch.setitem(sys.modules, "usb", None)
    monkeypatch.setitem(sys.modules, "usb.core", None)
    monkeypatch.setitem(sys.modules, "openrazer", None)
    monkeypatch.setitem(sys.modules, "openrazer.client", None)
    backend = make_backend("auto")
    assert backend.name == "mock"


def test_an_explicit_choice_does_not_fall_through(monkeypatch):
    """Asking for razer_hid and silently getting openrazer would hide a real
    hardware problem — an explicit choice fails to mock, not to its neighbour."""
    monkeypatch.setitem(sys.modules, "usb", None)
    monkeypatch.setitem(sys.modules, "usb.core", None)
    assert make_backend("razer_hid").name == "mock"


def test_an_unknown_preference_yields_mock():
    assert make_backend("nonsense").name == "mock"


def test_make_backend_never_raises(monkeypatch):
    """The show must go on: a dark keyboard is a disappointment, a crash is a
    black screen."""
    def explode(*_a, **_k):
        raise RuntimeError("catastrophe")

    monkeypatch.setattr("lilypad.lighting.razer_hid.RazerHidBackend.__init__", explode)
    for preference in ("auto", "razer_hid", "openrazer", "mock", "bogus"):
        assert make_backend(preference) is not None


def test_every_backend_satisfies_the_interface(fake_usb, fake_openrazer):
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    for cls in (MockLightingBackend, RazerHidBackend, OpenRazerBackend):
        for method in ("apply", "set_brightness", "close"):
            assert callable(getattr(cls, method)), f"{cls.__name__}.{method}"
        assert isinstance(cls.name, str) and cls.name


def test_backends_declare_distinct_names():
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    names = {MockLightingBackend.name, RazerHidBackend.name, OpenRazerBackend.name}
    assert len(names) == 3


def test_lighting_backend_is_the_declared_base():
    from lilypad.lighting.openrazer_backend import OpenRazerBackend
    assert issubclass(RazerHidBackend, LightingBackend)
    assert issubclass(OpenRazerBackend, LightingBackend)
