import tomllib
from pathlib import Path

import pytest

from lilypad.config import Config, load


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
    assert cfg.music.tunes == "reward"
    assert cfg.music.tune_volume == 0.6
    assert cfg.music.background_folder == "music"
    assert cfg.music.fade_after == 30.0


def test_music_from_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[music]\nkey_notes = false\ntunes = "always"\ntune_volume = 0.2\n'
                  'background_folder = "songs"\nfade_after = 15.0\n')
    cfg = load(p)
    assert cfg.music.key_notes is False
    assert cfg.music.tunes == "always"
    assert cfg.music.tune_volume == 0.2
    assert cfg.music.background_folder == "songs"
    assert cfg.music.fade_after == 15.0


def test_music_tune_volume_is_clamped(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[music]\ntune_volume = 4.0\n")
    assert load(p).music.tune_volume == 1.0


def test_music_fade_after_cannot_go_negative(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[music]\nfade_after = -5.0\n")
    assert load(p).music.fade_after == 0.0


def test_invalid_tune_mode_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[music]\ntunes = "sometimes"\n')
    with pytest.raises(ValueError, match="music.tunes"):
        load(p)


def test_active_tune_mode_accepted(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[music]\ntunes = "active"\n')
    assert load(p).music.tunes == "active"


def test_repo_config_declares_the_music_section():
    cfg = load("config.toml")
    assert cfg.music.tunes in ("idle", "always", "off", "active", "reward")
    assert cfg.music.key_notes is True


# Each row pins the public setting, its default and the classic-play value.
PAINTED_SETTINGS = (
    ("effects.animal_art", "painted", "traced"),
    ("effects.pip_art", "painted", "drawn"),
    ("effects.max_sprite_width", 0.60, 0.0),
    ("effects.clean_sprites", True, False),
    ("effects.ecosystem", True, False),
    ("effects.storybook", "both", "off"),
    ("effects.fx_style", "painted", "glow"),
    ("effects.album", True, False),
    ("effects.parade", True, False),
    ("scene.world", "painted", "drawn"),
    ("scene.parallax", True, False),
    ("scene.reflections", True, False),
    ("scene.fireflies", True, False),
    ("scene.mood_minutes", 5.0, 5.0),  # drawn scenery cycles every 300 s
    ("scene.lily", True, False),
    ("scene.lily_move_seconds", 75.0, 75.0),
    ("audio.voice", "narrator", "espeak"),
    ("audio.phrases", True, False),
    ("audio.count_aloud", True, False),
    ("music.bundled_tracks", True, False),
    ("music.reward_source", "folder_first", "folder_first"),
    ("music.party_show", True, False),
    ("lighting.mirror_animals", True, False),
    ("escape.summary_seconds", 8.0, 0.0),
)


def setting(cfg, name):
    section, key = name.split(".")
    return getattr(getattr(cfg, section), key)


@pytest.mark.parametrize("name,default,legacy", PAINTED_SETTINGS)
def test_painted_settings_in_defaults_and_both_profiles(name, default, legacy):
    assert setting(Config(), name) == setting(load(), name) == default
    section, key = name.split(".")
    for filename, expected in (("config.toml", default), ("config.legacy.toml", legacy)):
        path = Path(__file__).resolve().parents[1] / filename
        assert tomllib.loads(path.read_text(encoding="utf-8"))[section][key] == expected
        value = setting(load(path), name)
        assert type(value) is type(expected)
        assert value == expected


def load_setting(tmp_path, name, literal):
    section, key = name.split(".")
    path = tmp_path / "setting.toml"
    path.write_text(f"[{section}]\n{key} = {literal}\n", encoding="utf-8")
    return load(path)


@pytest.mark.parametrize("name,default,legacy", PAINTED_SETTINGS)
def test_painted_settings_reject_wrong_types(tmp_path, name, default, legacy):
    # A quoted boolean is truthy in Python, and a TOML bool is an int subclass.
    wrong = {bool: '"false"', float: 'true', str: '["painted"]'}[type(default)]
    with pytest.raises(ValueError, match=name):
        load_setting(tmp_path, name, wrong)


@pytest.mark.parametrize("name,allowed", [
    ("effects.animal_art", ("painted", "traced", "drawn")),
    ("effects.pip_art", ("painted", "drawn")),
    ("effects.storybook", ("encore", "attract", "both", "off")),
    ("effects.fx_style", ("painted", "glow")),
    ("scene.world", ("painted", "drawn")),
    ("audio.voice", ("narrator", "espeak")),
    ("music.reward_source", ("folder_first", "bundled", "generated")),
])
def test_painted_choices(tmp_path, name, allowed):
    for choice in allowed:
        assert setting(load_setting(tmp_path, name, f'"{choice}"'), name) == choice
    with pytest.raises(ValueError, match=name):
        load_setting(tmp_path, name, '"unknown"')


@pytest.mark.parametrize("entries,expected", [
    ("", "painted"),
    ("silhouettes = true", "painted"),
    ("silhouettes = false", "drawn"),
    ('silhouettes = false\nanimal_art = "traced"', "traced"),
])
def test_silhouettes_compatibility(tmp_path, entries, expected):
    path = tmp_path / "art.toml"
    path.write_text(f"[effects]\n{entries}\n", encoding="utf-8")
    assert load(path).effects.animal_art == expected


@pytest.mark.parametrize("name,literal,expected", [
    ("effects.max_sprite_width", "-1", 0.0),
    ("effects.max_sprite_width", "0.33", 0.33),
    ("effects.max_sprite_width", "2", 1.0),
    ("escape.summary_seconds", "-1", 0.0),
    ("escape.summary_seconds", "2.5", 2.5),
    ("scene.mood_minutes", "0.5", 0.5),
    ("scene.lily_move_seconds", "12", 12.0),
])
def test_painted_numeric_settings(tmp_path, name, literal, expected):
    assert setting(load_setting(tmp_path, name, literal), name) == expected


@pytest.mark.parametrize("name,literal", [
    ("effects.max_sprite_width", "nan"),
    ("escape.summary_seconds", "inf"),
    ("scene.mood_minutes", "-inf"),
    ("scene.mood_minutes", "0"),
    ("scene.mood_minutes", "-1"),
    ("scene.lily_move_seconds", "0"),
    ("scene.lily_move_seconds", "-5"),
    ("scene.lily_move_seconds", "nan"),
])
def test_painted_invalid_numbers(tmp_path, name, literal):
    with pytest.raises(ValueError, match=name):
        load_setting(tmp_path, name, literal)
