# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's USB bandwidth logic (bridge/rpi-audiod/usb.py) on synthetic descriptors,
and the budget bookkeeping of the daemon's bridges."""

import importlib.machinery
import importlib.util
import json
import signal
import sys
import types
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"
sys.path.insert(0, str(BRIDGE))
import audiod  # noqa: E402
import usb  # noqa: E402
from audiod import IN, OUT  # noqa: E402


def device():
    return bytes([18, 1, 0, 2, 0, 0, 0, 64, 0xbb, 0x08, 0x02, 0x29, 0, 1, 1, 2, 0, 2])


def config(value, *parts):
    body = b"".join(parts)
    total = 9 + len(body)
    return bytes([9, 2, total & 255, total >> 8, 2, value, 0, 0x80, 50]) + body


def interface(number, alt, endpoints=0, klass=1, sub=2):
    return bytes([9, 4, number, alt, endpoints, klass, sub, 0, 0])


def endpoint(address, attributes, packet, interval=1, audio=True):
    """A 9-byte audio endpoint descriptor (bRefresh, bSynchAddress), or a 7-byte one."""
    head = [9 if audio else 7, 5, address, attributes, packet & 255, packet >> 8, interval]
    return bytes(head + ([0, 0] if audio else []))


CLASS_SPECIFIC = bytes([7, 0x24, 1, 0, 1, 0, 0])

# A PCM2902-like mixer: playback is interface 1, capture interface 2, a 1-byte HID endpoint on 3.
MIXER = device() + config(
    1,
    interface(0, 0, 0, 1, 1),
    interface(1, 0), interface(1, 1, 1), CLASS_SPECIFIC, endpoint(0x02, 9, 192),
    interface(1, 2, 1), endpoint(0x02, 9, 96),
    interface(2, 0), interface(2, 1, 1), CLASS_SPECIFIC, endpoint(0x84, 5, 196),
    interface(2, 3, 1), endpoint(0x84, 5, 180),
    interface(3, 0, 1, 3, 0), endpoint(0x85, 3, 1, 10, audio=False))

STREAM = """Mixer at usb-0000:01:00.0-1.3, full speed : USB Audio

Playback:
  Status: Running
    Interface = 1
    Altset = 1
    Packet Size = 192
  Interface 1
    Altset 1
    Channels: 2
    Rates: 32000, 44100, 48000
  Interface 1
    Altset 2
    Channels: 1
    Rates: 32000, 44100, 48000

Capture:
  Status: Stop
  Interface 2
    Altset 1
    Channels: 2
    Rates: 48000
  Interface 2
    Altset 3
    Channels: 2
    Rates: 44100
"""


def test_parse_stream_interfaces_skips_status_block():
    found = audiod.parse_stream(STREAM)
    assert [(a.interface, a.altset, a.channels) for a in found["playback"]] == [(1, 1, 2), (1, 2, 1)]
    assert [(a.interface, a.altset, a.rates) for a in found["capture"]] == [(2, 1, (48000,)), (2, 3, (44100,))]


def test_parse_descriptors():
    found = usb.parse_descriptors(MIXER, 1)
    assert found[(1, 1)] == [usb.Endpoint(0x02, 9, 192, 1)]
    assert found[(2, 3)] == [usb.Endpoint(0x84, 5, 180, 1)]
    assert found[(1, 0)] == [] and found[(3, 0)] == [usb.Endpoint(0x85, 3, 1, 10)]
    assert usb.parse_descriptors(MIXER, 2) == {}   # no such configuration


def test_parse_descriptors_picks_the_active_configuration():
    data = device() + config(1, interface(1, 1, 1), endpoint(0x01, 5, 100)) \
        + config(2, interface(1, 1, 1), endpoint(0x01, 5, 300))
    assert usb.parse_descriptors(data, 1)[(1, 1)][0].packet == 100
    assert usb.parse_descriptors(data, 2)[(1, 1)][0].packet == 300
    assert usb.parse_descriptors(data, None) == {}


def test_parse_descriptors_survives_odd_data():
    assert usb.parse_descriptors(b"", 1) == {}
    assert usb.parse_descriptors(b"\x12", 1) == {}
    for cut in range(len(MIXER)):   # truncated anywhere: no crash, and nothing invented
        for key, endpoints in usb.parse_descriptors(MIXER[:cut], 1).items():
            assert endpoints == usb.parse_descriptors(MIXER, 1)[key][:len(endpoints)]
    data = device() + config(1, interface(1, 1, 1), bytes([0, 5, 1, 1]), endpoint(0x01, 5, 100))
    assert usb.parse_descriptors(data, 1)[(1, 1)] == []   # bLength 0 stops the walk
    data = device() + config(1, interface(1, 1, 1), bytes([200, 5, 1, 1, 0, 1, 1]))
    assert usb.parse_descriptors(data, 1)[(1, 1)] == []   # bLength past the end stops it too
    short = device() + config(1, interface(1, 1, 1), bytes([4, 5, 1, 1]))
    assert usb.parse_descriptors(short, 1)[(1, 1)] == []   # an endpoint too short to read is skipped


def test_direction_load_follows_the_rate():
    stream = audiod.parse_stream(STREAM)
    ifaces = usb.parse_descriptors(MIXER, 1)
    plan = audiod.plan_direction
    assert usb.direction_load("12", stream["playback"], plan(stream["playback"], [48000]), ifaces) == 192
    assert usb.direction_load("12", stream["capture"], plan(stream["capture"], [48000]), ifaces) == 196
    assert usb.direction_load("12", stream["capture"], plan(stream["capture"], [44100]), ifaces) == 180


def test_direction_load_counts_data_and_feedback_endpoints():
    # Altset 1 of an asynchronous OUT stream: 720 B of data, 3 B of feedback; alt 2 is bigger but mono-only.
    data = device() + config(1, interface(1, 1, 2), endpoint(0x01, 5, 720), endpoint(0x82, 0x11, 3),
                             interface(1, 2, 2), endpoint(0x01, 5, 900), endpoint(0x82, 0x11, 3))
    stream = audiod.parse_stream("Playback:\n  Interface 1\n    Altset 1\n    Channels: 8\n    Rates: 44100\n"
                                 "  Interface 1\n    Altset 2\n    Channels: 10\n    Rates: 44100\n")["playback"]
    ifaces = usb.parse_descriptors(data, 1)
    assert usb.direction_load("12", stream, (44100, 10), ifaces) == 903
    assert usb.direction_load("12", stream[:1], (44100, 8), ifaces) == 723
    # an interrupt endpoint is not counted
    data = device() + config(1, interface(1, 1, 2), endpoint(0x01, 5, 720), endpoint(0x85, 3, 8, 10, audio=False))
    assert usb.direction_load("12", stream[:1], (44100, 8), usb.parse_descriptors(data, 1)) == 720


def test_direction_load_high_speed_and_unknown():
    stream = audiod.parse_stream(STREAM)["capture"]
    ifaces = usb.parse_descriptors(MIXER, 1)
    plan = (48000, 2)
    assert usb.direction_load("480", stream, plan, ifaces) == 0
    assert usb.direction_load("5000", stream, plan, ifaces) == 0
    assert usb.direction_load("1.5", stream, plan, ifaces) == 196
    assert usb.direction_load("", stream, plan, ifaces) is None
    assert usb.direction_load("12", stream, plan, {}) is None          # descriptors unreadable
    assert usb.direction_load("12", stream, plan, {(2, 1): []}) is None  # a stream altset with no endpoint
    assert usb.direction_load("12", stream, (96000, 2), ifaces) is None  # nothing matches the plan
    assert usb.direction_load("12", [audiod.Altset(2, (48000,))], plan, ifaces) is None  # stream0 gave no numbers


def test_budget_reason():
    assert usb.budget_reason(196, 903, 1099, "1") is None
    assert usb.budget_reason(200, 903, 1099, "1") == "USB full-speed budget: needs 200 B, 196 B of 1099 B free on bus 1"
    assert usb.budget_reason(192, 1000, 1099, "1") == "USB full-speed budget: needs 192 B, 99 B of 1099 B free on bus 1"
    assert usb.budget_reason(192, 1200, 1099, "1").startswith("USB full-speed budget: needs 192 B, 0 B of")
    assert usb.budget_reason(192, 1000, 0, "1") is None   # check off
    assert usb.budget_reason(0, 1099, 1099, "1") is None  # nothing to open (high speed)


# --- the daemon's bridges -----------------------------------------------------------------

stub = "tomllib" not in sys.modules and importlib.util.find_spec("tomllib") is None
if stub:   # Python before 3.11: the daemon imports it, but these tests do not use it
    sys.modules["tomllib"] = types.ModuleType("tomllib")
loader = importlib.machinery.SourceFileLoader("rpi_audiod", str(BRIDGE / "rpi-audiod"))
daemon = importlib.util.module_from_spec(importlib.util.spec_from_loader("rpi_audiod", loader))
loader.exec_module(daemon)
if stub:
    del sys.modules["tomllib"]


class FakeChild:
    def __init__(self, name, cmd, on_line=None, stop_signal=None):
        self.name, self.cmd, self.alive_, self.proc = name, cmd, True, types.SimpleNamespace(returncode=0)
        self.started, self.stop_signal = 0.0, stop_signal

    def alive(self):
        return self.alive_

    def stop(self, grace=1.0):
        self.alive_ = False


def bridges(monkeypatch, *specs):
    """Bridges on one daemon, from (id, bus, load) of one IN direction each."""
    monkeypatch.setattr(daemon, "Child", FakeChild)
    logs = []
    monkeypatch.setattr(daemon, "log", logs.append)
    d = daemon.Daemon.__new__(daemon.Daemon)
    d.bridges = {}
    for name, bus, load in specs:
        dev = daemon.Device(1, name, "001/002", "usb-" + name, {IN: (48000, 2), OUT: None}, bus=bus,
                            loads={IN: load, OUT: None})
        b = daemon.Bridge(dev, IN)
        b.start = 1
        d.bridges[(dev.identity, IN)] = b
    return d, logs


def tick(d, budget, now=0.0):
    cfg = {"bridge": {}}
    for b in d.bridges.values():
        b.tick(cfg, now, d.bus_used(b), budget)


def test_bridges_share_the_budget_in_order(monkeypatch):
    d, logs = bridges(monkeypatch, ("tracker", "1", 903), ("mixer", "1", 196), ("other", "2", 196), ("hs", "1", None))
    tick(d, 1099)
    running = {b.client: bool(b.child) for b in d.bridges.values()}
    assert running == {"tracker_in": True, "mixer_in": True, "other_in": True, "hs_in": True}
    d, logs = bridges(monkeypatch, ("tracker", "1", 903), ("mixer", "1", 196), ("mixer2", "1", 192),
                      ("other", "2", 196))
    tick(d, 1099)
    mixer2 = d.bridges[("usb-mixer2", IN)]
    assert [bool(b.child) for b in d.bridges.values()] == [True, True, False, True]
    assert mixer2.blocked == "USB full-speed budget: needs 192 B, 0 B of 1099 B free on bus 1"
    assert sum("waits" in line for line in logs) == 1
    tick(d, 1099)   # still blocked: nothing more is logged
    assert sum("waits" in line for line in logs) == 1
    d.bridges.pop(("usb-mixer", IN)).stop()   # that device leaves: its budget frees up
    tick(d, 1099, 100.0)
    assert mixer2.child and mixer2.blocked is None
    assert any("has USB budget again" in line for line in logs)


def test_budget_zero_turns_the_check_off(monkeypatch):
    d, _ = bridges(monkeypatch, ("a", "1", 903), ("b", "1", 903))
    tick(d, 0)
    assert all(b.child for b in d.bridges.values())


def test_parked_bridge_is_not_blocked(monkeypatch):
    d, _ = bridges(monkeypatch, ("a", "1", 903), ("b", "1", 903))
    d.bridges[("usb-b", IN)].start = None
    tick(d, 1099)
    assert not d.bridges[("usb-b", IN)].child and d.bridges[("usb-b", IN)].blocked is None


def test_status_shows_the_reason(monkeypatch):
    d, _ = bridges(monkeypatch, ("a", "1", 903), ("b", "1", 903))
    tick(d, 1099)
    d.cfg, d.rates, d.mode, d.jack_ready, d.channels, d.midi = {}, (0, 0), None, False, 26, None
    d.devices = {b.dev.identity: b.dev for b in d.bridges.values()}
    d.muted, d.volumes, d.route_state = {IN: set(), OUT: set()}, {}, {}
    status = {e["identity"]: e for e in d.status_data()["devices"]}
    assert "blocked" not in status["usb-a"][IN] and status["usb-a"][IN]["fs_load"] == 903
    assert status["usb-b"][IN]["blocked"].startswith("USB full-speed budget: needs 903 B, 196 B of 1099 B")


def test_device_ignores_channels_and_status_names(monkeypatch):
    d, _ = bridges(monkeypatch, ("a", "1", 0))
    profile = audiod.Profile("1234:5678", "a.toml", name="Dev", names_in=("L", "R", "Aux"), ignore_in=(2,))
    dev = daemon.Device(1, "a", "001/002", "usb-a", {IN: (48000, 3), OUT: None}, profile)
    b = daemon.Bridge(dev, IN)
    b.start = 5
    assert (b.channels, b.size, b.kept) == (3, 2, [1, 3])
    assert b.routes() == [("a_in:capture_1", "system:playback_5"), ("a_in:capture_3", "system:playback_6")]
    d.bridges, d.devices = {("usb-a", IN): b}, {"usb-a": dev}
    d.rates, d.mode, d.jack_ready, d.channels, d.midi = (0, 0), None, False, 26, None
    d.muted, d.volumes, d.route_state = {IN: set(), OUT: set()}, {}, {}
    entry = d.status_data()["devices"][0]
    assert entry["name"] == "Dev"
    assert entry[IN]["slots"] == 2 and entry[IN]["ignored"] == [2] and entry[IN]["names"] == ["L", "R", "Aux"]
    assert OUT not in entry


def test_bridges_stop_zita_with_sigint(monkeypatch):
    d, _ = bridges(monkeypatch, ("a", "1", 0))
    tick(d, 1099)
    assert d.bridges[("usb-a", IN)].child.stop_signal == signal.SIGINT


def test_child_stop_sends_its_signal(monkeypatch):
    monkeypatch.setattr(daemon, "log", lambda msg: None)
    c = daemon.Child("sleep", ["sleep", "5"], stop_signal=signal.SIGINT)
    c.stop()
    assert c.proc.returncode == -signal.SIGINT


# --- names, presets and their files ----------------------------------------------------------

def stateful(monkeypatch, tmp_path):
    """The daemon module with its slots.json and presets.json in tmp_path."""
    monkeypatch.setattr(daemon, "STATE", tmp_path / "slots.json")
    monkeypatch.setattr(daemon, "PRESETS", tmp_path / "presets.json")
    monkeypatch.setattr(daemon, "log", lambda msg: None)


def command_daemon(monkeypatch, tmp_path):
    stateful(monkeypatch, tmp_path)
    d = daemon.Daemon.__new__(daemon.Daemon)
    d.bridges, d.devices, d.rates, d.mode, d.jack_ready, d.channels, d.midi = {}, {}, (0, 0), None, False, 26, None
    d.muted, d.volumes, d.route_state = {IN: set(), OUT: set()}, {}, {}
    return d


def control_midi():
    m = daemon.Midi.__new__(daemon.Midi)
    m.channels = (16, 15)
    m.events = daemon.queue.SimpleQueue()
    return m


def test_name_and_preset_commands_through_the_daemon(monkeypatch, tmp_path):
    d = command_daemon(monkeypatch, tmp_path)
    assert d.command("assign usb-a in=3 out=5") == "ok"
    assert d.command("volume usb-a out 80") == "ok"
    assert d.command("name usb-a  My  box") == "ok"
    assert d.command("name usb-a in 2 Kick") == "ok"
    assert daemon.load_slots()["names"] == {"usb-a": {"name": "My  box", "in": {"2": "Kick"}}}
    assert d.command("preset load 1") == "error: preset 1 is empty"
    assert d.command("preset save 1 Live") == "ok"
    saved = daemon.load_presets()["1"]
    assert saved["name"] == "Live" and len(saved["saved"]) == 16
    assert saved["state"] == {"in": {"usb-a": 3}, "out": {"usb-a": 5}, "volume": {"out": {"usb-a": 80}}}
    assert (tmp_path / "presets.json").stat().st_mode & 0o777 == 0o644
    assert d.command("assign usb-a in=9") == "ok"
    assert d.command("name usb-a Renamed") == "ok"
    stamp = daemon.slots_stamp()
    assert d.command("preset load 1") == "ok"
    slots = daemon.load_slots()
    assert slots["in"] == {"usb-a": 3} and slots["names"]["usb-a"]["name"] == "Renamed"
    assert daemon.slots_stamp() != stamp   # the service sees the change and re-applies it
    assert d.command("preset save 1") == "ok" and daemon.load_presets()["1"]["name"] == "Live"
    assert d.command("preset save 2") == "ok" and daemon.load_presets()["2"]["name"] == "Preset 2"
    assert d.command("preset clear 1") == "ok" and sorted(daemon.load_presets()) == ["2"]
    assert d.command("preset load 9").startswith("error: slot must be")
    assert d.command("name usb-a " + "x" * 25) == "error: name must be at most 24 characters"
    status = json.loads(d.command("status"))
    assert status["presets"] == [{"slot": 2, "name": "Preset 2", "saved": daemon.load_presets()["2"]["saved"]}]


def test_empty_preset_load_writes_nothing(monkeypatch, tmp_path):
    d = command_daemon(monkeypatch, tmp_path)
    assert d.command("preset load 4") == "error: preset 4 is empty"
    assert d.command("preset clear 4") == "ok"
    assert not (tmp_path / "slots.json").exists() and not (tmp_path / "presets.json").exists()


def test_presets_file_of_junk_is_empty(monkeypatch, tmp_path):
    d = command_daemon(monkeypatch, tmp_path)
    (tmp_path / "presets.json").write_text("[1, 2")
    assert daemon.load_presets() == {}
    (tmp_path / "presets.json").write_text("[1]")
    assert daemon.load_presets() == {}
    assert d.command("preset save 1") == "ok" and list(daemon.load_presets()) == ["1"]


def test_cli_changes_use_the_same_commands(monkeypatch, tmp_path):
    stateful(monkeypatch, tmp_path)
    daemon.cmd_change("name usb-a out 1 Main L")
    daemon.cmd_change("preset save 3 Gig")
    assert daemon.load_slots()["names"]["usb-a"]["out"] == {"1": "Main L"}
    assert daemon.load_presets()["3"]["name"] == "Gig"
    for text in ("preset load 5", "name usb-a " + "x" * 25):
        with pytest.raises(SystemExit):
            daemon.cmd_change(text)


def test_program_change_loads_presets(monkeypatch, tmp_path):
    d = command_daemon(monkeypatch, tmp_path)
    d.command("assign usb-a in=3")
    d.command("preset save 2 Two")
    d.command("assign usb-a in=7")
    m = control_midi()
    for event in (("pc", 15, 1), ("pc", 16, 9), ("pc", 16, 5)):   # other channel, no such program, empty preset
        m.events.put(event)
    m.drain(d)
    assert daemon.load_slots()["in"] == {"usb-a": 7}
    m.events.put(("pc", 16, 1))
    m.drain(d)
    assert daemon.load_slots()["in"] == {"usb-a": 3}


def test_program_change_comes_after_earlier_ccs(monkeypatch, tmp_path):
    d = command_daemon(monkeypatch, tmp_path)
    d.starts = lambda: {IN: {3: "usb-a"}, OUT: {}}
    d.command("volume usb-a in 10")
    d.command("preset save 1")
    m = control_midi()
    m.events.put(("cc", 16, 35, 127))   # level 100, applied before the preset restores 10
    m.events.put(("pc", 16, 0))
    m.drain(d)
    assert daemon.load_slots()["volume"] == {"in": {"usb-a": 10}}


def test_status_names(monkeypatch, tmp_path):
    d = command_daemon(monkeypatch, tmp_path)
    profile = audiod.Profile("1234:5678", "a.toml", name="Dev", names_in=("L", "R"))
    dev = daemon.Device(1, "a", "001/002", "usb-a", {IN: (48000, 3), OUT: (48000, 2)}, profile)
    d.bridges = {("usb-a", IN): daemon.Bridge(dev, IN), ("usb-a", OUT): daemon.Bridge(dev, OUT)}
    d.devices = {"usb-a": dev}
    entry = d.status_data()["devices"][0]
    assert entry["name"] == "Dev" and entry[IN]["names"] == ["L", "R", ""] and "names" not in entry[OUT]
    assert d.status_data()["presets"] == []
    d.command("name usb-a Mine")
    d.command("name usb-a in 2 Mic")
    d.command("name usb-a in 3 Aux")
    d.command("name usb-a out 2 Right")
    entry = d.status_data()["devices"][0]
    assert entry["name"] == "Mine" and entry[IN]["names"] == ["L", "Mic", "Aux"]
    assert entry[OUT]["names"] == ["", "Right"]
    d.command("name usb-a")
    assert d.status_data()["devices"][0]["name"] == "Dev"


def test_status_with_everything_named_fits_one_sysex(monkeypatch, tmp_path):
    d = command_daemon(monkeypatch, tmp_path)
    d.midi = types.SimpleNamespace(status=lambda: {
        "card": "MIDIGadget", "client": 40, "ports": 4, "control_port": 1, "host_connected": True,
        "listening": True,
        "endpoints": [{"endpoint": f"usb-84ef:0186-A1B2C3{k}/0", "port": k % 3 + 2} for k in range(6)]})
    for k in range(6):
        profile = audiod.Profile("1234:5678", "a.toml", name="Profile name")
        dev = daemon.Device(k + 1, f"Device{k}", f"001/00{k}", f"usb-84ef:0186-A1B2C3{k}",
                            {IN: (48000, 6), OUT: (48000, 6)}, profile, speed="12", bus="1",
                            loads={IN: 196, OUT: 192})
        d.devices[dev.identity] = dev
        for direction in (IN, OUT):
            b = daemon.Bridge(dev, direction)
            b.start, b.child = 1 + 6 * k, FakeChild("zita", [])
            d.bridges[(dev.identity, direction)] = b
            d.volumes[(dev.identity, direction)] = 100
        d.command(f"name {dev.identity} " + "N" * 16)
        for direction in (IN, OUT):
            for ch in range(1, 7):
                d.command(f"name {dev.identity} {direction} {ch} " + "c" * 16)
    for slot in range(1, 9):
        d.command(f"preset save {slot} " + "P" * 16)
    full = json.dumps(d.status_data(), separators=(",", ":"), sort_keys=True)
    reply = d.command("status")
    status = json.loads(reply)
    print("status bytes:", len(full.encode()), "reply bytes:", len(reply.encode()))
    assert len(full.encode()) > 4000   # the full status does not fit: the reply drops diagnostics
    assert len(reply.encode()) < 4000
    assert len(status["presets"]) == 8 and status["devices"][5][OUT]["names"] == ["c" * 16] * 6
    assert status["devices"][0]["name"] == "N" * 16 and status["devices"][0][IN]["level"] == 100
    assert status["midi"]["endpoints"][5]["port"] == 4
