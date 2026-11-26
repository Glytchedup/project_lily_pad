"""SIGUSR1 frame dump: flag -> atomic PNG, failure never raises."""

from __future__ import annotations

import logging
import os
import signal
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from lilypad import frame_dump  # noqa: E402


@pytest.fixture()
def surface():
    # No pygame.init()/quit(): other tests own the display lifecycle, and a
    # quit here would break every later test that relies on it.
    s = pygame.Surface((32, 20))
    s.fill((200, 30, 60))
    return s


@pytest.fixture(autouse=True)
def _reset_flag():
    frame_dump._requested = False
    yield
    frame_dump._requested = False


def test_dump_frame_writes_png_atomically(surface, tmp_path, caplog):
    target = tmp_path / "run" / "lilypad"  # missing dir is created
    with caplog.at_level(logging.INFO, logger="lilypad"):
        path = frame_dump.dump_frame(surface, target)
    assert path == target / "frame.png"
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not (target / "frame.png.tmp").exists()
    back = pygame.image.load(str(path))
    assert back.get_size() == (32, 20)
    assert tuple(back.get_at((5, 5)))[:3] == (200, 30, 60)
    assert sum(str(path) in r.getMessage() for r in caplog.records
               if r.levelno == logging.INFO) == 1


def test_dump_frame_overwrites_previous(surface, tmp_path):
    frame_dump.dump_frame(surface, tmp_path)
    surface.fill((1, 2, 3))
    frame_dump.dump_frame(surface, tmp_path)
    assert tuple(pygame.image.load(str(tmp_path / "frame.png")).get_at((0, 0)))[:3] == (1, 2, 3)


def test_dump_frame_failure_logs_and_does_not_raise(surface, tmp_path, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so makedirs under it fails")
    with caplog.at_level(logging.WARNING, logger="lilypad"):
        assert frame_dump.dump_frame(surface, blocker / "sub") is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_dump_frame_bad_surface_does_not_raise(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="lilypad"):
        assert frame_dump.dump_frame(None, tmp_path) is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert not (tmp_path / "frame.png").exists()


def test_service_request_only_acts_when_flagged(surface, tmp_path, monkeypatch):
    monkeypatch.setattr(frame_dump, "frame_dir", lambda kiosk: tmp_path)
    assert frame_dump.service_request(surface, False) is None
    assert not (tmp_path / "frame.png").exists()
    frame_dump._request()
    assert frame_dump.service_request(surface, False) == tmp_path / "frame.png"
    assert (tmp_path / "frame.png").exists()
    # The flag is consumed: no second write until another signal.
    (tmp_path / "frame.png").unlink()
    assert frame_dump.service_request(surface, False) is None
    assert not (tmp_path / "frame.png").exists()


def test_frame_dir_by_mode():
    assert frame_dump.frame_dir(True) == Path("/run/lilypad")
    assert frame_dump.frame_dir(False) == Path(tempfile.gettempdir())


def test_install_without_sigusr1_is_a_noop(monkeypatch):
    monkeypatch.delattr(signal, "SIGUSR1", raising=False)
    assert frame_dump.install() is False


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="no SIGUSR1 on this platform")
def test_sigusr1_sets_flag_only():
    old = signal.getsignal(signal.SIGUSR1)
    try:
        assert frame_dump.install() is True
        assert frame_dump._requested is False
        os.kill(os.getpid(), signal.SIGUSR1)
        assert frame_dump._requested is True
    finally:
        signal.signal(signal.SIGUSR1, old)


def test_service_unit_has_runtime_directory():
    unit = Path(__file__).resolve().parents[1] / "deploy" / "lilypad.service"
    assert "RuntimeDirectory=lilypad" in unit.read_text(encoding="utf-8").splitlines()
