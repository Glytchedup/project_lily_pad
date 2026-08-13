"""Boot-time ALSA selection, including the card-swap cases it exists for."""

from lilypad import hdmi_audio
from lilypad.doctor import Connector
from lilypad.hdmi_audio import HEADER, alsa_card_for, apply, desired_conf

from test_doctor import (
    PI3_CARDS,
    PI5_CARDS,
    full_edid,
    make_asound_cards,
    make_connector,
)


def connector(name: str) -> Connector:
    return Connector(name=name, card="card1", status="connected", edid_bytes=256)


# --------------------------------------------------------------------------
# Connector -> ALSA card
# --------------------------------------------------------------------------

def test_single_sink_is_unambiguous():
    """Pi 3 / Zero 2 W: one HDMI sink, whatever it is called."""
    assert alsa_card_for(connector("HDMI-A-1"), [(1, "vc4hdmi")]) == 1


def test_no_sinks_gives_none():
    assert alsa_card_for(connector("HDMI-A-1"), []) is None


def test_two_sinks_match_by_offset_suffix():
    """HDMI-A-1 is vc4hdmi0 and HDMI-A-2 is vc4hdmi1 — off by one."""
    cards = [(0, "vc4hdmi0"), (1, "vc4hdmi1")]
    assert alsa_card_for(connector("HDMI-A-1"), cards) == 0
    assert alsa_card_for(connector("HDMI-A-2"), cards) == 1


def test_two_sinks_with_shuffled_indices():
    """The ALSA index is not required to equal the driver's own suffix."""
    cards = [(2, "vc4hdmi1"), (3, "vc4hdmi0")]
    assert alsa_card_for(connector("HDMI-A-2"), cards) == 2
    assert alsa_card_for(connector("HDMI-A-1"), cards) == 3


def test_unnumbered_connector_falls_back_to_first():
    assert alsa_card_for(connector("HDMI-A"), [(4, "vc4hdmi0"), (5, "vc4hdmi1")]) == 4


def test_unmatched_suffix_falls_back_to_first():
    assert alsa_card_for(connector("HDMI-A-9"), [(0, "vc4hdmi0"), (1, "vc4hdmi1")]) == 0


# --------------------------------------------------------------------------
# desired_conf
# --------------------------------------------------------------------------

def test_no_live_output_declines_to_guess(tmp_path):
    """A wrong pin is silence; no pin is at least the ALSA default."""
    make_connector(tmp_path, "HDMI-A-1", status="connected", edid=b"")
    make_asound_cards(tmp_path, PI5_CARDS)
    assert desired_conf(tmp_path) is None


def test_no_hdmi_sink_declines(tmp_path):
    make_connector(tmp_path, "HDMI-A-1", edid=full_edid())
    make_asound_cards(tmp_path, " 0 [Headphones     ]: bcm2835 - Headphones\n")
    assert desired_conf(tmp_path) is None


def test_far_port_selects_card_one(tmp_path):
    """The exact bring-up case: near port dead, far port live, ALSA card 1."""
    make_connector(tmp_path, "HDMI-A-1", status="connected", edid=b"")
    make_connector(tmp_path, "HDMI-A-2", edid=full_edid())
    make_asound_cards(tmp_path, PI5_CARDS)
    contents, summary = desired_conf(tmp_path)
    assert "defaults.pcm.card 1" in contents
    assert "defaults.ctl.card 1" in contents
    assert summary == "HDMI-A-2 -> ALSA card 1 (vc4hdmi1)"


def test_older_pi_single_sink(tmp_path):
    """Same card, older board: one HDMI, and it is card 1 here."""
    make_connector(tmp_path, "HDMI-A-1", edid=full_edid())
    make_asound_cards(tmp_path, PI3_CARDS)
    contents, summary = desired_conf(tmp_path)
    assert "defaults.pcm.card 1" in contents
    assert "vc4hdmi" in summary


def test_non_hdmi_connector_ignored(tmp_path):
    make_connector(tmp_path, "DSI-1", card="card1", edid=full_edid())
    make_asound_cards(tmp_path, PI5_CARDS)
    assert desired_conf(tmp_path) is None


# --------------------------------------------------------------------------
# apply()
# --------------------------------------------------------------------------

def live_pi5(tmp_path, live_port="HDMI-A-2"):
    for name in ("HDMI-A-1", "HDMI-A-2"):
        make_connector(tmp_path, name,
                       edid=full_edid() if name == live_port else b"")
    make_asound_cards(tmp_path, PI5_CARDS)


def test_apply_writes_the_conf(tmp_path):
    live_pi5(tmp_path)
    (tmp_path / "etc").mkdir()
    result = apply(tmp_path)
    written = (tmp_path / "etc" / "asound.conf").read_text(encoding="utf-8")
    assert "wrote" in result
    assert "defaults.pcm.card 1" in written
    assert HEADER in written


def test_apply_creates_etc_if_absent(tmp_path):
    live_pi5(tmp_path)
    apply(tmp_path)
    assert (tmp_path / "etc" / "asound.conf").is_file()


def test_apply_is_idempotent(tmp_path):
    live_pi5(tmp_path)
    apply(tmp_path)
    assert "already correct" in apply(tmp_path)


def test_apply_leaves_no_temp_file_behind(tmp_path):
    live_pi5(tmp_path)
    apply(tmp_path)
    assert list((tmp_path / "etc").glob("*.tmp")) == []


def test_apply_rewrites_when_the_port_moves(tmp_path):
    """Cable moved to the other port: the next boot must follow it."""
    live_pi5(tmp_path, live_port="HDMI-A-2")
    apply(tmp_path)
    assert "card 1" in (tmp_path / "etc" / "asound.conf").read_text(encoding="utf-8")

    live_pi5(tmp_path, live_port="HDMI-A-1")
    assert "wrote" in apply(tmp_path)
    assert "card 0" in (tmp_path / "etc" / "asound.conf").read_text(encoding="utf-8")


def test_apply_never_stomps_a_hand_written_conf(tmp_path):
    live_pi5(tmp_path)
    (tmp_path / "etc").mkdir()
    mine = "# I know what I am doing\ndefaults.pcm.card 3\n"
    (tmp_path / "etc" / "asound.conf").write_text(mine, encoding="utf-8")
    result = apply(tmp_path)
    assert "leaving hand-written" in result
    assert (tmp_path / "etc" / "asound.conf").read_text(encoding="utf-8") == mine


def test_apply_declines_without_a_live_output(tmp_path):
    make_connector(tmp_path, "HDMI-A-1", status="connected", edid=b"")
    make_asound_cards(tmp_path, PI5_CARDS)
    assert "no live HDMI output" in apply(tmp_path)
    assert not (tmp_path / "etc" / "asound.conf").exists()


def test_dry_run_writes_nothing(tmp_path):
    live_pi5(tmp_path)
    result = apply(tmp_path, dry_run=True)
    assert result.startswith("would write")
    assert not (tmp_path / "etc" / "asound.conf").exists()


def test_dry_run_on_a_correct_system_reports_correct(tmp_path):
    live_pi5(tmp_path)
    apply(tmp_path)
    assert "already correct" in apply(tmp_path, dry_run=True)


def test_main_returns_zero(tmp_path, capsys):
    live_pi5(tmp_path)
    assert hdmi_audio.main(["--root", str(tmp_path), "--dry-run"]) == 0


def test_main_off_pi_is_not_an_error(tmp_path):
    assert hdmi_audio.main(["--root", str(tmp_path)]) == 0
