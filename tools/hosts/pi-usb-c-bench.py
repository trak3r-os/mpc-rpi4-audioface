#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Temporary Pi 4 internal-xHCI comparison, invoked through tools/deploy.sh.

An operator must approve the boot change and arrange suitable power/data wiring.
No service, kernel, network or audio setting is changed; reboot separately.
"""
import os
from pathlib import Path
import sys
import tempfile


def host_config(original):
    section = "all"
    result = []
    changed = 0
    for line in original.splitlines(keepends=True):
        setting = line.split("#", 1)[0].strip()
        if setting.startswith("[") and setting.endswith("]"):
            section = setting[1:-1]
        if setting == "dtoverlay=dwc2,dr_mode=peripheral":
            if section != "pi4":
                raise ValueError("peripheral overlay must be explicitly under [pi4]")
            result.append("otg_mode=1\n")
            changed += 1
        else:
            if setting.startswith("otg_mode=") and section != "cm4":
                raise ValueError("unexpected existing otg_mode setting")
            result.append(line)
    if changed != 1:
        raise ValueError("expected exactly one Pi 4 peripheral overlay")
    return "".join(result)


def change_role(role, config, backup):
    current = config.read_bytes()
    original_path = backup / "config.txt.original"
    proposed_path = backup / "config.txt.host"
    if role == "host":
        if not backup.exists():
            proposed = host_config(current.decode()).encode()
            backup.mkdir(mode=0o700, parents=True)
            original_path.write_bytes(current)
            proposed_path.write_bytes(proposed)
        original = original_path.read_bytes()
        proposed = proposed_path.read_bytes()
        if proposed != host_config(original.decode()).encode():
            raise ValueError("backup pair is inconsistent")
        target = proposed
    elif role == "restore":
        original = original_path.read_bytes()
        proposed = proposed_path.read_bytes()
        if proposed != host_config(original.decode()).encode():
            raise ValueError("backup pair is inconsistent")
        target = original
    else:
        raise ValueError("role must be host or restore")
    if current not in (original, proposed):
        raise ValueError("boot config changed since backup; refusing to overwrite")
    if current != target:
        with tempfile.NamedTemporaryFile(dir=config.parent, delete=False) as staged:
            staged.write(target)
            staged.flush()
            os.fsync(staged.fileno())
        os.replace(staged.name, config)
    return target


if __name__ == "__main__":
    if "Raspberry Pi 4 Model B" not in Path("/proc/device-tree/model").read_text():
        raise SystemExit("USB-C bench requires a Raspberry Pi 4 Model B")
    backup = Path("/var/backups/rpi-audio-usbc-bench")
    change_role(sys.argv[1], Path("/boot/firmware/config.txt"), backup)
    print("USB-C bench:", sys.argv[1], "prepared; backup:", backup, "(reboot separately)")
