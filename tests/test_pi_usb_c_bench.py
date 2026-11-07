# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pi_usb_c_bench", Path(__file__).resolve().parents[1] / "tools/hosts/pi-usb-c-bench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

ORIGINAL = ("[cm4]\notg_mode=1\n[pi4]\ndtoverlay=dwc2,dr_mode=peripheral\n"
            "[all]\ndtparam=i2c_arm=on\ndtoverlay=hifiberry-dac\n")


def test_roundtrip_preserves_original_and_repeated_apply(tmp_path):
    config = tmp_path / "config.txt"
    config.write_text(ORIGINAL)
    backup = tmp_path / "backup"
    bench.change_role("host", config, backup)
    assert config.read_text() == ORIGINAL.replace("dtoverlay=dwc2,dr_mode=peripheral", "otg_mode=1")
    bench.change_role("host", config, backup)
    bench.change_role("restore", config, backup)
    bench.change_role("restore", config, backup)
    assert config.read_text() == ORIGINAL


def test_restore_refuses_to_destroy_later_edits(tmp_path):
    config = tmp_path / "config.txt"
    config.write_text(ORIGINAL)
    backup = tmp_path / "backup"
    bench.change_role("host", config, backup)
    config.write_text(config.read_text() + "# later operator edit\n")
    edited = config.read_bytes()
    with pytest.raises(ValueError, match="changed since backup"):
        bench.change_role("restore", config, backup)
    assert config.read_bytes() == edited


@pytest.mark.parametrize("text", [
    "[all]\ndtoverlay=dwc2,dr_mode=peripheral\n",
    ORIGINAL + "[pi4]\notg_mode=0\n",
    ORIGINAL.replace("dtoverlay=dwc2,dr_mode=peripheral", ""),
])
def test_rejects_ambiguous_or_missing_settings(text):
    with pytest.raises(ValueError):
        bench.host_config(text)
