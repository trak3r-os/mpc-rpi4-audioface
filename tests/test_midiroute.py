# SPDX-License-Identifier: GPL-3.0-or-later
"""MIDI routes between USB devices (bridge/rpi-audiod/midiroute.py) and their commands."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"))
import midi  # noqa: E402
import midiroute  # noqa: E402
import presets  # noqa: E402
from midiroute import Link  # noqa: E402

KEYS, TRK, MIX = "usb-1234:0001-K", "usb-16d0:0e9f-T", "usb-08bb:2902-M"
EPS = [(f"{KEYS}/0", 20, 0), (f"{TRK}/0", 24, 0), (f"{TRK}/1", 24, 1), (f"{MIX}/0", 28, 0)]
CAPS = {(20, 0): (True, False), (24, 0): (True, True), (24, 1): (False, True), (28, 0): (False, False)}


def test_endpoints_and_the_default_port():
    assert midiroute.split(f"{TRK}/1") == (TRK, 1) and midiroute.split(TRK) == (TRK, None)
    assert midiroute.normal(TRK) == f"{TRK}/0" and midiroute.normal(f"{TRK}/2") == f"{TRK}/2"
    assert midiroute.split("usb-a/b/3") == ("usb-a/b", 3)


def test_check_refuses_a_device_to_itself_even_between_its_ports():
    with pytest.raises(ValueError, match="itself"):
        midiroute.check(Link(f"{TRK}/0", f"{TRK}/1"))
    midiroute.check(Link(f"{KEYS}/0", f"{TRK}/0"))


def test_state_round_trip_normalises_and_keeps_order():
    state = {}
    assert midiroute.add(state, Link(KEYS, TRK))
    assert midiroute.add(state, Link(f"{TRK}/0", f"{KEYS}/0"))
    assert not midiroute.add(state, Link(f"{KEYS}/0", f"{TRK}/0"))   # the same, with the port spelled out
    assert state["midi_routes"] == [{"src": f"{KEYS}/0", "dst": f"{TRK}/0"}, {"src": f"{TRK}/0", "dst": f"{KEYS}/0"}]
    assert midiroute.from_state(state) == [Link(f"{KEYS}/0", f"{TRK}/0"), Link(f"{TRK}/0", f"{KEYS}/0")]


def test_from_state_skips_bad_entries():
    state = {"midi_routes": [{"src": KEYS}, "x", {"src": f"{TRK}/0", "dst": f"{TRK}/1"}, {"src": 1, "dst": TRK},
                             {"src": KEYS, "dst": TRK}, {"src": f"{KEYS}/0", "dst": f"{TRK}/0"}]}
    assert midiroute.from_state(state) == [Link(f"{KEYS}/0", f"{TRK}/0")]
    assert midiroute.from_state(None) == [] and midiroute.from_state({}) == []


def test_remove_by_port_or_by_device():
    state = {}
    for link in (Link(f"{KEYS}/0", f"{TRK}/0"), Link(f"{KEYS}/0", f"{TRK}/1"), Link(f"{TRK}/0", f"{KEYS}/0")):
        midiroute.add(state, link)
    assert midiroute.remove(state, f"{KEYS}/0", f"{TRK}/1") == 1
    assert midiroute.from_state(state) == [Link(f"{KEYS}/0", f"{TRK}/0"), Link(f"{TRK}/0", f"{KEYS}/0")]
    assert midiroute.remove(state, KEYS, TRK) == 1   # no port: any
    assert midiroute.remove(state, KEYS, TRK) == 0
    assert midiroute.remove(state, TRK, KEYS) == 1
    assert state == {}


def test_wanted_joins_the_ports():
    links = [Link(f"{KEYS}/0", f"{TRK}/0"), Link(f"{KEYS}/0", f"{TRK}/1"), Link(f"{TRK}/0", f"{KEYS}/0")]
    subs, pending = midiroute.wanted(links, EPS, CAPS)
    assert subs == {((20, 0), (24, 0)), ((20, 0), (24, 1))} and pending == [
        (Link(f"{TRK}/0", f"{KEYS}/0"), f"{KEYS}/0 cannot receive MIDI")]


def test_wanted_waits_with_a_reason():
    _, pending = midiroute.wanted([Link(f"{KEYS}/0", "usb-gone/0")], EPS, CAPS)
    assert pending[0][1] == "usb-gone/0 is not here"
    _, pending = midiroute.wanted([Link(f"{KEYS}/0", f"{TRK}/5")], EPS, CAPS)
    assert pending[0][1] == f"{TRK}/5 is not here"
    _, pending = midiroute.wanted([Link(f"{MIX}/0", f"{TRK}/0")], EPS, CAPS)
    assert pending[0][1] == f"{MIX}/0 cannot send MIDI"
    _, pending = midiroute.wanted([Link(f"{KEYS}/0", f"{MIX}/0")], EPS, CAPS)
    assert pending[0][1] == f"{MIX}/0 cannot receive MIDI"


def test_reconcile_only_touches_connections_between_two_devices():
    devices = {20, 24, 28}
    subs = {((20, 0), (24, 0))}
    conns = {((20, 0), (24, 1)),            # a route that was removed
             ((24, 0), (24, 1)),            # a device's own loop: not ours
             ((14, 0), (24, 0)),            # Midi Through to a device: not ours
             ((20, 0), (99, 0))}            # a program: not ours
    connect, disconnect = midiroute.reconcile(subs, conns, devices)
    assert connect == [((20, 0), (24, 0))] and disconnect == [((20, 0), (24, 1))]
    assert midiroute.reconcile(subs, subs, devices) == ([], [])


def test_reconcile_with_owned_leaves_hand_made_subscriptions_alone():
    devices = {20, 24}
    subs, mine, theirs = {((20, 0), (24, 0))}, ((20, 0), (24, 1)), ((24, 1), (20, 0))
    connect, disconnect = midiroute.reconcile(subs, subs | {mine, theirs}, devices, owned={mine, ((20, 0), (24, 0))})
    assert connect == [] and disconnect == [mine]


# --- the commands --------------------------------------------------------------------------------


def test_parse_midi_route_commands():
    assert midi.parse_command(f"midiroute {KEYS} {TRK}") == midi.Command("midiroute", KEYS, (("dst", TRK),))
    assert midi.parse_command(f"midiunroute {KEYS}/0 {TRK}/1").verb == "midiunroute"
    for bad in ("midiroute", f"midiroute {KEYS}", f"midiroute {KEYS} {TRK} extra", f"midiunroute {KEYS}"):
        with pytest.raises(ValueError, match="usage: midi"):
            midi.parse_command(bad)


def test_midi_route_commands_edit_the_state():
    state, _ = midi.apply_command({}, midi.parse_command(f"midiroute {KEYS} {TRK}"))
    state, _ = midi.apply_command(state, midi.parse_command(f"midiroute {TRK}/0 {KEYS}"))
    assert midiroute.from_state(state) == [Link(f"{KEYS}/0", f"{TRK}/0"), Link(f"{TRK}/0", f"{KEYS}/0")]
    state, _ = midi.apply_command(state, midi.parse_command(f"midiunroute {TRK} {KEYS}"))
    assert midiroute.from_state(state) == [Link(f"{KEYS}/0", f"{TRK}/0")]
    with pytest.raises(ValueError, match="itself"):
        midi.apply_command({}, midi.parse_command(f"midiroute {KEYS} {KEYS}/1"))
    assert "routes" not in state   # the audio routes are another list


def test_presets_keep_the_midi_routes():
    state = {"in": {KEYS: 1}}
    midiroute.add(state, Link(KEYS, TRK))
    store = {}
    presets.save_preset(store, state, 1, "Keys to tracker", "2026-11-02 10:00")
    assert store["1"]["state"]["midi_routes"] == [{"src": f"{KEYS}/0", "dst": f"{TRK}/0"}]
    other = {}
    midiroute.add(other, Link(TRK, KEYS))
    presets.load_preset(other, store, 1)
    assert midiroute.from_state(other) == [Link(f"{KEYS}/0", f"{TRK}/0")]
    presets.save_preset(store, {}, 2, "None", "x")
    presets.load_preset(other, store, 2)
    assert "midi_routes" not in other
