# SPDX-License-Identifier: GPL-3.0-or-later
"""The small-display interface (bridge/rpi-audio-ui/ui.py): screens, navigation and the commands it sends."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge" / "rpi-audio-ui"))
sys.path.insert(0, str(ROOT / "bridge" / "rpi-audiod"))
import midi  # noqa: E402
import routing  # noqa: E402
import ui as display  # noqa: E402

MIXER, GP, TRK = "usb-mixer", "usb-gp150", "usb-tracker"


def status(routes=None, presets=None, **extra):
    devices = [
        {"identity": MIXER, "card": "CODEC", "name": "Mixer", "in": {"channels": 2, "muted": False}},
        {"identity": GP, "card": "GP150", "name": "GP-150", "in": {"channels": 2, "muted": False, "level": 100},
         "out": {"channels": 2, "muted": False, "level": 80}},
        {"identity": TRK, "card": "Tracker", "name": "Tracker", "in": {"channels": 2, "muted": False},
         "out": {"channels": 2, "muted": False}},
    ]
    out = {"devices": devices, "presets": presets or []}
    if routes:
        out["routes"] = routes
    out.update(extra)
    return out


def press(u, st, *events, now=0.0):
    sent = []
    for event in events:
        sent += u.handle(event, st, now)
    return sent


def text(u, st, now=0.0):
    return display.plain(u.render(st, now))


def test_every_screen_is_the_size_of_the_display():
    u = display.UI()
    st = status()
    for events in ((), ("confirm",), ("back", "cw", "confirm"), ("back", "cw", "confirm", "confirm"),
                   ("back", "back", "cw", "cw", "confirm")):
        press(u, st, *events)
        rows = u.render(st)
        assert len(rows) == display.ROWS and all(len(r.text) == display.COLS for r in rows)
        assert rows[0].inverse


def test_home_and_navigation():
    u, st = display.UI(), status()
    assert [r.rstrip() for r in text(u, st)[:4]] == ["rpi-audio", ">Presets", " Routes", " Devices"]
    press(u, st, "cw", "cw", "confirm")
    assert text(u, st)[0].strip() == "Devices"
    press(u, st, "back")
    assert text(u, st)[0].strip() == "rpi-audio"
    press(u, st, "back", "ccw", "ccw")
    assert text(u, st)[1].startswith(">Presets")   # the encoder stops at the ends
    with pytest.raises(ValueError):
        u.handle("long", st)


def test_push_does_what_confirm_does_except_where_a_screen_has_its_own_use():
    u, st = display.UI(), status()
    press(u, st, "push")   # Home -> Presets, like CONFIRM
    assert text(u, st)[0].strip() == "Presets"
    press(u, st, "back", "cw", "cw", "push", "push")   # Devices -> Mixer -> its In mute
    assert text(u, st)[0].strip() == "Mixer"
    assert press(u, st, "push", now=1.0) == [f"mute {MIXER} in on"]
    press(u, st, "back", "back", "ccw", "push")   # Routes
    assert text(u, st)[0].strip() == "Route to..."
    assert press(u, st, "push", "push") == [f"route {MIXER} {GP} src=1 dst=1"]   # Routes -> GP-150 -> Mixer on


def test_routes_screen_toggles_a_route_and_shows_it_at_once():
    u, st = display.UI(), status()
    press(u, st, "cw", "confirm")   # Routes
    assert [r.rstrip() for r in text(u, st)[1:3]] == [">GP-150", " Tracker"]   # only what has a playback
    press(u, st, "cw", "confirm")   # -> Tracker
    rows = text(u, st)
    assert rows[0].strip() == "-> Tracker"
    assert [r.rstrip() for r in rows[1:3]] == [">[ ] Mixer", " [ ] GP-150"]
    assert press(u, st, "confirm", now=10.0) == [f"route {MIXER} {TRK} src=1 dst=1"]
    assert text(u, st, 10.5)[1].startswith(">[x] Mixer")   # shown before the service has it
    on = status(routes=[{"src": MIXER, "dst": TRK}])
    assert text(u, on, 11.0)[1].startswith(">[x] Mixer") and not u.overlay   # the status caught up
    assert press(u, on, "confirm", now=11.0) == [f"unroute {MIXER} {TRK} src=1 dst=1"]
    assert text(u, on, 11.1)[1].startswith(">[ ] Mixer")
    assert text(u, on, 20.0)[1].startswith(">[x] Mixer")   # the change never arrived: the status wins again


def test_a_device_is_not_offered_to_itself_and_a_waiting_route_is_marked():
    u = display.UI()
    st = status(routes=[{"src": GP, "dst": TRK, "waiting": "starting"}])
    press(u, st, "cw", "confirm", "cw", "confirm")
    assert [r.rstrip() for r in text(u, st)[1:4]] == [">[ ] Mixer", " [~] GP-150", ""]   # Tracker: not itself
    press(u, st, "back", "ccw", "confirm")   # -> GP-150: the Tracker is a source, the GP-150 is not
    assert [r.rstrip() for r in text(u, st)[1:4]] == [">[ ] Mixer", " [ ] Tracker", ""]


def test_pairs_of_a_multichannel_device_are_rows_of_their_own():
    st = status()
    st["devices"][2]["in"]["channels"] = 8
    st["devices"][2]["out"]["channels"] = 2
    u = display.UI()
    press(u, st, "cw", "confirm", "cw", "confirm")   # -> Tracker
    names = [r.strip(">").strip() for r in text(u, st)[1:4]]
    assert names == ["[ ] Mixer", "[ ] GP-150", ""]    # the Tracker's own pairs are not offered to itself
    press(u, st, "back", "ccw", "confirm")             # -> GP-150
    names = [r.strip(">").strip() for r in text(u, st)[1:7]]
    assert names == ["[ ] Mixer", "[ ] Tracker 1-2", "[ ] Tracker 3-4", "[ ] Tracker 5-6", "[ ] Tracker 7-8", ""]
    assert press(u, st, "cw", "cw", "cw", "confirm") == [f"route {TRK} {GP} src=3 dst=1"]


def test_a_long_list_scrolls_with_the_cursor():
    st = status()
    st["devices"][2]["in"]["channels"] = 30   # fifteen pairs
    u = display.UI()
    press(u, st, "cw", "confirm", "cw", "confirm", "back", "ccw", "confirm")
    for _ in range(12):
        press(u, st, "cw")
    rows = text(u, st)
    assert len(rows) == 8 and sum(r.startswith(">") for r in rows) == 1 and rows[7].startswith(">")


def test_presets_load_and_save_with_a_question():
    st = status(presets=[{"slot": 2, "name": "Live", "saved": "x"}, {"slot": 3, "name": "", "saved": "x"}])
    u = display.UI()
    press(u, st, "confirm")
    rows = text(u, st)
    assert [r.rstrip() for r in rows[1:4]] == [">1 -empty-", " 2 Live", " 3 Preset 3"]
    assert press(u, st, "confirm") == [] and u.render(st)[-1].text.strip() == "1 is empty"
    assert press(u, st, "cw", "confirm") == ["preset load 2"] and u.render(st)[-1].text.strip() == "loaded 2"
    assert press(u, st, "push") == []
    assert text(u, st)[0].strip() == "Save preset?" and "Slot 2" in text(u, st)[2]
    assert press(u, st, "back") == [] and text(u, st)[0].strip() == "Presets"   # asked, and said no
    assert press(u, st, "push", "confirm") == ["preset save 2"] and text(u, st)[0].strip() == "Presets"


def test_device_mutes_and_levels():
    u, st = display.UI(), status()
    press(u, st, "cw", "cw", "confirm", "cw", "confirm")   # Devices -> GP-150
    assert text(u, st)[0].strip() == "GP-150"
    assert [r.strip(">").strip() for r in text(u, st)[1:5]] == ["In  mute off", "In  lvl 100%", "Out mute off",
                                                                "Out lvl 80%"]
    assert press(u, st, "ccw", "ccw", "confirm", now=1.0) == [f"mute {GP} in on"]
    assert text(u, st, 1.1)[1].startswith(">In  mute on")
    # a level: CONFIRM starts the edit, turning changes it, nothing is sent until it is set
    assert press(u, st, "cw", "confirm") == []
    assert text(u, st)[0].strip() == "Level" and ">In  lvl [100%]" in text(u, st)[2]
    assert press(u, st, "ccw", "ccw", "ccw") == [] and ">In  lvl [85%]" in text(u, st)[2]
    assert press(u, st, "cw", "cw", "cw", "cw", "cw", "cw", "cw") == []
    assert ">In  lvl [100%]" in text(u, st)[2]   # it stops at 100
    assert press(u, st, "ccw", "push", now=2.0) == [f"volume {GP} in 95"]
    assert text(u, st, 2.1)[2].startswith(">In  lvl 95%")
    # BACK drops an edit
    press(u, st, "cw", "cw", "confirm", "ccw")
    assert press(u, st, "back") == [] and text(u, st)[0].strip() == "GP-150"


def midi_status(routes=None):
    ports = [{"identity": "usb-keys", "port": 0, "name": "Keys", "in": True, "out": False},
             {"identity": TRK, "port": 0, "name": "Tracker", "in": True, "out": True},
             {"identity": "usb-synth", "port": 0, "name": "Synth", "in": True, "out": True},
             {"identity": "usb-synth", "port": 1, "name": "Synth", "in": True, "out": True}]
    return status(midi_ports=ports, **({"midi_routes": routes} if routes else {}))


def test_midi_routes_pick_a_destination_then_toggle_its_sources():
    u, st = display.UI(), midi_status()
    press(u, st, "cw", "cw", "cw", "confirm")   # Home -> MIDI
    assert text(u, st)[0].strip() == "MIDI to..."
    assert [r.rstrip() for r in text(u, st)[1:5]] == [">Tracker", " Synth 1", " Synth 2", ""]   # only what receives
    press(u, st, "confirm")
    assert text(u, st)[0].strip() == "-> Tracker"
    assert [r.rstrip() for r in text(u, st)[1:5]] == [">[ ] Keys", " [ ] Synth 1", " [ ] Synth 2", ""]
    assert press(u, st, "confirm", now=5.0) == [f"midiroute usb-keys/0 {TRK}/0"]
    assert text(u, st, 5.5)[1].startswith(">[x] Keys")   # shown before the service has it
    on = midi_status(routes=[{"src": "usb-keys/0", "dst": f"{TRK}/0"}])
    assert text(u, on, 6.0)[1].startswith(">[x] Keys") and not u.overlay
    assert press(u, on, "confirm", now=6.0) == [f"midiunroute usb-keys/0 {TRK}/0"]
    waiting = midi_status(routes=[{"src": "usb-keys/0", "dst": f"{TRK}/0", "waiting": "not here"}])
    assert text(u, waiting, 30.0)[1].startswith(">[~] Keys")


def test_a_device_is_not_offered_its_own_midi_ports():
    u, st = display.UI(), midi_status()
    press(u, st, "cw", "cw", "cw", "confirm", "cw", "confirm")   # MIDI -> Synth 1
    assert [r.strip(">").strip() for r in text(u, st)[1:4]] == ["[ ] Keys", "[ ] Tracker", ""]   # not Synth's own
    assert press(u, st, "push", now=1.0) == ["midiroute usb-keys/0 usb-synth/0"]


def test_the_midi_screen_with_no_ports_is_empty_and_the_commands_are_the_services():
    u = display.UI()
    press(u, {}, "cw", "cw", "cw", "confirm")
    assert text(u, {})[1].strip() == "(nothing here)"
    st, state = midi_status(), {}
    for events in (("cw", "cw", "cw", "confirm", "confirm", "confirm"),):
        (sent,) = press(display.UI(), st, *events)
        cmd = midi.parse_command(sent)
        state, _ = midi.apply_command(state, cmd)
    assert state["midi_routes"] == [{"src": "usb-keys/0", "dst": f"{TRK}/0"}]
    gone = midi_status()
    gone["midi_ports"] = [p for p in gone["midi_ports"] if p["identity"] != TRK]
    v = display.UI()
    press(v, st, "cw", "cw", "cw", "confirm", "confirm")
    assert text(v, gone)[0].strip() == "-> (gone)"


def test_a_local_dac_has_a_mute_and_no_level():
    st = status()
    st["devices"].append({"identity": "local-dac", "card": "sndrpihifiberry", "name": "pHAT DAC", "local": True,
                          "out": {"channels": 2, "muted": False, "fixed_level": True}})
    u = display.UI()
    press(u, st, "cw", "cw", "confirm", "cw", "cw", "cw", "confirm")   # Devices -> pHAT DAC
    assert text(u, st)[0].strip() == "pHAT DAC"
    assert [r.strip(">").strip() for r in text(u, st)[1:4]] == ["Out mute off", "", ""]
    assert press(u, st, "confirm", now=1.0) == ["mute local-dac out on"]
    press(u, st, "back", "back", "ccw", "confirm")   # Routes: the DAC is a destination like the rest
    assert [r.strip(">").strip() for r in text(u, st)[1:5]] == ["GP-150", "Tracker", "pHAT DAC", ""]


def test_a_level_edit_starts_at_a_default_when_the_device_has_none():
    u, st = display.UI(), status()
    press(u, st, "cw", "cw", "confirm", "confirm")   # Devices -> Mixer
    assert [r.strip(">").strip() for r in text(u, st)[1:3]] == ["In  mute off", "In  lvl --"]
    press(u, st, "cw", "confirm")
    assert ">In  lvl [80%]" in text(u, st)[2]


def test_a_device_that_leaves_does_not_break_the_screen():
    u, st = display.UI(), status()
    press(u, st, "cw", "cw", "confirm", "cw", "confirm")
    gone = status()
    gone["devices"] = [d for d in gone["devices"] if d["identity"] != GP]
    assert text(u, gone)[0].strip() == "(gone)" and text(u, gone)[1].strip() == "(nothing here)"
    assert press(u, gone, "confirm", "cw") == []
    none = display.UI()
    press(none, {"devices": []}, "cw", "confirm")
    assert text(none, {})[1].strip() == "(nothing here)"


def test_waiting_devices_are_marked():
    st = status()
    st["devices"][2]["in"]["blocked"] = "USB full-speed budget: needs 900 B"
    u = display.UI()
    press(u, st, "cw", "cw", "confirm")
    assert [r.strip(">").strip() for r in text(u, st)[1:4]] == ["Mixer", "GP-150", "~ Tracker"]


def test_every_command_is_one_the_service_accepts():
    """The display speaks the service's own grammar: each command parses and applies to a state."""
    saved = status(presets=[{"slot": 1, "name": "A", "saved": "x"}], routes=[{"src": MIXER, "dst": TRK}])
    scenarios = [(status(), ("cw", "confirm", "cw", "confirm", "confirm")),                  # route
                 (saved, ("cw", "confirm", "cw", "confirm", "confirm")),                     # unroute
                 (saved, ("confirm", "confirm")),                                            # preset load
                 (saved, ("confirm", "push", "confirm")),                                    # preset save
                 (saved, ("cw", "cw", "confirm", "cw", "confirm", "confirm")),               # mute
                 (saved, ("cw", "cw", "confirm", "cw", "confirm", "cw", "confirm", "cw", "push"))]   # a level
    state, verbs = {}, []
    for st, events in scenarios:
        sent = press(display.UI(), st, *events)
        assert len(sent) == 1, (events, sent)
        cmd = midi.parse_command(sent[0])
        verbs.append(cmd.verb)
        if cmd.verb != "preset":
            state, _ = midi.apply_command(state, cmd)
    assert verbs == ["route", "unroute", "preset", "preset", "mute", "volume"]
    assert state["mute"]["in"] == ["usb-gp150"] and state["volume"]["in"] == {"usb-gp150": 100}
    assert routing.from_state(state) == []   # the route was added and then removed
