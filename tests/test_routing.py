# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's device-to-device routes (bridge/rpi-audiod/routing.py) and the route commands."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"))
import midi  # noqa: E402
import presets  # noqa: E402
import routing  # noqa: E402
from routing import Route  # noqa: E402

MIXER, GP, TRK = "usb-08bb:2902-A", "usb-84ef:0186-B", "usb-16d0:0e9f-C"
BRIDGES = {(MIXER, "in"): ("codec_in", 2), (GP, "in"): ("gp150_in", 2), (GP, "out"): ("gp150_out", 2),
           (TRK, "in"): ("tracker_in", 2), (TRK, "out"): ("tracker_out", 2)}
PORTS = {f"{c}:{kind}_{k}" for c, kind in (("codec_in", "capture"), ("gp150_in", "capture"), ("gp150_out", "playback"),
                                           ("tracker_in", "capture"), ("tracker_out", "playback")) for k in (1, 2)}


def test_check_refuses_a_device_to_itself_and_bad_pairs():
    with pytest.raises(ValueError, match="itself"):
        routing.check(Route(GP, GP))
    with pytest.raises(ValueError, match="start at 1"):
        routing.check(Route(GP, TRK, 0))
    routing.check(Route(GP, TRK, 2, 3))


def test_state_round_trip_keeps_default_pairs_out():
    state = {}
    assert routing.add(state, Route(MIXER, TRK))
    assert routing.add(state, Route(GP, TRK, 1, 2))
    assert not routing.add(state, Route(MIXER, TRK))
    assert state["routes"] == [{"src": MIXER, "dst": TRK}, {"src": GP, "dst": TRK, "dst_pair": 2}]
    assert routing.from_state(state) == [Route(MIXER, TRK), Route(GP, TRK, 1, 2)]


def test_from_state_skips_bad_entries_and_repeats():
    state = {"routes": [{"src": MIXER}, "x", {"src": GP, "dst": GP}, {"src": GP, "dst": TRK, "src_pair": "two"},
                        {"src": GP, "dst": TRK}, {"src": GP, "dst": TRK}, {"src": 1, "dst": TRK}]}
    assert routing.from_state(state) == [Route(GP, TRK)]
    assert routing.from_state(None) == [] and routing.from_state({}) == []


def test_remove_by_pair_or_all():
    state = {}
    for r in (Route(GP, TRK), Route(GP, TRK, 2, 1), Route(MIXER, TRK)):
        routing.add(state, r)
    assert routing.remove(state, GP, TRK, 2) == 1
    assert routing.from_state(state) == [Route(GP, TRK), Route(MIXER, TRK)]
    assert routing.remove(state, GP, TRK) == 1
    assert routing.remove(state, GP, TRK) == 0
    assert routing.remove(state, MIXER, TRK) == 1
    assert state == {}   # no routes, no key


def test_toggle():
    state = {}
    assert routing.toggle(state, Route(GP, TRK)) is True
    assert routing.toggle(state, Route(GP, TRK)) is False
    assert state == {}
    with pytest.raises(ValueError):
        routing.toggle(state, Route(GP, GP))


def test_pairs():
    assert [routing.pair_count(n) for n in (1, 2, 3, 6)] == [1, 1, 2, 3]
    assert routing.pair_channels(2, 3) == [3] and routing.pair_channels(2, 4) == [3, 4]
    assert routing.links([1, 2], [1, 2]) == [(1, 1), (2, 2)]
    assert routing.links([1], [1, 2]) == [(1, 1), (1, 2)]   # mono is copied to both
    assert routing.links([1, 2], [1]) == [(1, 1), (2, 1)]   # stereo into mono is summed


def test_wanted_joins_the_pairs():
    want, pending = routing.wanted([Route(MIXER, TRK), Route(GP, TRK)], BRIDGES, {}, PORTS)
    assert want == {("codec_in:capture_1", "tracker_out:playback_1"), ("codec_in:capture_2", "tracker_out:playback_2"),
                    ("gp150_in:capture_1", "tracker_out:playback_1"), ("gp150_in:capture_2", "tracker_out:playback_2")}
    assert pending == []


def test_wanted_waits_with_a_reason():
    bridges = {k: v for k, v in BRIDGES.items() if k != (TRK, "out")}
    want, pending = routing.wanted([Route(MIXER, TRK)], bridges, {}, PORTS)
    assert want == set() and pending == [(Route(MIXER, TRK), f"{TRK} is not here")]
    want, pending = routing.wanted([Route(MIXER, TRK)], BRIDGES, {}, PORTS - {"tracker_out:playback_2"})
    assert want == set() and pending[0][1] == "starting"
    _, pending = routing.wanted([Route(MIXER, TRK, 1, 2)], BRIDGES, {}, PORTS)
    assert pending[0][1] == "the device has no such pair"
    _, pending = routing.wanted([Route(MIXER, TRK)], BRIDGES, {"in": {MIXER}}, PORTS)
    assert pending[0][1] == "muted"
    _, pending = routing.wanted([Route(MIXER, TRK)], BRIDGES, {"out": {TRK}}, PORTS)
    assert pending[0][1] == "muted"


def test_wanted_odd_channel_counts():
    bridges = {(MIXER, "in"): ("codec_in", 1), (TRK, "out"): ("tracker_out", 2)}
    want, _ = routing.wanted([Route(MIXER, TRK)], bridges, {}, PORTS)
    assert want == {("codec_in:capture_1", "tracker_out:playback_1"), ("codec_in:capture_1", "tracker_out:playback_2")}


def test_reconcile_only_touches_connections_between_bridges():
    clients = {"codec_in", "tracker_out", "gp150_in", "gp150_out", "tracker_in"}
    want = {("codec_in:capture_1", "tracker_out:playback_1"), ("codec_in:capture_2", "tracker_out:playback_2")}
    existing = {frozenset(("codec_in:capture_1", "tracker_out:playback_1")),
                frozenset(("gp150_in:capture_1", "tracker_out:playback_1")),       # a route that was removed
                frozenset(("gp150_in:capture_1", "system:playback_3")),            # the gadget's: not ours
                frozenset(("somebody:out", "tracker_out:playback_2"))}             # another client: not ours
    connect, disconnect = routing.reconcile(want, existing, clients)
    assert connect == [("codec_in:capture_2", "tracker_out:playback_2")]
    assert disconnect == [("gp150_in:capture_1", "tracker_out:playback_1")]   # output port first


def test_reconcile_is_quiet_when_nothing_changed():
    want = {("codec_in:capture_1", "tracker_out:playback_1")}
    assert routing.reconcile(want, {frozenset(want.copy().pop())}, {"codec_in", "tracker_out"}) == ([], [])


# --- the commands --------------------------------------------------------------------------------


def test_parse_route_commands():
    assert midi.parse_command(f"route {MIXER} {TRK}") == midi.Command("route", MIXER, (("dst", TRK),))
    cmd = midi.parse_command(f"route {MIXER} {TRK} dst=2 src=3")
    assert cmd.args == (("dst", TRK), ("src_pair", 3), ("dst_pair", 2))
    assert midi.parse_command(f"unroute {MIXER} {TRK}").verb == "unroute"
    for bad in ("route", f"route {MIXER}", f"route {MIXER} {TRK} src", f"route {MIXER} {TRK} in=1",
                f"route {MIXER} {TRK} src=1 src=2"):
        with pytest.raises(ValueError, match="usage: route"):
            midi.parse_command(bad)
    with pytest.raises(ValueError, match="src must be 1 or more"):
        midi.parse_command(f"route {MIXER} {TRK} src=0")


def test_route_commands_edit_the_state():
    state, _ = midi.apply_command({}, midi.parse_command(f"route {MIXER} {TRK}"))
    state, _ = midi.apply_command(state, midi.parse_command(f"route {GP} {TRK} dst=2"))
    assert routing.from_state(state) == [Route(MIXER, TRK), Route(GP, TRK, 1, 2)]
    state, _ = midi.apply_command(state, midi.parse_command(f"unroute {GP} {TRK}"))
    assert routing.from_state(state) == [Route(MIXER, TRK)]
    with pytest.raises(ValueError, match="itself"):
        midi.apply_command({}, midi.parse_command(f"route {GP} {GP}"))


def test_presets_keep_the_routes():
    state = {"in": {GP: 1}, "names": {GP: {"name": "Pedal"}}}
    routing.add(state, Route(GP, TRK))
    store = {}
    presets.save_preset(store, state, 1, "Guitar", "2026-11-01 10:00")
    assert store["1"]["state"]["routes"] == [{"src": GP, "dst": TRK}]
    other = {"in": {MIXER: 3}}
    routing.add(other, Route(MIXER, TRK))
    presets.load_preset(other, store, 1)
    assert routing.from_state(other) == [Route(GP, TRK)]
    presets.save_preset(store, {"in": {GP: 1}}, 2, "Plain", "x")   # a preset without routes clears them on load
    presets.load_preset(other, store, 2)
    assert "routes" not in other
