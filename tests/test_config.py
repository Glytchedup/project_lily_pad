import pytest

from lilypad.config import load


def test_defaults_without_file():
    cfg = load(None)
    assert cfg.audio.mute is False
    assert cfg.display.fps == 60
    assert cfg.lighting.backend == "auto"
    assert cfg.escape.combo == ("LEFTSHIFT", "RIGHTSHIFT", "BACKSPACE")
    assert cfg.escape.hold_seconds == 5.0


def test_missing_file_uses_defaults(tmp_path):
    cfg = load(tmp_path / "nope.toml")
    assert cfg.effects.max_particles == 900


def test_partial_file_merges_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[audio]\nmute = true\nvolume = 2.5\n', encoding="utf-8")
    cfg = load(p)
    assert cfg.audio.mute is True
    assert cfg.audio.volume == 1.0          # clamped
    assert cfg.display.fps == 60            # untouched section defaulted


def test_escape_combo_normalized_upper(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[escape]\ncombo = ["leftshift", "rightshift", "backspace"]\n',
                 encoding="utf-8")
    cfg = load(p)
    assert cfg.escape.combo == ("LEFTSHIFT", "RIGHTSHIFT", "BACKSPACE")


def test_single_key_escape_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[escape]\ncombo = ["ESC"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="at least 2"):
        load(p)


def test_bad_backend_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[lighting]\nbackend = "synapse"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="backend"):
        load(p)


def test_repo_config_file_is_valid():
    # The checked-in config.toml must always load.
    cfg = load("config.toml")
    assert cfg.display.dev_window == (1280, 720)


def test_effects_new_toggles_default(tmp_path):
    from lilypad.config import load
    cfg = load(None)
    assert cfg.effects.trails is True
    assert cfg.effects.milestone_every == 50


def test_effects_new_toggles_from_toml(tmp_path):
    from lilypad.config import load
    p = tmp_path / "c.toml"
    p.write_text("[effects]\ntrails = false\nmilestone_every = -5\n")
    cfg = load(p)
    assert cfg.effects.trails is False
    assert cfg.effects.milestone_every == 0   # negative clamps to disabled
