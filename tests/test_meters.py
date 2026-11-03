# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge/rpi-audio-ui"))
import meters  # noqa: E402
import ui  # noqa: E402


@pytest.mark.parametrize("line", ['{}', '[]', '{"in":NaN,"out":0}', '{"in":-1,"out":0}',
                                  '{"in":true,"out":0}', 'not json'])
def test_bad_samples_are_unavailable(line):
    assert meters.packet(line) is None


def test_real_amplitudes_display_dbfs_silence_unavailable_and_clipping():
    assert ui.meter_row("IN", 0.25).meter[2] == "-12"
    assert ui.meter_row("IN", 0.5).meter[2] == "-6"
    assert ui.meter_row("IN", 0).meter[1:3] == (0, "-inf")
    assert ui.meter_row("OUT", None).meter[1:3] == (-1, "--")
    assert ui.meter_row("OUT", 1.25).meter[1:] == (18, "CLIP", True)


def test_ports_follow_the_engine_and_do_not_open_alsa():
    assert meters.ports({}) == ()
    assert meters.ports({"jack_ready": True, "gadget_channels": 2}) == (
        "in=system:playback_1", "out=system:capture_1", "in=system:playback_2", "out=system:capture_2")
    status = {"jack_ready": True, "standalone": {"channels": 2},
              "devices": [{"in": {"client": "guitar_in", "running": True, "channels": 2}}]}
    assert meters.ports(status) == ("in=guitar_in:capture_1", "in=guitar_in:capture_2",
                                    "out=system:playback_1", "out=system:playback_2")


def test_nonblocking_partial_frames_stale_readings_and_process_cleanup(tmp_path):
    helper = tmp_path / "meter"
    sample = json.dumps({"in": 0.25, "out": None})
    helper.write_text(f"#!{sys.executable}\nimport sys,time\n"
                      f"sys.stdout.write({sample[:8]!r});sys.stdout.flush()\ntime.sleep(0.1)\n"
                      f"sys.stdout.write({(sample[8:] + chr(10))!r});sys.stdout.flush()\ntime.sleep(5)\n")
    helper.chmod(0o755)
    reader = meters.Reader(helper)
    status = {"jack_ready": True, "gadget_channels": 1}
    try:
        start = time.monotonic()
        assert reader.read(status, start) == {}
        assert time.monotonic() - start < 0.5
        deadline = start + 2
        while time.monotonic() < deadline:
            value = reader.read(status, time.monotonic())
            if value:
                break
            time.sleep(0.01)
        else:
            pytest.fail("native helper reader did not assemble its partial JSON frame")
        assert value == {"in": 0.25, "out": None}
        proc = reader.proc
        assert reader.read(status, time.monotonic() + meters.STALE_S + 1) == {}
        assert reader.read(status, time.monotonic(), enabled=False) == {}
        assert reader.proc is None
    finally:
        reader.close()
    assert proc.poll() is not None and proc.stdout.closed


def test_inactive_audio_never_starts_a_meter_process():
    def forbidden(*args, **kwargs):
        pytest.fail("meter started without an active server")
    reader = meters.Reader(popen=forbidden)
    assert reader.read({}, 0) == {}
    assert reader.read({"jack_ready": True, "gadget_channels": 2}, 1, enabled=False) == {}
