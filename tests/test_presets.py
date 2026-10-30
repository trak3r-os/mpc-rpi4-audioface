# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's names and presets (bridge/rpi-audiod/presets.py), on plain dicts."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"))
import presets  # noqa: E402

GP = "usb-84ef:0186-A1B2C3"


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
                          "state": {"in": {GP: 3}, "volume": {"out": {GP: 80}}}}
    presets.save_preset(store, state, 1, "Gig", "2026-10-30 11:00")
    presets.save_preset(store, {"mute": {"in": []}}, 1, "", "2026-10-30 12:00")   # keeps the name
    assert store["1"] == {"name": "Gig", "saved": "2026-10-30 12:00", "state": {"mute": {"in": []}}}
    target = {"in": {"x": 1}, "volume": {"in": {}}, "names": {GP: {"name": "T"}}}
    presets.load_preset(target, store, 1)
    assert target == {"mute": {"in": []}, "names": {GP: {"name": "T"}}}
    with pytest.raises(ValueError, match="preset 2 is empty"):
        presets.load_preset(target, store, 2)
    assert target == {"mute": {"in": []}, "names": {GP: {"name": "T"}}}
    for bad in ({"1": "junk"}, {"1": {"name": "x"}}, {"1": {"state": []}}):
        with pytest.raises(ValueError):
            presets.load_preset({}, bad, 1)


def test_load_ignores_foreign_keys_of_a_hand_edited_preset():
    target = {}
    presets.load_preset(target, {"1": {"state": {"in": {GP: 2}, "names": {"x": 1}, "junk": 1}}}, 1)
    assert target == {"in": {GP: 2}}


def test_summary():
    store = {"3": {"name": "C", "saved": "t3", "state": {}}, "1": {"name": "A", "saved": "t1", "state": {}},
             "9": {"name": "no", "saved": "t"}, "x": {}, "2": "junk"}
    assert presets.summary(store) == [{"slot": 1, "name": "A", "saved": "t1"}, {"slot": 3, "name": "C", "saved": "t3"}]
    assert presets.summary({}) == []
