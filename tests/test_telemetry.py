# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware detection against temporary proc/sys trees; no network, GPIO or audio changes."""

import subprocess
import sys
from concurrent.futures import Future
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge/rpi-audio-ui"))
import telemetry  # noqa: E402


def put(root, name, text=""):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_collect_wifi_usb_and_physical_audio_midi_cards(tmp_path):
    proc, sys = tmp_path / "proc", tmp_path / "sys"
    (sys / "class/net/wlan0").mkdir(parents=True)
    put(sys, "class/udc/controller/state", "configured\n")
    put(proc, "net/wireless", "wlan0: 0000 56. -54. -256\n")
    put(proc, "asound/card0/id", "UAC2Gadget")
    put(proc, "asound/card1/id", "sndrpihifiberry")
    put(proc, "asound/card2/id", "GP150")
    put(proc, "asound/card2/usbid", "1234:5678")
    put(proc, "asound/card2/midi0", "GP-150")
    put(proc, "asound/card2/stream0", "Valeton GP-150 at usb-1, high speed : USB Audio\n"
        "Playback:\n Channels: 2\n Rates: 48000\nCapture:\n Channels: 2\n Rates: 48000\n")
    put(proc, "asound/card2/stream1", "Capture:\n Channels: 8\n Rates: 48000\n")
    put(proc, "asound/card3/id", "Keys")
    put(proc, "asound/card3/usbid", "abcd:1234")
    put(proc, "asound/card3/midi0", "Keys")

    def run(args, **kwargs):
        assert "--rescan" not in args and kwargs["timeout"] == 2
        return subprocess.CompletedProcess(args, 0, "100 (connected)\nbender_5G\n192.168.2.229/24\n")

    result = telemetry.collect(proc, sys, run)
    assert result["usb_state"] == "configured"
    assert result["wifi"] == {"state": "up", "name": "bender_5G", "ip": "192.168.2.229", "signal": 80}
    dac, audio, midi = result["devices"]
    assert dac["local"] and dac["name"] == "pHAT DAC"
    assert audio["name"] == "Valeton GP-150" and audio["in"]["channels"] == 8
    assert audio["out"]["channels"] == 2 and audio["midi"]
    assert midi["midi"] and "in" not in midi and "out" not in midi


def test_wifi_off_disconnected_missing_and_unavailable_tools(tmp_path):
    proc, sys = tmp_path / "proc", tmp_path / "sys"
    (sys / "class/net/wlan0").mkdir(parents=True)

    def disconnected(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "30 (disconnected)\n--\n")

    assert telemetry.collect(proc, sys, disconnected)["wifi"]["state"] == "down"
    put(sys, "class/rfkill/rfkill1/type", "wlan")
    put(sys, "class/rfkill/rfkill1/soft", "1")
    assert telemetry.collect(proc, sys, disconnected)["wifi"]["state"] == "off"

    def missing(*args, **kwargs):
        raise FileNotFoundError("nmcli")

    assert telemetry.collect(proc, sys, missing)["wifi"]["state"] == "off"
    put(sys, "class/rfkill/rfkill1/soft", "0")
    assert telemetry.collect(proc, sys, missing)["wifi"]["state"] == "unknown"
    (sys / "class/net/wlan0").rmdir()
    assert telemetry.collect(proc, sys, missing)["wifi"]["state"] == "missing"


def test_monitor_does_not_wait_or_queue_multiple_collections():
    pending = []

    def submit(collector):
        future = Future()
        pending.append(future)
        return future

    monitor = telemetry.Monitor(submit)
    assert monitor.read(0.0) == {} and len(pending) == 1
    assert monitor.read(10.0) == {} and len(pending) == 1
    pending[0].set_result({"usb_state": "configured"})
    assert monitor.read(10.1) == {"usb_state": "configured"} and len(pending) == 2
    pending[1].set_result({"usb_state": "not attached"})
    assert monitor.read(10.2) == {"usb_state": "not attached"} and len(pending) == 2
    monitor.read(12.2)
    assert len(pending) == 3
    pending[2].set_exception(OSError("device removed"))
    assert monitor.read(12.3) == {}


def test_physical_usb_identity_matches_saved_midi_cables_and_device_names(tmp_path):
    proc, sys = tmp_path / "proc", tmp_path / "sys"
    put(proc, "asound/card2/id", "Keys")
    put(proc, "asound/card2/usbid", "1234:5678")
    put(proc, "asound/card2/midi0", "Keys")
    usb = sys / "devices/usb1/1-1.2"
    interface = usb / "1-1.2:1.0"
    interface.mkdir(parents=True)
    sound = sys / "class/sound/card2"
    sound.mkdir(parents=True)
    (sound / "device").symlink_to(interface)
    put(usb, "idVendor", "1234")
    put(usb, "idProduct", "5678")
    put(usb, "serial", "ABC123")
    assert telemetry.sound_devices(proc, sys)[0]["identity"] == "usb-1234:5678-ABC123"
