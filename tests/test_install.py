# SPDX-License-Identifier: GPL-3.0-or-later
"""install.sh: argument parsing, the config/.new logic, the boot overlay and uninstall,
all in a temporary root (RPI_AUDIO_ROOT: nothing but file operations runs)."""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "install.sh"
OVERLAY = "dtoverlay=dwc2,dr_mode=peripheral"


def run(root, *args, stdin=subprocess.DEVNULL):
    env = dict(os.environ, RPI_AUDIO_ROOT=str(root))
    return subprocess.run([str(SCRIPT), *args], env=env, stdin=stdin,
                          capture_output=True, text=True)


@pytest.fixture
def root(tmp_path):
    return tmp_path


def boot(root, text, new_style=True):
    d = root / ("boot/firmware" if new_style else "boot")
    d.mkdir(parents=True)
    f = d / "config.txt"
    f.write_text(text)
    return f


def test_bad_arguments(root):
    for args in (["--bogus"], ["--purge"], ["--host"], ["--uninstall", "--host", "x"]):
        assert run(root, *args).returncode != 0
    r = run(root, "--bogus")
    assert r.returncode == 2 and "usage:" in r.stderr
    r = run(root, "--host", "nonexistent")
    assert r.returncode == 1 and "no tools/hosts/nonexistent.toml" in r.stderr
    r = run(root, "--host", "../x")
    assert r.returncode == 1 and "invalid host name" in r.stderr


def test_fresh_install_lays_out_files(root):
    r = run(root, "--no-boot-config", "--host", "akai-force")
    assert r.returncode == 0, r.stderr
    lib = root / "usr/local/lib/rpi-audio"
    for name in ("rpi-audio-gadget", "rpi-audio-keepalive", "tonegen.py", "rpi-audiod"):
        assert os.access(lib / name, os.X_OK), name
    for name in ("audiod.py", "midi.py", "presets.py", "routing.py", "usb.py"):
        assert (lib / name).is_file(), name
    assert os.readlink(root / "usr/local/bin/rpi-audiod") == "/usr/local/lib/rpi-audio/rpi-audiod"
    etc = root / "etc/rpi-audio"
    assert (etc / "gadget.env").read_bytes() == (REPO / "config/gadget.env").read_bytes()
    assert (etc / "rpi-audio.toml").is_file()
    assert (etc / "rpi-audio.d/akai-force.toml").is_file()
    assert (etc / "devices.d/valeton-gp150.toml").is_file()
    for u in ("rpi-audio-gadget", "rpi-audiod", "rpi-audio-keepalive", "rpi-audio-cpu"):
        assert (root / f"etc/systemd/system/{u}.service").is_file()
    assert (lib / "VERSION").read_text().startswith((REPO / "VERSION").read_text().strip())
    assert (root / "etc/modules-load.d/rpi-audio.conf").read_text() == "snd-seq\nsnd-seq-midi\n"
    assert "Storage=persistent" in (root / "etc/systemd/journald.conf.d/rpi-audio.conf").read_text()
    assert "next: connect the Pi's USB-C" in r.stdout


def test_config_kept_and_new_written(root):
    assert run(root, "--no-boot-config").returncode == 0
    env = root / "etc/rpi-audio/gadget.env"
    mine = "GADGET_CHANNELS=8\n"
    env.write_text(mine)
    r = run(root, "--no-boot-config")
    assert env.read_text() == mine
    assert (root / "etc/rpi-audio/gadget.env.new").read_bytes() == (REPO / "config/gadget.env").read_bytes()
    assert "gadget.env.new" in r.stdout
    # Identical to the repo's again: no notice, a stale .new goes away.
    env.write_bytes((REPO / "config/gadget.env").read_bytes())
    r = run(root, "--no-boot-config")
    assert not (root / "etc/rpi-audio/gadget.env.new").exists()
    assert ".new" not in r.stdout


def test_force_config_overwrites(root):
    assert run(root, "--no-boot-config").returncode == 0
    env = root / "etc/rpi-audio/gadget.env"
    env.write_text("GADGET_CHANNELS=8\n")
    (root / "etc/rpi-audio/gadget.env.new").write_text("stale\n")
    r = run(root, "--no-boot-config", "--force-config")
    assert env.read_bytes() == (REPO / "config/gadget.env").read_bytes()
    assert not (root / "etc/rpi-audio/gadget.env.new").exists()
    assert "overwrote" in r.stdout


def test_profiles_always_installed_others_kept(root):
    assert run(root, "--no-boot-config").returncode == 0
    d = root / "etc/rpi-audio/devices.d"
    mine = d / "mine.toml"
    mine.write_text("x = 1\n")
    (d / "valeton-gp150.toml").write_text("changed\n")
    assert run(root, "--no-boot-config").returncode == 0
    assert mine.read_text() == "x = 1\n"
    assert (d / "valeton-gp150.toml").read_bytes() == (REPO / "config/devices.d/valeton-gp150.toml").read_bytes()


def test_overlay_added_with_yes(root):
    cfg = boot(root, "dtparam=audio=on\n[cm4]\notg_mode=1\n[all]\ndtoverlay=vc4-kms-v3d")  # no final newline
    original = cfg.read_text()
    r = run(root, "-y")
    assert r.returncode == 0, r.stderr
    assert cfg.read_text() == original + "\n" + OVERLAY + "\n"
    backups = list(cfg.parent.glob("config.txt.rpi-audio-*"))
    assert len(backups) == 1 and backups[0].read_text() == original
    assert "reboot" in r.stdout
    # A second run finds it there (still no UDC: reboot pending) and adds nothing.
    r = run(root, "-y")
    assert cfg.read_text().count(OVERLAY) == 1
    assert len(list(cfg.parent.glob("config.txt.rpi-audio-*"))) == 1
    assert "reboot" in r.stdout


def test_overlay_opens_all_section_when_last_is_other(root):
    cfg = boot(root, "[all]\ndtparam=audio=on\n[cm4]\notg_mode=1\n", new_style=False)
    assert run(root, "-y").returncode == 0
    assert cfg.read_text().endswith("[cm4]\notg_mode=1\n[all]\n" + OVERLAY + "\n")


def test_overlay_not_added_without_yes_or_terminal(root):
    cfg = boot(root, "[all]\n")
    r = run(root)  # stdin is not a terminal
    assert cfg.read_text() == "[all]\n"
    assert not list(cfg.parent.glob("config.txt.*"))
    assert "not adding it" in r.stderr


def test_overlay_skipped_by_flag_udc_or_comment(root):
    cfg = boot(root, "[all]\n# " + OVERLAY + "\n")
    before = cfg.read_text()
    run(root, "-y", "--no-boot-config")
    assert cfg.read_text() == before
    (root / "sys/class/udc/fe980000.usb").mkdir(parents=True)
    (root / "sys/class/udc/fe980000.usb/state").write_text("not attached\n")
    r = run(root, "-y")
    assert cfg.read_text() == before
    assert "not attached" in r.stdout and "connect the Pi's USB-C" in r.stdout


def test_overlay_not_edited_when_other_dwc2_line(root):
    cfg = boot(root, "[all]\ndtoverlay=dwc2\n")
    r = run(root, "-y")
    assert cfg.read_text() == "[all]\ndtoverlay=dwc2\n"
    assert "by hand" in r.stderr


def test_uninstall_and_purge(root):
    assert run(root, "--no-boot-config", "--host", "akai-force").returncode == 0
    r = run(root, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert not (root / "usr/local/lib/rpi-audio").exists()
    assert not (root / "usr/local/bin/rpi-audiod").is_symlink()
    assert not list((root / "etc/systemd/system").glob("rpi-audio*"))
    assert not (root / "etc/modules-load.d/rpi-audio.conf").exists()
    assert not (root / "etc/systemd/journald.conf.d/rpi-audio.conf").exists()
    assert (root / "etc/rpi-audio/gadget.env").exists()
    r = run(root, "--uninstall", "--purge")
    assert r.returncode == 0
    assert not (root / "etc/rpi-audio").exists()


def test_uninstall_prints_how_to_revert_overlay(root):
    boot(root, "[all]\n")
    r = run(root, "--uninstall")
    assert OVERLAY in r.stdout


def test_version_takes_the_commit_given(root):
    env = dict(os.environ, RPI_AUDIO_ROOT=str(root), RPI_AUDIO_COMMIT="abc1234")
    r = subprocess.run([str(SCRIPT), "--no-boot-config"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    version = (REPO / "VERSION").read_text().strip()
    assert (root / "usr/local/lib/rpi-audio/VERSION").read_text() == f"{version} (abc1234)\n"


def cmdline(root, text):
    f = root / "boot/firmware/cmdline.txt"
    f.write_text(text)
    return f


def test_tune_boot_only_when_asked(root):
    cfg = boot(root, "[all]\ndtparam=audio=on\n" + OVERLAY + "\n")
    cl = cmdline(root, "console=tty1 root=PARTUUID=1234-02 rootwait\n")
    before = cfg.read_text(), cl.read_text()
    r = run(root, "-y")
    assert r.returncode == 0, r.stderr
    assert (cfg.read_text(), cl.read_text()) == before


def test_tune_boot_edits_with_backups_once(root):
    cfg = boot(root, "dtparam=audio=on\n[all]\n" + OVERLAY + "\n")
    cl = cmdline(root, "console=tty1 root=PARTUUID=1234-02 rootwait\n")
    r = run(root, "--tune-boot")
    assert r.returncode == 0, r.stderr
    assert cfg.read_text() == "dtparam=audio=off\n[all]\n" + OVERLAY + "\n"
    assert cl.read_text() == "console=tty1 root=PARTUUID=1234-02 rootwait threadirqs\n"
    assert len(list(cfg.parent.glob("config.txt.rpi-audio-*"))) == 1
    assert len(list(cl.parent.glob("cmdline.txt.rpi-audio-*"))) == 1
    assert "takes effect at the next reboot" in r.stdout
    r = run(root, "--tune-boot")
    assert r.returncode == 0, r.stderr
    assert cl.read_text().count("threadirqs") == 1
    assert cfg.read_text().count("dtparam=audio") == 1
    assert "takes effect at the next reboot" not in r.stdout


def test_tune_boot_adds_audio_off_under_all(root):
    cfg = boot(root, "[cm4]\notg_mode=1\n[all]\n" + OVERLAY + "\n[pi5]\nfoo=1")
    cmdline(root, "rootwait")
    r = run(root, "--tune-boot")
    assert r.returncode == 0, r.stderr
    assert cfg.read_text().endswith("[pi5]\nfoo=1\n[all]\ndtparam=audio=off\n")


def test_tune_boot_conflicts_with_no_boot_config(root):
    assert run(root, "--tune-boot", "--no-boot-config").returncode == 2
