import subprocess
import sys
from pathlib import Path

import pygame
import pytest

from lilypad.effects import assets


def test_art_root_for_dev_and_kiosk(tmp_path, monkeypatch):
    packaged = Path(assets.__file__).resolve().parents[1] / "assets"
    monkeypatch.delenv("LILYPAD_ART_DIR", raising=False)
    assert assets.asset_root() == packaged
    monkeypatch.setenv("LILYPAD_ART_DIR", str(tmp_path))
    assert assets.asset_root() == tmp_path
    assert assets.asset_root(kiosk=True) == packaged


def test_load_image_preserves_alpha(tmp_path):
    path = tmp_path / "sprite.png"
    sprite = pygame.Surface((2, 1), pygame.SRCALPHA)
    sprite.set_at((1, 0), (24, 16, 8, 127))
    pygame.image.save(sprite, path)
    result = assets.load_image(path)
    assert result.get_masks() == sprite.convert_alpha().get_masks()
    assert result.get_at((0, 0)).a == 0
    assert result.get_at((1, 0)) == (24, 16, 8, 127)


def test_load_image_without_display_keeps_native_format(tmp_path, monkeypatch):
    path = tmp_path / "indexed.bmp"
    pygame.image.save(pygame.Surface((2, 2), depth=8), path)
    monkeypatch.setattr(pygame.display, "get_surface", lambda: None)
    assert assets.load_image(path).get_bitsize() == 8


def test_budget_counts_nested_files_once(tmp_path):
    assert assets.budget_bytes(tmp_path) == 0
    (tmp_path / "manifest.toml").write_bytes(b"123")
    nested = tmp_path / "painted" / "frog"
    nested.mkdir(parents=True)
    (nested / "idle.png").write_bytes(b"12345")
    assert assets.budget_bytes(tmp_path) == 8


@pytest.mark.parametrize("supported", [True, False])
def test_webp_probe_uses_decoder_and_caches_result(monkeypatch, supported):
    calls = []

    def decode(stream, name):
        data = stream.read()
        assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        assert name.endswith(".webp")
        calls.append(data)
        if not supported:
            raise pygame.error("Unsupported image format")
        return pygame.Surface((1, 1))

    assets.webp_supported.cache_clear()
    try:
        monkeypatch.setattr(pygame.image, "load", decode)
        assert assets.webp_supported() is supported
        assert assets.webp_supported() is supported
        assert len(calls) == 1
    finally:
        assets.webp_supported.cache_clear()


def test_probe_cli_reports_local_decoder_and_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LILYPAD_ART_DIR", str(tmp_path))
    # An editable install can point at a sibling worktree.
    monkeypatch.setenv("PYTHONPATH", str(Path(assets.__file__).resolve().parents[2]))
    result = subprocess.run(
        [sys.executable, "-m", "lilypad.effects.assets", "--probe"],
        capture_output=True, text=True, check=True,
    )
    assert type(assets.webp_supported()) is bool
    assert f"WebP supported: {assets.webp_supported()}" in result.stdout
    assert str(tmp_path) in result.stdout
