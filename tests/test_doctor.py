"""Doctor checks against a synthetic /sys, /proc and /etc.

Every fault here is one that actually happened during the first on-device
bring-up (CHANGELOG, 2026-08-12). The point of the fake root is that these
regressions get caught on a Windows dev box with no Pi attached — which is the
only way they get caught at all between bring-ups.
"""

from pathlib import Path

import pytest

from lilypad import doctor
from lilypad.doctor import (
    FAIL,
    PASS,
    SKIP,
    WARN,
    Check,
    Report,
    check_alsa_card,
    check_authorized_keys,
    check_card_swap,
    check_hdmi_edid,
    check_mode_pinned,
    check_model,
    check_overlay,
    check_power,
    check_service,
    check_sounds,
    check_wifi_regdom,
    find_connectors,
    format_report,
    read_model,
    run_all,
    write_stamp,
)


# --------------------------------------------------------------------------
# Fake-root builders
# --------------------------------------------------------------------------

def make_connector(root: Path, name: str, card: str = "card1",
                   status: str = "connected", edid: bytes = b"") -> None:
    d = root / "sys" / "class" / "drm" / f"{card}-{name}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "status").write_text(status, encoding="utf-8")
    (d / "edid").write_bytes(edid)


def full_edid(blocks: int = 2) -> bytes:
    """A plausible EDID: 128 bytes per block, 2 blocks when audio is advertised."""
    return bytes(128 * blocks)


def make_asound_cards(root: Path, text: str) -> None:
    p = root / "proc" / "asound"
    p.mkdir(parents=True, exist_ok=True)
    (p / "cards").write_text(text, encoding="utf-8")


PI5_CARDS = """\
 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
                      vc4-hdmi-0
 1 [vc4hdmi1       ]: vc4-hdmi - vc4-hdmi-1
                      vc4-hdmi-1
"""

PI3_CARDS = """\
 0 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones
                      bcm2835 Headphones
 1 [vc4hdmi        ]: vc4-hdmi - vc4-hdmi
                      vc4-hdmi
"""


def make_cmdline(root: Path, text: str) -> None:
    p = root / "boot" / "firmware"
    p.mkdir(parents=True, exist_ok=True)
    (p / "cmdline.txt").write_text(text, encoding="utf-8")


def make_mounts(root: Path, fstype: str) -> None:
    p = root / "proc"
    p.mkdir(parents=True, exist_ok=True)
    (p / "mounts").write_text(
        f"/dev/root / {fstype} rw,relatime 0 0\n"
        "proc /proc proc rw,nosuid 0 0\n", encoding="utf-8")


def make_model(root: Path, model: str) -> None:
    p = root / "proc" / "device-tree"
    p.mkdir(parents=True, exist_ok=True)
    # The device tree stores a NUL-terminated string; the doctor must strip it.
    (p / "model").write_text(model + "\x00", encoding="utf-8")


def runner_returning(mapping: dict[str, str | None]):
    """A command runner keyed on the first word of the command."""
    def run(cmd):
        return mapping.get(cmd[0])
    return run


# --------------------------------------------------------------------------
# Connector enumeration
# --------------------------------------------------------------------------

def test_no_sysfs_yields_no_connectors(tmp_path):
    assert find_connectors(tmp_path) == []


def test_connectors_sorted_and_parsed(tmp_path):
    make_connector(tmp_path, "HDMI-A-2", edid=full_edid())
    make_connector(tmp_path, "HDMI-A-1", status="connected", edid=b"")
    names = [c.name for c in find_connectors(tmp_path)]
    assert names == ["HDMI-A-1", "HDMI-A-2"], "near port must report first"


def test_render_node_without_connector_suffix_ignored(tmp_path):
    (tmp_path / "sys" / "class" / "drm" / "card0").mkdir(parents=True)
    (tmp_path / "sys" / "class" / "drm" / "renderD128").mkdir(parents=True)
    make_connector(tmp_path, "HDMI-A-1", edid=full_edid())
    assert [c.name for c in find_connectors(tmp_path)] == ["HDMI-A-1"]


def test_live_requires_both_connected_and_edid(tmp_path):
    make_connector(tmp_path, "HDMI-A-1", status="connected", edid=b"")
    make_connector(tmp_path, "HDMI-A-2", status="disconnected", edid=full_edid())
    assert [c.live for c in find_connectors(tmp_path)] == [False, False]


def test_short_edid_read_is_not_live(tmp_path):
    """A partial read is a broken DDC transfer, not a modest monitor."""
    make_connector(tmp_path, "HDMI-A-1", edid=bytes(64))
    assert find_connectors(tmp_path)[0].live is False


# --------------------------------------------------------------------------
# Fault 2 — EDID
# --------------------------------------------------------------------------

def test_edid_pass_when_a_port_answers(tmp_path):
    make_connector(tmp_path, "HDMI-A-1", edid=full_edid())
    check = check_hdmi_edid(tmp_path)
    assert check.status == PASS
    assert "256 bytes" in check.detail


def test_edid_fail_is_the_dead_ddc_port(tmp_path):
    """The bring-up signature: connected, zero bytes, and a working far port."""
    make_connector(tmp_path, "HDMI-A-1", status="connected", edid=b"")
    make_connector(tmp_path, "HDMI-A-2", status="disconnected", edid=b"")
    check = check_hdmi_edid(tmp_path)
    assert check.status == FAIL
    assert "0 bytes" in check.detail
    # The remedy has to name the other port and insist on a reboot, because
    # SDL inherits the mode the CRTC negotiated at boot.
    assert "HDMI-A-2" in check.remedy
    assert "reboot" in check.remedy.lower()


def test_edid_warn_when_nothing_is_plugged_in(tmp_path):
    make_connector(tmp_path, "HDMI-A-1", status="disconnected", edid=b"")
    assert check_hdmi_edid(tmp_path).status == WARN


def test_edid_skips_off_pi(tmp_path):
    assert check_hdmi_edid(tmp_path).status == SKIP


# --------------------------------------------------------------------------
# Fault 2 — the ALSA half
# --------------------------------------------------------------------------

def test_alsa_skips_without_hdmi_sinks(tmp_path):
    make_asound_cards(tmp_path, " 0 [Headphones     ]: bcm2835 - Headphones\n")
    assert check_alsa_card(tmp_path).status == SKIP


def test_alsa_warns_when_two_sinks_and_no_conf(tmp_path):
    make_asound_cards(tmp_path, PI5_CARDS)
    check = check_alsa_card(tmp_path)
    assert check.status == WARN
    assert "card 0" in check.detail and "card 1" in check.detail


def test_alsa_passes_when_conf_pins_a_real_sink(tmp_path):
    make_asound_cards(tmp_path, PI5_CARDS)
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "asound.conf").write_text(
        "defaults.pcm.card 1\ndefaults.ctl.card 1\n", encoding="utf-8")
    assert check_alsa_card(tmp_path).status == PASS


def test_alsa_fails_when_conf_pins_a_non_sink(tmp_path):
    make_asound_cards(tmp_path, PI5_CARDS)
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "asound.conf").write_text(
        "defaults.pcm.card 7\n", encoding="utf-8")
    check = check_alsa_card(tmp_path)
    assert check.status == FAIL
    assert "card 7" in check.detail


def test_alsa_single_card_zero_needs_no_conf(tmp_path):
    make_asound_cards(tmp_path, " 0 [vc4hdmi        ]: vc4-hdmi - vc4-hdmi\n")
    assert check_alsa_card(tmp_path).status == PASS


# --------------------------------------------------------------------------
# The video= pin — the card-swap trap
# --------------------------------------------------------------------------

def test_mode_pin_matching_live_output_passes(tmp_path):
    make_connector(tmp_path, "HDMI-A-2", edid=full_edid())
    make_cmdline(tmp_path, "console=serial0 video=HDMI-A-2:1920x1080@60D rootwait")
    assert check_mode_pinned(tmp_path).status == PASS


def test_mode_pin_on_a_dead_connector_fails(tmp_path):
    """Exactly what a card swap produces: pinned to a port this board lacks."""
    make_connector(tmp_path, "HDMI-A-1", edid=full_edid())
    make_cmdline(tmp_path, "video=HDMI-A-2:1920x1080@60D rootwait")
    check = check_mode_pinned(tmp_path)
    assert check.status == FAIL
    assert "HDMI-A-1" in check.remedy


def test_missing_pin_suggests_the_live_connector(tmp_path):
    make_connector(tmp_path, "HDMI-A-2", edid=full_edid())
    make_cmdline(tmp_path, "console=serial0 rootwait")
    check = check_mode_pinned(tmp_path)
    assert check.status == WARN
    assert "video=HDMI-A-2:1920x1080@60D" in check.remedy


def test_mode_pin_skips_without_cmdline(tmp_path):
    assert check_mode_pinned(tmp_path).status == SKIP


# --------------------------------------------------------------------------
# Fault 3 — regulatory domain
# --------------------------------------------------------------------------

REG_SPLIT = """\
global
country US: DFS-FCC

phy#0
country 00: DFS-UNSET
"""

REG_OK = """\
global
country US: DFS-FCC

phy#0
country US: DFS-FCC
"""


def test_regdom_detects_the_dfs_unset_split():
    check = check_wifi_regdom(runner_returning({"iw": REG_SPLIT}))
    assert check.status == FAIL
    assert "00" in check.detail
    # The critical instruction: a reboot, not a command.
    assert "cold boot" in check.remedy


def test_regdom_pass_when_aligned():
    assert check_wifi_regdom(runner_returning({"iw": REG_OK})).status == PASS


def test_regdom_skips_without_iw():
    assert check_wifi_regdom(runner_returning({"iw": None})).status == SKIP


def test_regdom_skips_on_unparsable_output():
    assert check_wifi_regdom(runner_returning({"iw": "nonsense"})).status == SKIP


# --------------------------------------------------------------------------
# Fault 4 — authorized_keys
# --------------------------------------------------------------------------

def test_authorized_keys_zero_bytes_fails(tmp_path):
    p = tmp_path / "authorized_keys"
    p.write_text("", encoding="utf-8")
    check = check_authorized_keys(p)
    assert check.status == FAIL
    assert "0 bytes" in check.detail
    assert "ssh-keygen -lf" in check.remedy


def test_authorized_keys_comments_only_fails(tmp_path):
    p = tmp_path / "authorized_keys"
    p.write_text("# just a comment\n\n", encoding="utf-8")
    assert check_authorized_keys(p).status == FAIL


def test_authorized_keys_counts_real_keys(tmp_path):
    p = tmp_path / "authorized_keys"
    p.write_text("ssh-ed25519 AAAAC3Nz key-one\nssh-rsa AAAAB3Nz key-two\n",
                 encoding="utf-8")
    check = check_authorized_keys(p)
    assert check.status == PASS
    assert "2 key(s)" in check.detail


def test_authorized_keys_absent_skips(tmp_path):
    assert check_authorized_keys(tmp_path / "nope").status == SKIP


# --------------------------------------------------------------------------
# Overlay — the boot=overlay false negative
# --------------------------------------------------------------------------

def test_overlay_detected_from_mounts(tmp_path):
    make_mounts(tmp_path, "overlay")
    assert check_overlay(tmp_path).status == PASS


def test_overlay_absent_is_a_warning_not_a_fault(tmp_path):
    make_mounts(tmp_path, "ext4")
    check = check_overlay(tmp_path)
    assert check.status == WARN
    assert "do_overlayfs 0" in check.remedy


def test_overlay_skips_without_proc_mounts(tmp_path):
    assert check_overlay(tmp_path).status == SKIP


# --------------------------------------------------------------------------
# Power
# --------------------------------------------------------------------------

def test_power_clean():
    check = check_power(runner_returning({"vcgencmd": "throttled=0x0\n"}))
    assert check.status == PASS


def test_power_live_undervoltage_is_a_fault():
    check = check_power(runner_returning({"vcgencmd": "throttled=0x50005\n"}))
    assert check.status == FAIL
    assert "under-voltage now" in check.detail


def test_power_historic_only_is_a_warning():
    check = check_power(runner_returning({"vcgencmd": "throttled=0x50000\n"}))
    assert check.status == WARN
    assert "has occurred" in check.detail


def test_power_skips_without_vcgencmd():
    assert check_power(runner_returning({"vcgencmd": None})).status == SKIP


# --------------------------------------------------------------------------
# Deployment state
# --------------------------------------------------------------------------

def test_service_enabled(tmp_path):
    units = tmp_path / "etc" / "systemd" / "system"
    (units / "multi-user.target.wants").mkdir(parents=True)
    (units / "lilypad.service").write_text("[Unit]\n", encoding="utf-8")
    (units / "multi-user.target.wants" / "lilypad.service").write_text(
        "[Unit]\n", encoding="utf-8")
    assert check_service(tmp_path).status == PASS


def test_service_installed_but_not_enabled(tmp_path):
    units = tmp_path / "etc" / "systemd" / "system"
    units.mkdir(parents=True)
    (units / "lilypad.service").write_text("[Unit]\n", encoding="utf-8")
    check = check_service(tmp_path)
    assert check.status == FAIL
    assert "systemctl enable" in check.remedy


def test_sounds_present(tmp_path):
    d = tmp_path / "opt" / "lilypad" / "sounds"
    d.mkdir(parents=True)
    (d / "a.wav").write_bytes(b"RIFF")
    assert check_sounds(tmp_path).status == PASS


def test_sounds_directory_empty_fails(tmp_path):
    (tmp_path / "opt" / "lilypad" / "sounds").mkdir(parents=True)
    assert check_sounds(tmp_path).status == FAIL


# --------------------------------------------------------------------------
# Board model and card swap
# --------------------------------------------------------------------------

def test_model_strips_device_tree_nul(tmp_path):
    make_model(tmp_path, "Raspberry Pi 5 Model B Rev 1.1")
    assert read_model(tmp_path) == "Raspberry Pi 5 Model B Rev 1.1"


def test_model_pass_on_pi5(tmp_path):
    make_model(tmp_path, "Raspberry Pi 5 Model B Rev 1.1")
    assert check_model(tmp_path).status == PASS


@pytest.mark.parametrize("model", [
    "Raspberry Pi 2 Model B Rev 1.1",
    "Raspberry Pi Model B Plus Rev 1.2",
    "Raspberry Pi Zero W Rev 1.1",
])
def test_model_rejects_32bit_only_boards(tmp_path, model):
    """64-bit Raspberry Pi OS needs a Pi 3 or newer — say so before it 'fails
    to boot' and looks like a bad flash."""
    make_model(tmp_path, model)
    check = check_model(tmp_path)
    assert check.status == FAIL
    assert "64-bit" in check.remedy


@pytest.mark.parametrize("model", [
    "Raspberry Pi 3 Model B Rev 1.2",
    "Raspberry Pi 4 Model B Rev 1.4",
    "Raspberry Pi Zero 2 W Rev 1.0",
])
def test_model_accepts_64bit_capable_boards(tmp_path, model):
    make_model(tmp_path, model)
    assert check_model(tmp_path).status == PASS


def test_stamp_roundtrips_the_same_board(tmp_path):
    make_model(tmp_path, "Raspberry Pi 4 Model B Rev 1.4")
    make_connector(tmp_path, "HDMI-A-1", edid=full_edid())
    make_asound_cards(tmp_path, PI3_CARDS)
    write_stamp(tmp_path)
    assert check_card_swap(tmp_path).status == PASS


def test_stamp_notices_the_swap_into_the_pi5(tmp_path):
    """The whole point: set up on the test Pi, then moved into the Pi 5."""
    make_model(tmp_path, "Raspberry Pi 4 Model B Rev 1.4")
    make_connector(tmp_path, "HDMI-A-1", edid=full_edid())
    make_asound_cards(tmp_path, PI3_CARDS)
    write_stamp(tmp_path)

    make_model(tmp_path, "Raspberry Pi 5 Model B Rev 1.1")
    check = check_card_swap(tmp_path)
    assert check.status == WARN
    assert "Raspberry Pi 4" in check.detail and "Raspberry Pi 5" in check.detail
    assert "video=" in check.remedy


def test_card_swap_skips_without_a_stamp(tmp_path):
    make_model(tmp_path, "Raspberry Pi 5 Model B Rev 1.1")
    assert check_card_swap(tmp_path).status == SKIP


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------

def test_run_all_is_all_skips_on_a_bare_root(tmp_path):
    report = run_all(tmp_path, runner_returning({}))
    assert report.ok
    assert all(c.status == SKIP for c in report.checks)


def test_run_all_surfaces_a_real_fault(tmp_path):
    make_connector(tmp_path, "HDMI-A-1", status="connected", edid=b"")
    report = run_all(tmp_path, runner_returning({}))
    assert not report.ok
    assert [c.name for c in report.failed] == ["HDMI EDID"]


def test_run_all_uses_an_explicit_home(tmp_path):
    home = tmp_path / "home" / "someone"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "authorized_keys").write_text("", encoding="utf-8")
    report = run_all(tmp_path, runner_returning({}), home=home)
    assert any(c.name == "SSH authorized_keys" and c.status == FAIL
               for c in report.checks)


def test_report_ok_ignores_warnings():
    report = Report([Check("a", WARN, "d", "r"), Check("b", PASS, "d")])
    assert report.ok and report.warned


def test_format_shows_remedies_only_for_problems():
    text = format_report(Report([
        Check("Good", PASS, "fine", "unused remedy"),
        Check("Bad", FAIL, "broken", "do the thing"),
    ]))
    assert "unused remedy" not in text
    assert "do the thing" in text
    assert "1 fault(s) need attention" in text


def test_format_reports_all_clear():
    assert "All checks passed" in format_report(Report([Check("a", PASS, "d")]))


def test_format_reports_warnings_without_faults():
    text = format_report(Report([Check("a", WARN, "d", "r")]))
    assert "No faults" in text and "1 warning(s)" in text


def test_unreadable_sysfs_file_is_not_fatal(tmp_path, monkeypatch):
    """Sysfs reads race with hot-plug; a raising read must not crash the doctor."""
    make_connector(tmp_path, "HDMI-A-1", edid=full_edid())

    def boom(*_a, **_k):
        raise OSError("gone")

    monkeypatch.setattr(Path, "read_bytes", boom)
    assert find_connectors(tmp_path)[0].edid_bytes == 0


def test_shell_runner_handles_a_missing_binary():
    assert doctor.shell_runner(["definitely-not-a-real-binary-xyz"]) is None


def test_main_exit_code_reflects_faults(tmp_path, capsys):
    make_connector(tmp_path, "HDMI-A-1", status="connected", edid=b"")
    assert doctor.main(["--root", str(tmp_path)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_exit_zero_when_clean(tmp_path, capsys):
    assert doctor.main(["--root", str(tmp_path)]) == 0
    assert "All checks passed" in capsys.readouterr().out
