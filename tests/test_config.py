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


# ------------------------------------------------------------ music section

def test_music_defaults():
    cfg = load(None)
    assert cfg.music.key_notes is True
    # Off by default: an unattended playground goes quiet rather than playing
    # backing music to an empty room.
    assert cfg.music.tunes == "off"
    assert cfg.music.tune_volume == 0.45
    # The celebration flourish is an event cue, not background music, so it
    # ships on — it only ever sounds when somebody just did something.
    assert cfg.music.flourish is True


def test_flourish_can_be_toggled_off(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[music]\nflourish = false\n")
    assert load(p).music.flourish is False


def test_idle_tunes_still_available(tmp_path):
    """Off is the default, not the only option — the tunes still work."""
    p = tmp_path / "config.toml"
    p.write_text('[music]\ntunes = "idle"\n', encoding="utf-8")
    assert load(p).music.tunes == "idle"


def test_music_from_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[music]\nkey_notes = false\ntunes = "always"\ntune_volume = 0.2\n')
    cfg = load(p)
    assert cfg.music.key_notes is False
    assert cfg.music.tunes == "always"
    assert cfg.music.tune_volume == 0.2


def test_music_tune_volume_is_clamped(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[music]\ntune_volume = 4.0\n")
    assert load(p).music.tune_volume == 1.0


def test_invalid_tune_mode_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[music]\ntunes = "sometimes"\n')
    with pytest.raises(ValueError, match="music.tunes"):
        load(p)


def test_repo_config_declares_the_music_section():
    cfg = load("config.toml")
    assert cfg.music.tunes in ("idle", "always", "off")
    assert cfg.music.key_notes is True
