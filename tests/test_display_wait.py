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
