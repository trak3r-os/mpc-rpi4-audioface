# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's names and presets (bridge/rpi-audiod/presets.py), on plain dicts."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"))
import audiod  # noqa: E402
import presets  # noqa: E402

GP = "usb-84ef:0186-A1B2C3"


def test_active_scene_tracks_saved_changes_and_ignores_engine_selection():
    state = {'output_levels': {'local-dac': 50}, 'engine_mode': 'hub'}
    store = {}
    presets.save_preset(store, state, 2, 'Live', '')
    presets.mark_active(state, 2)
    assert presets.active_scene(state, store) == {'slot': 2, 'name': 'Live', 'available': True, 'modified': False}
    state['engine_mode'] = 'host'
    assert not presets.active_scene(state, store)['modified']
    state['output_levels']['local-dac'] = 60
    assert presets.active_scene(state, store)['modified']
    state['output_levels']['local-dac'] = 50
    assert not presets.active_scene(state, store)['modified']
    assert 'active_scene' not in presets.capture_state(state)
    assert not presets.active_scene(state, {})['available']


def test_set_name_and_clear():
    state = {"in": {GP: 1}}
    presets.set_name(state, GP, "Tracker")
    presets.set_name(state, GP, "Kick", "in", 1)
    presets.set_name(state, GP, "Snare", "in", 2)
    presets.set_name(state, GP, "Out L", "out", 1)
    assert state["names"] == {GP: {"name": "Tracker", "in": {"1": "Kick", "2": "Snare"}, "out": {"1": "Out L"}}}
    presets.set_name(state, GP, "Rename")
    presets.set_name(state, GP, "", "in", 1)
    presets.set_name(state, GP, "", "out", 1)
    assert state["names"] == {GP: {"name": "Rename", "in": {"2": "Snare"}}}
    presets.set_name(state, GP, "", "in", 2)
    presets.set_name(state, GP, "")
    assert state == {"in": {GP: 1}}
    presets.set_name(state, GP, "", "out", 9)   # clearing what is not there leaves no empty entry
    presets.set_name(state, GP, "")
    assert state == {"in": {GP: 1}}


def test_device_name():
    assert presets.device_name("Profile", {"name": "Mine"}) == "Mine"
    assert presets.device_name("Profile", {"in": {"1": "x"}}) == "Profile"
    assert presets.device_name("", None) == ""


def test_channel_names():
    assert presets.channel_names((), None, 2) is None
    assert presets.channel_names(("", ""), {}, 2) is None
    assert presets.channel_names(("L", "R", "Aux"), None, 3) == ["L", "R", "Aux"]
    assert presets.channel_names(("L", "R", "Aux"), None, 2) == ["L", "R"]
    assert presets.channel_names(("L",), None, 3) == ["L", "", ""]
    assert presets.channel_names(("L", "R"), {"2": "Mic", "3": "Line", "4": "gone", "x": "no", "0": "no"}, 3) == [
        "L", "Mic", "Line"]
    assert presets.channel_names((), {"2": "Mic"}, 3) == ["", "Mic", ""]


def test_save_and_load_preset():
    state = {"in": {GP: 3}, "volume": {"out": {GP: 80}}, "names": {GP: {"name": "T"}}, "other": 1}
    store = {}
    presets.save_preset(store, state, 1, "", "2026-10-30 10:00")
    assert store["1"] == {"name": "Preset 1", "saved": "2026-10-30 10:00",
                          "state": {"in": {GP: 3}, "volume": {"out": {GP: 80}},
                                    "names": {GP: {"name": "T"}}, "output_levels": {}}}
    presets.save_preset(store, state, 1, "Gig", "2026-10-30 11:00")
    presets.save_preset(store, {"mute": {"in": []}}, 1, "", "2026-10-30 12:00")   # keeps the name
    assert store["1"] == {"name": "Gig", "saved": "2026-10-30 12:00",
                          "state": {"mute": {"in": []}, "names": {}, "output_levels": {}}}
    target = {"in": {"x": 1}, "volume": {"in": {}}, "names": {GP: {"name": "T"}}}
    presets.load_preset(target, store, 1)
    assert target == {"mute": {"in": []}, "names": {}, "output_levels": {}}
    with pytest.raises(ValueError, match="preset 2 is empty"):
        presets.load_preset(target, store, 2)
    assert target == {"mute": {"in": []}, "names": {}, "output_levels": {}}
    for bad in ({"1": "junk"}, {"1": {"name": "x"}}, {"1": {"state": []}}):
        with pytest.raises(ValueError):
            presets.load_preset({}, bad, 1)


def test_load_ignores_foreign_keys_of_a_hand_edited_preset():
    target = {}
    presets.load_preset(target, {"1": {"state": {"in": {GP: 2}, "names": {"x": {"name": "X"}}, "junk": 1}}}, 1)
    assert target == {"in": {GP: 2}, "names": {"x": {"name": "X"}}}


def test_summary():
    store = {"3": {"name": "C", "saved": "t3", "state": {}}, "1": {"name": "A", "saved": "t1", "state": {}},
             "9": {"name": "no", "saved": "t"}, "x": {}, "2": "junk"}
    assert presets.summary(store) == [{"slot": 1, "name": "A", "saved": "t1"}, {"slot": 3, "name": "C", "saved": "t3"}]
    assert presets.summary({}) == []


def test_legacy_scene_keeps_names_but_new_empty_scene_can_restore_no_custom_names():
    state = {'names': {'a': {'name': 'Keep me'}}, 'host_profile': 'studio', 'engine_mode': 'hub'}
    presets.load_preset(state, {'1': {'state': {'in': {'a': 1}}}}, 1)
    assert state['names'] == {'a': {'name': 'Keep me'}}
    store = {}
    presets.save_preset(store, {}, 1, '', '')
    presets.load_preset(state, store, 1)
    assert state['names'] == {} and state['engine_mode'] == 'hub' and state['host_profile'] == 'studio'


def test_legacy_scene_keeps_output_gains_and_modern_scene_restores_them():
    state = {'output_levels': {'local-dac': 40}}
    presets.load_preset(state, {'1': {'state': {}}}, 1)
    assert state['output_levels'] == {'local-dac': 40}
    store = {}
    presets.save_preset(store, state, 1, '', '')
    state['output_levels']['local-dac'] = 100
    presets.load_preset(state, store, 1)
    assert state['output_levels'] == {'local-dac': 40}


# --- a device with no serial number moved to another USB port ------------------------------------

OLD, NEW = "usb-3-2-08bb:2902", "usb-1-2-08bb:2902"


def mixer_state(identity=OLD):
    return {"in": {identity: 3, GP: 1}, "out": {identity: 5},
            "in_channels": {identity: 2}, "out_channels": {identity: 2},
            "midi": {f"{identity}/0": 2, f"{GP}/1": 3}, "mute": {"in": [identity], "out": [GP]},
            "volume": {"in": {GP: 90}, "out": {identity: 70}}, "names": {identity: {"name": "Desk"}},
            "routes": [{"src": identity, "dst": "usb-host", "dst_pair": 2}, {"src": "usb-host", "dst": identity},
                       {"src": GP, "dst": "local-dac"}],
            "midi_routes": [{"src": f"{identity}/0", "dst": f"{GP}/1"}], "outputs": {"network-rtp": False}}


def test_a_device_that_moved_ports_takes_the_state_of_its_only_namesake():
    state = mixer_state()
    assert presets.follow_moves(state, {NEW, GP, "usb-host"}) == [(OLD, NEW)]
    expected = mixer_state(NEW)
    assert state == expected   # every key that names a device was rewritten, nothing else
    assert OLD not in presets.identities(state) and presets.identities(state) == {NEW, GP, "usb-host", "local-dac"}
    assert presets.follow_moves(state, {NEW, GP}) == []   # nothing left to move: idempotent


def test_two_stored_namesakes_are_a_guess_so_nothing_moves():
    state = mixer_state()
    state["in"]["usb-1-1.4-08bb:2902"] = 9
    before = repr(state)
    assert presets.follow_moves(state, {NEW, GP}) == [] and repr(state) == before


def test_two_new_namesakes_at_once_are_a_guess_so_nothing_moves():
    state = mixer_state()
    before = repr(state)
    assert presets.follow_moves(state, {NEW, "usb-1-1.1-08bb:2902"}) == [] and repr(state) == before


def test_a_namesake_that_is_still_present_does_not_move():
    state = mixer_state()
    before = repr(state)
    assert presets.follow_moves(state, {OLD, NEW}) == [] and repr(state) == before


def test_a_new_device_that_already_has_state_keeps_it():
    state = mixer_state()
    state["in"][NEW] = 7
    before = repr(state)
    assert presets.follow_moves(state, {NEW}) == [] and repr(state) == before


def test_devices_with_a_serial_or_another_model_are_never_touched():
    state = mixer_state("usb-84ef:0186-A1B2C3")   # a serial identity is not an identity from a port
    before = repr(state)
    assert presets.follow_moves(state, {"usb-84ef:0186-NEWSERIAL", NEW}) == [] and repr(state) == before
    state = mixer_state()
    assert presets.follow_moves(state, {"usb-1-2-1234:5678", "usb-1-3-08bb:2902#2"}) == []   # other model, or #2
    assert audiod.by_port("usb-1-1.1.3.4-0d8c:0014") == ("1-1.1.3.4", "0d8c:0014")
    assert audiod.by_port("usb-84ef:0186-20241224") is None and audiod.by_port("local-dac") is None
