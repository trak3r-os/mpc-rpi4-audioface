# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's MIDI logic (bridge/rpi-audiod/midi.py), on outputs taken from the Pi."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"))
import midi  # noqa: E402
from audiod import IN, OUT  # noqa: E402
from midi import Client, Command  # noqa: E402

# `aconnect -l` with a temporary connection between the GP-150 and Midi Through (2026-10-30).
ACONNECT = """client 0: 'System' [type=kernel]
    0 'Timer           '
    1 'Announce        '
client 14: 'Midi Through' [type=kernel]
    0 'Midi Through Port-0'
\tConnecting To: 36:0
\tConnected From: 36:0
client 36: 'GP-150' [type=kernel,card=5]
    0 'GP-150 MIDI 1   '
\tConnecting To: 14:0
\tConnected From: 14:0
"""

# /proc/asound/seq/clients at the same moment.
SEQ_CLIENTS = """Client info
  cur  clients : 3
  peak clients : 5
  max  clients : 192

Client   0 : "System" [Kernel Legacy]
  Port   0 : "Timer" (Rwe-) [In/Out]
  Port   1 : "Announce" (R-e-) [In]
Client  14 : "Midi Through" [Kernel Legacy]
  Port   0 : "Midi Through Port-0" (RWe-) [In/Out]
    Connecting To: 36:0
    Connected From: 36:0
Client  36 : "GP-150" [Kernel Legacy]
  Port   0 : "GP-150 MIDI 1" (RWeX) [In/Out]
    Connecting To: 14:0
    Connected From: 14:0
"""

# aseqdump piped through cat.
ASEQDUMP = """Waiting for data. Press Ctrl+C to end.
Source  Event                  Ch  Data
 14:0   Control change          0, controller 7, value 100
 14:0   Program change          2, program 5
 14:0   Note on                 0, note 60, velocity 127
 14:0   Note off                0, note 60, velocity 64
 14:0   System exclusive           F0 7D 52 41 73 74 61 74 75 73 F7
 14:0   Pitch bend              0, value 0
 14:0   Clock
 14:0   Control change         15, controller 3, value 127
"""

# Synthetic: the gadget's MIDI client has not been seen on the Pi yet. Here the GP-150 sits
# on cable 3 (gadget port 2), Midi Through feeds it, and an aseqdump listens to gadget port 0.
ROUTED = """client 14: 'Midi Through' [type=kernel]
    0 'Midi Through Port-0'
\tConnecting To: 36:0
\tConnected From: 36:0
client 36: 'GP-150' [type=kernel,card=5]
    0 'GP-150 MIDI 1   '
\tConnecting To: 14:0, 40:2[real:0]
\tConnected From: 14:0, 40:2
client 40: 'MIDI Gadget' [type=kernel,card=6]
    0 'f_midi          '
\tConnecting To: 128:0[ex][tick:1]
    1 'f_midi          '
    2 'f_midi          '
\tConnecting To: 36:0
\tConnected From: 36:0
    3 'f_midi          '
client 128: 'aseqdump' [type=user,pid=1234]
    0 'aseqdump        '
\tConnected From: 40:0
"""

GP = "usb-84ef:0186-A1B2C3"


def test_parse_aconnect():
    clients, connections = midi.parse_aconnect(ACONNECT)
    assert clients == {
        0: Client(0, "System", None, ((0, "Timer"), (1, "Announce"))),
        14: Client(14, "Midi Through", None, ((0, "Midi Through Port-0"),)),
        36: Client(36, "GP-150", 5, ((0, "GP-150 MIDI 1"),))}
    assert connections == {((14, 0), (36, 0)), ((36, 0), (14, 0))}


def test_parse_aconnect_several_destinations():
    clients, connections = midi.parse_aconnect(ROUTED)
    assert clients[40].card == 6 and [p for p, _ in clients[40].ports] == [0, 1, 2, 3]
    assert clients[128] == Client(128, "aseqdump", None, ((0, "aseqdump"),), 1234)
    assert connections == {((14, 0), (36, 0)), ((36, 0), (14, 0)), ((36, 0), (40, 2)),
                           ((40, 0), (128, 0)), ((40, 2), (36, 0))}


def test_parse_seq_caps():
    assert midi.parse_seq_caps(SEQ_CLIENTS) == {
        (0, 0): (True, False),  # "Rwe-": a lowercase w cannot be subscribed to
        (0, 1): (True, False),
        (14, 0): (True, True),
        (36, 0): (True, True)}


def test_endpoints():
    clients, _ = midi.parse_aconnect(ACONNECT)
    assert midi.endpoints(clients, {5: GP}) == [(f"{GP}/0", 36, 0)]
    clients = {50: Client(50, "Synth", 8, ((1, "Synth B"), (0, "Synth A"))), **clients,
               40: Client(40, "MIDI Gadget", 6, ((0, "f_midi"),))}
    assert midi.endpoints(clients, {5: GP, 8: "usb-synth"}) == [
        (f"{GP}/0", 36, 0), ("usb-synth/0", 50, 0), ("usb-synth/1", 50, 1)]
    assert midi.endpoints(clients, {}) == []


def test_assign_cables_one_cable_shared():
    assigned, parked, saved = midi.assign_cables(["a/0", "b/0"], {"c/0": 3}, 1, 1)
    assert assigned == {"a/0": 1, "b/0": 1} and parked == [] and saved == {"c/0": 3}


def test_assign_cables_sticky_around_control():
    assigned, parked, saved = midi.assign_cables(["a/0", "b/0"], {}, 4, 1)
    assert assigned == {"a/0": 2, "b/0": 3} and not parked
    # Back the other way round: each gets its cable again.
    assigned, _, _ = midi.assign_cables(["b/0", "a/0"], saved, 4, 1)
    assert assigned == {"b/0": 3, "a/0": 2}
    # An absent endpoint keeps its cable while there is another free one...
    assigned, _, saved = midi.assign_cables(["c/0"], saved, 4, 1)
    assert assigned == {"c/0": 4} and saved == {"a/0": 2, "b/0": 3, "c/0": 4}
    # ...and loses it when there is not; a returning endpoint gets its own back.
    assigned, parked, saved = midi.assign_cables(["c/0", "d/0"], saved, 4, 1)
    assert assigned == {"c/0": 4, "d/0": 2} and not parked and saved == {"b/0": 3, "c/0": 4, "d/0": 2}
    # No cable left: parked.
    assigned, parked, _ = midi.assign_cables(["a/0", "b/0"], {}, 2, 1)
    assert assigned == {"a/0": 2} and parked == ["b/0"]
    # Any control cable; a saved cable on the control cable or past the last one is replaced.
    assigned, _, _ = midi.assign_cables(["a/0", "b/0", "c/0"], {"a/0": 3, "b/0": 9}, 4, 3)
    assert assigned == {"a/0": 1, "b/0": 2, "c/0": 4}


def test_wanted_subscriptions():
    eps = [(f"{GP}/0", 36, 0), ("usb-keys/0", 37, 0), ("usb-box/0", 38, 0), ("usb-parked/0", 39, 0)]
    assigned = {f"{GP}/0": 2, "usb-keys/0": 3, "usb-box/0": 4}
    caps = {(36, 0): (True, True), (37, 0): (True, False)}  # usb-box is missing from caps
    assert midi.wanted_subscriptions(eps, assigned, caps, 40, True) == {
        ((36, 0), (40, 1)), ((40, 1), (36, 0)), ((37, 0), (40, 2))}
    assert midi.wanted_subscriptions(eps, assigned, caps, 40, False) == set()
    assert midi.wanted_subscriptions(eps, assigned, caps, None, True) == set()


def test_stale_after_reassignment():
    clients, connections = midi.parse_aconnect(ROUTED)
    caps = midi.parse_seq_caps(SEQ_CLIENTS)
    eps = midi.endpoints(clients, {5: GP})
    state, _ = midi.apply_command({"midi": {f"{GP}/0": 3}}, midi.parse_command(f"assign {GP} midi=2"))
    assigned, _, _ = midi.assign_cables([e[0] for e in eps], state["midi"], 4, 1)
    assert assigned == {f"{GP}/0": 2}
    wanted = midi.wanted_subscriptions(eps, assigned, caps, 40, True)
    assert wanted == {((36, 0), (40, 1)), ((40, 1), (36, 0))}
    device_clients = {e[1] for e in eps}
    # Midi Through <-> GP-150 and gadget -> aseqdump are not ours and stay.
    assert midi.stale_subscriptions(connections, wanted, 40, device_clients) == {
        ((36, 0), (40, 2)), ((40, 2), (36, 0))}
    assert midi.stale_subscriptions(connections | wanted, wanted, 40, device_clients) == {
        ((36, 0), (40, 2)), ((40, 2), (36, 0))}
    assert midi.stale_subscriptions(connections, set(), 40, set()) == set()


def test_parse_aseqdump():
    assert [midi.parse_aseqdump(line) for line in ASEQDUMP.splitlines()] == [
        None, None, ("cc", 1, 7, 100), None, None, None,
        ("sysex", bytes.fromhex("F07D5241737461747573F7")), None, None, ("cc", 16, 3, 127)]
    assert midi.parse_aseqdump("") is None


def test_sysex_round_trip():
    assert midi.sysex_hex("ping") == "F0 7D 52 41 70 69 6E 67 F7"
    for text in ("ping", "status", "ok rpi-audio", 'error: usage: x', '{"in": {"a": [1, 2]}}', "~ !", ""):
        assert midi.sysex_text(bytes.fromhex(midi.sysex_hex(text))) == text
    event, = [midi.parse_aseqdump(line) for line in ASEQDUMP.splitlines() if "System" in line]
    assert midi.sysex_text(event[1]) == "status"
    for bad in ("café", "a\nb", "a\tb", "\x7f"):
        with pytest.raises(ValueError):
            midi.sysex_hex(bad)


def test_sysex_text_rejects_other_messages():
    for raw in ("F0 7D 52 42 70 F7",  # another 7D use
                "F0 43 52 41 70 F7",  # a manufacturer id
                "F0 7D 52 41 70 69",  # no F7
                "F0 7D 52 41",
                "F0 7D 52 41 70 0A F7",  # a byte under 0x20
                "F0 7D 52 41 7F F7",
                "90 3C 7F"):
        assert midi.sysex_text(bytes.fromhex(raw)) is None


def test_parse_command():
    assert midi.parse_command("ping") == Command("ping")
    assert midi.parse_command(" status ") == Command("status")
    cmd = midi.parse_command(f"assign {GP} midi=2 in=3")
    assert cmd == Command("assign", GP, (("in", 3), ("midi", 2)))
    assert cmd.arg("in") == 3 and cmd.arg("out") is None and cmd.arg("out", 0) == 0
    assert midi.parse_command(f"assign {GP}/1 out=5").args == (("out", 5),)
    assert midi.parse_command(f"mute {GP} out on") == Command("mute", GP, (("direction", OUT), ("on", True)))
    assert midi.parse_command(f"mute {GP} in off").arg("on") is False
    assert midi.parse_command(f"volume {GP} in 0") == Command("volume", GP, (("direction", IN), ("percent", 0)))
    assert midi.parse_command(f"volume {GP} out 100").arg("percent") == 100
    assert hash(cmd) == hash(Command("assign", GP, (("in", 3), ("midi", 2))))


@pytest.mark.parametrize("text", [
    "", "reboot", "PING",
    "ping now", "status all",
    "assign", f"assign {GP}", f"assign {GP} in", f"assign {GP} in=", f"assign {GP} in=x", f"assign {GP} in=2.5",
    f"assign {GP} in=0", f"assign {GP} midi=-1", f"assign {GP} lane=2", f"assign {GP} in=3 in=5",
    f"mute {GP}", f"mute {GP} in", f"mute {GP} up on", f"mute {GP} in maybe", f"mute {GP} in on now",
    f"volume {GP} in", f"volume {GP} side 50", f"volume {GP} in 101", f"volume {GP} in -1",
    f"volume {GP} in loud", f"volume {GP} in 50 50",
])
def test_parse_command_errors(text):
    with pytest.raises(ValueError):
        midi.parse_command(text)


def test_parse_command_messages():
    def message(text):
        with pytest.raises(ValueError) as e:
            midi.parse_command(text)
        return str(e.value)

    assert message("reboot") == "unknown command reboot"
    assert message(f"mute {GP} in") == "usage: mute IDENTITY in|out on|off"
    assert message(f"mute {GP} up on") == "direction must be in or out"
    assert message(f"mute {GP} in maybe") == "expected on or off"
    assert message(f"assign {GP} in=x") == "in must be an integer"
    assert message(f"assign {GP} midi=0") == "midi must be 1 or more"
    assert message(f"volume {GP} out 101") == "percent must be 0..100"


def test_smf_sysex():
    pong = bytes.fromhex(midi.sysex_hex("pong").replace(" ", ""))
    assert midi.smf_sysex(pong) == (b"MThd\0\0\0\6\0\0\0\1\0\x60MTrk\0\0\0\x0f"
                                    b"\0\xF0\x08\x7D\x52\x41pong\xF7\0\xFF\x2F\0")
    long = bytes.fromhex(midi.sysex_hex("x" * 200).replace(" ", ""))
    smf = midi.smf_sysex(long)
    assert smf[22:26] == b"\0\xF0\x81\x4C" and smf.endswith(b"\xF7\0\xFF\x2F\0")
    assert int.from_bytes(smf[18:22], "big") == len(smf) - 22


def test_cc_percent():
    assert [midi.cc_percent(v) for v in (0, 1, 63, 64, 127)] == [0, 1, 50, 50, 100]


def test_cc_command():
    starts = {IN: {3: GP, 1: "mix"}, OUT: {5: GP}}

    def cc(controller, value, channel=16):
        return midi.cc_command(channel, controller, value, (16, 15), starts)

    assert cc(35, 127) == Command("volume", GP, (("direction", IN), ("percent", 100)))
    assert cc(37, 64, channel=15) == Command("volume", GP, (("direction", OUT), ("percent", 50)))
    assert cc(67, 64) == Command("mute", GP, (("direction", IN), ("on", True)))
    assert cc(69, 63, channel=15) == Command("mute", GP, (("direction", OUT), ("on", False)))
    assert cc(65, 0) == Command("mute", "mix", (("direction", IN), ("on", False)))
    assert cc(33, 0).identity == "mix"
    # Never commands: other channels, the first bank (1, 7, 10...), N == 0 or > 27, the
    # channel mode messages hosts send on stop, and no device starting at N there.
    assert cc(35, 127, channel=14) is None
    for controller in (0, 1, 3, 7, 10, 32, 60, 64, 92, 96, 120, 121, 123, 127):
        assert cc(controller, 127) is None and cc(controller, 0, channel=15) is None
    assert cc(36, 100) is None and cc(37, 100) is None and cc(35, 100, channel=15) is None
    assert midi.cc_command(1, 35, 127, (1, 2), starts).identity == GP
    assert midi.cc_command(1, 35, 127, (1, 2), {}) is None


def test_apply_assign():
    state = {"in": {"other": 1}, "mute": {"in": [], "out": []}}
    new, reply = midi.apply_command(state, midi.parse_command(f"assign {GP}/1 in=3 out=5 midi=2"))
    assert reply == "ok"
    assert new == {"in": {"other": 1, GP: 3}, "out": {GP: 5}, "midi": {f"{GP}/1": 2},
                   "mute": {"in": [], "out": []}}
    assert state == {"in": {"other": 1}, "mute": {"in": [], "out": []}}
    new, _ = midi.apply_command(new, midi.parse_command(f"assign {GP} midi=4"))
    assert new["midi"] == {f"{GP}/1": 2, f"{GP}/0": 4} and new["in"][GP] == 3


def test_apply_mute_and_volume():
    state = {"mute": {"in": ["zz"]}, "volume": {"in": {GP: 100}}}
    new, _ = midi.apply_command(state, midi.parse_command(f"mute {GP} in on"))
    new, _ = midi.apply_command(new, midi.parse_command(f"mute {GP} in on"))
    assert new["mute"] == {"in": [GP, "zz"]} and state["mute"] == {"in": ["zz"]}
    new, _ = midi.apply_command(new, midi.parse_command(f"mute {GP} out off"))
    new, _ = midi.apply_command(new, midi.parse_command("mute zz in off"))
    assert new["mute"] == {"in": [GP], "out": []}
    new, reply = midi.apply_command({}, midi.parse_command(f"volume {GP} out 80"))
    assert new == {"volume": {"out": {GP: 80}}} and reply == "ok"
    new, _ = midi.apply_command(state, midi.parse_command(f"volume {GP} in 30"))
    assert new["volume"] == {"in": {GP: 30}} and state["volume"] == {"in": {GP: 100}}
    for cmd in (Command("ping"), Command("status"), Command("reboot", GP)):
        with pytest.raises(ValueError):
            midi.apply_command(state, cmd)


def test_reply_header_is_not_a_command():
    # A host that echoes the control port back must not turn replies into commands.
    reply = bytes.fromhex(midi.sysex_hex("ok rpi-audio", reply=True).replace(" ", ""))
    assert reply[:4] == midi.REPLY_HEAD and midi.sysex_text(reply) is None


def test_parse_aconnect_pid():
    text = "client 128: 'aseqdump' [type=user,pid=1117377]\n    0 'aseqdump        '\n"
    clients, _ = midi.parse_aconnect(text)
    assert clients[128].pid == 1117377 and clients[128].card is None
