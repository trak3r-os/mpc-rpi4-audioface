# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/deploy.sh against a Pi with a read-only root: ssh and rsync are fakes that only log what they get."""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FAKE_SSH = """#!/bin/sh
printf '%s\\n' "$*" >> "$LOG"
case "$*" in
  *overlayroot=tmpfs*) exit "$OVERLAY_RC" ;;
esac
exit 0
"""
FAKE_RSYNC = """#!/bin/sh
printf 'rsync %s\\n' "$*" >> "$LOG"
"""


@pytest.fixture
def deploy(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("ssh", FAKE_SSH), ("rsync", FAKE_RSYNC)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "log"

    def run(*args, overlay=False):
        env = {**{k: v for k, v in os.environ.items() if not k.startswith("GADGET_")},
               "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log), "PI_HOST": "pi.invalid",
               "OVERLAY_RC": "0" if overlay else "1"}
        done = subprocess.run([str(REPO / "tools/deploy.sh"), *args], env=env, capture_output=True, text=True,
                              timeout=60)
        return done, (log.read_text().splitlines() if log.exists() else [])

    return run


def test_a_read_only_pi_is_not_deployed_to_without_volatile(deploy):
    done, calls = deploy("--enable", overlay=True)
    assert done.returncode == 1 and "disable_overlayfs" in done.stderr and "--read-only" in done.stderr
    assert not [c for c in calls if c.startswith("rsync") or "install.sh" in c]
    done, calls = deploy("--ui-only", overlay=True)
    assert done.returncode == 1 and not [c for c in calls if c.startswith("rsync")]


def test_volatile_deploys_into_the_overlay_and_says_so(deploy):
    done, calls = deploy("--volatile", overlay=True)
    assert done.returncode == 0, done.stderr
    assert "until the next reboot" in done.stderr
    assert [c for c in calls if "sudo -n env" in c and "--volatile" in c]


def test_read_only_and_watchdog_reach_install(deploy):
    done, calls = deploy("--read-only", "--hw-watchdog", "15")
    assert done.returncode == 0, done.stderr
    install = [c for c in calls if "sudo -n env" in c]
    assert len(install) == 1 and "--read-only" in install[0] and "--hw-watchdog 15" in install[0]
    assert "--no-enable" in install[0]


@pytest.mark.parametrize("args", [["--hw-watchdog", "15;reboot"], ["--ui-only", "--read-only"],
                                  ["--ui-only", "--hw-watchdog", "off"], ["--usb-c-bench", "host", "--volatile"]])
def test_bad_combinations_stop_before_the_pi(deploy, args):
    done, calls = deploy(*args)
    assert done.returncode == 2 and calls == []
