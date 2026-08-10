"""Kiosk startup must survive a monitor that isn't awake yet.

Found on real hardware: the Pi booted with the monitor off, both HDMI
connectors read `disconnected`, SDL raised "kmsdrm not available", and the app
exited — which turned into a systemd restart storm that only stayed under the
default StartLimitBurst by luck. Past that limit the unit latches into `failed`
and stays dead even after the monitor comes back.
"""

import pygame
import pytest

from lilypad import __main__ as entry


def _failing_set_mode(fail_times, sentinel):
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise pygame.error("kmsdrm not available")
        return sentinel

    return fake, calls


def test_waits_instead_of_exiting_when_no_display_is_attached(monkeypatch):
    sentinel = object()
    fake, calls = _failing_set_mode(2, sentinel)
    monkeypatch.setattr(pygame.display, "set_mode", fake)
    monkeypatch.setattr(entry.time, "sleep", lambda _: None)

    assert entry._wait_for_display(retry=0) is sentinel
    assert calls["n"] == 3, "should have retried until the monitor appeared"


def test_returns_immediately_when_a_display_is_already_there(monkeypatch):
    sentinel = object()
    fake, calls = _failing_set_mode(0, sentinel)
    monkeypatch.setattr(pygame.display, "set_mode", fake)
    slept = []
    monkeypatch.setattr(entry.time, "sleep", lambda s: slept.append(s))

    assert entry._wait_for_display(retry=0) is sentinel
    assert calls["n"] == 1
    assert slept == [], "no display problem means no waiting"


def test_survives_a_long_outage_without_giving_up(monkeypatch):
    # A monitor switched off overnight is an ordinary event, not a failure.
    sentinel = object()
    fake, calls = _failing_set_mode(500, sentinel)
    monkeypatch.setattr(pygame.display, "set_mode", fake)
    monkeypatch.setattr(entry.time, "sleep", lambda _: None)

    assert entry._wait_for_display(retry=0) is sentinel
    assert calls["n"] == 501


def test_a_non_display_error_is_not_swallowed(monkeypatch):
    def boom(*args, **kwargs):
        raise MemoryError("something genuinely wrong")

    monkeypatch.setattr(pygame.display, "set_mode", boom)
    monkeypatch.setattr(entry.time, "sleep", lambda _: None)

    with pytest.raises(MemoryError):
        entry._wait_for_display(retry=0)


def test_unit_file_disables_the_systemd_start_limit():
    """The backstop behind the retry loop: even if the app dies some other
    way, systemd must never stop trying."""
    from pathlib import Path
    unit = Path("deploy/lilypad.service").read_text(encoding="utf-8")
    assert "StartLimitIntervalSec=0" in unit
    assert "Restart=on-failure" in unit, "clean escape-hatch exit must stay stopped"


# --------------------------------------------------- clean shutdown on SIGTERM

def test_unit_file_bounds_the_stop_timeout():
    """systemd's 90 s default turned every stop/restart/reboot into a 90 s
    stall when the app ignored SIGTERM. Measured on-device."""
    from pathlib import Path
    unit = Path("deploy/lilypad.service").read_text(encoding="utf-8")
    line = [l for l in unit.splitlines() if l.startswith("TimeoutStopSec=")]
    assert line, "no TimeoutStopSec — a wedged frame could stall shutdown"
    assert int(line[0].split("=")[1]) <= 15


def test_kiosk_loop_honours_quit_instead_of_discarding_it():
    """The kiosk branch must drain SDL's queue *and* act on QUIT.

    ``pygame.event.clear()`` there was the original bug: SDL translates SIGTERM
    into a QUIT event, and clearing the queue threw it away every frame, so the
    app never noticed systemd asking it to stop.
    """
    import inspect
    src = inspect.getsource(entry.main)
    assert "pygame.event.clear()" not in src, "clear() silently drops QUIT"
    assert "pygame.QUIT" in src


def test_sigterm_handler_is_installed_before_the_display_wait():
    """Order matters, and getting it wrong was a real (measured) bug.

    The first version of this fix installed the handler just above the main
    loop — after ``_wait_for_display``. With the monitor off the app never got
    that far, SDL's handler stayed in effect, and a reboot still stalled until
    systemd's kill timeout. Verified on-device: 10.2 s, result `timeout`.
    """
    import inspect
    src = inspect.getsource(entry.main)
    install = src.index("_install_signal_handlers()")
    wait = src.index("_wait_for_display()")
    assert install < wait, "handlers must be armed before the app can block"
    assert src.index("pygame.init()") < install, "pygame.init() overwrites them"


def test_shutdown_while_waiting_for_a_display_exits_promptly(monkeypatch):
    """A reboot with the monitor off must not wait out the kill timeout."""
    monkeypatch.setattr(pygame.display, "set_mode",
                        lambda *a, **k: (_ for _ in ()).throw(pygame.error("nope")))
    slept = []

    def fake_sleep(s):
        slept.append(s)
        if len(slept) == 3:          # SIGTERM lands mid-wait
            entry._request_stop()

    monkeypatch.setattr(entry.time, "sleep", fake_sleep)
    entry._stop_requested = False
    try:
        assert entry._wait_for_display(retry=1.0) is None
        assert len(slept) < 10, "should bail out, not keep waiting"
    finally:
        entry._stop_requested = False


def test_stop_flag_is_reset_when_handlers_are_installed(monkeypatch):
    # Otherwise a flag left set by a previous run would make the next start
    # exit immediately.
    entry._stop_requested = True
    monkeypatch.setattr(entry.signal, "signal", lambda *a: None)
    entry._install_signal_handlers()
    assert entry._stop_requested is False
