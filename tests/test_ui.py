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


def test_overview_active_scene_and_transient_command_feedback():
    u = display.UI(overview=True)
    st = status(active_scene={'slot': 2, 'name': 'Live', 'modified': True})
    assert 'Scene: *Live' in u.render(st)[6].text
    u.stack = [display.Presets()]
    assert u.render(st)[2].badge == '*edit'
    u.message, u.message_kind, u.message_until = 'Saved', 'success', 2
    assert u.render(st, 1)[-2].icon == 'check'
    u.render(st, 3)
    assert not u.message


def test_every_screen_is_the_size_of_the_display():
    u = display.UI()
    st = status()
    for events in ((), ("confirm",), ("back", "cw", "confirm"), ("back", "cw", "confirm", "confirm"),
                   ("back", "back", "cw", "cw", "confirm")):
        press(u, st, *events)
        rows = u.render(st)
        assert len(rows) == display.ROWS and all(len(r.text) == display.COLS for r in rows)
        assert not rows[0].inverse


def test_home_and_navigation():
    u, st = display.UI(), status()
    assert [r.rstrip() for r in text(u, st)[:4]] == ["", ">Send audio", " Outputs", " Levels & mute"]
    press(u, st, "cw", "cw", "confirm")
    assert text(u, st)[0].strip() == "Levels & mute"
    press(u, st, "back")
    assert text(u, st)[0].strip() == ""
    press(u, st, "ccw", "ccw", "ccw")
    assert text(u, st)[1].startswith(">Send audio")
    with pytest.raises(ValueError):
        u.handle("long", st)


def test_push_and_confirm_follow_the_same_navigation():
    for button in ("push", "confirm"):
        u, st = display.UI(), status()
        press(u, st, button, button)
        assert press(u, st, button) == [f"route {MIXER} {GP} src=1 dst=1"]
        press(u, st, "back", "back", "cw", "cw", button, button)
        assert press(u, st, button) == [f"mute {MIXER} in on"]


def test_routes_screen_toggles_a_route_and_shows_it_at_once():
    u, st = display.UI(), status()
    press(u, st, "confirm", "confirm")
    assert [r.rstrip() for r in text(u, st)[1:3]] == [">[ ] GP-150", " [ ] Tracker"]
    press(u, st, "cw")
    assert press(u, st, "confirm", now=10.0) == [f"route {MIXER} {TRK} src=1 dst=1"]
    assert text(u, st, 10.5)[2].startswith(">[x] Tracker")
    on = status(routes=[{"src": MIXER, "dst": TRK}])
    assert text(u, on, 11.0)[2].startswith(">[x] Tracker") and not u.overlay
    assert press(u, on, "confirm", now=11.0) == [f"unroute {MIXER} {TRK} src=1"]
    assert text(u, on, 11.1)[2].startswith(">[ ] Tracker")
    assert text(u, on, 20.0)[2].startswith(">[x] Tracker")


def test_a_device_is_not_offered_to_itself_and_a_waiting_route_is_marked():
    u = display.UI()
    st = status(routes=[{"src": GP, "dst": TRK, "waiting": "starting"}])
    press(u, st, "confirm", "cw", "confirm")
    assert [r.rstrip() for r in text(u, st)[1:3]] == [">[~] Tracker", " More output pairs..."]


def test_pairs_of_a_multichannel_device_are_rows_of_their_own():
    st = status()
    st["devices"][2]["in"]["channels"] = 8
    u = display.UI()
    press(u, st, "confirm")
    names = [r.strip(">").strip() for r in text(u, st)[1:7]]
    assert names == ["Mixer", "GP-150", "Tracker 1-2", "Tracker 3-4", "Tracker 5-6", "Tracker 7-8"]
    press(u, st, "cw", "cw", "cw", "cw", "confirm")
    assert press(u, st, "confirm") == [f"route {TRK} {GP} src=3 dst=1"]


def test_a_long_list_scrolls_with_the_cursor():
    st = status()
    st["devices"][2]["in"]["channels"] = 30
    u = display.UI()
    press(u, st, "confirm", *("cw",) * 12)
    rows = text(u, st)
    assert len(rows) == 8 and sum(r.startswith(">") for r in rows) == 1 and rows[6].startswith(">")
    assert u.render(st)[7].footer


def test_scenes_load_and_confirm_before_overwriting_with_either_button():
    st = status(presets=[{"slot": 2, "name": "Live", "saved": "x"}])
    for button in ("push", "confirm"):
        u = display.UI()
        press(u, st, *("cw",) * 4, button, button)
        assert press(u, st, button) == [] and u.message == "1 is empty"
        press(u, st, "back", "cw", button)
        assert press(u, st, button) == ["preset load 2"]
        assert press(u, st, "cw", button) == []
        assert text(u, st)[0].strip() == "Save scene?"
        press(u, st, "back")
        assert text(u, st)[0].strip() == "Scene 2"
        assert press(u, st, button, button) == ["preset save 2"]


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


def test_midi_routes_pick_a_source_then_toggle_its_destinations():
    u, st = display.UI(), midi_status()
    press(u, st, "cw", "cw", "cw", "confirm")
    assert text(u, st)[0].strip() == "MIDI from..."
    assert [r.rstrip() for r in text(u, st)[1:5]] == [">Keys", " Tracker", " Synth 1", " Synth 2"]
    press(u, st, "confirm")
    assert [r.rstrip() for r in text(u, st)[1:4]] == [">[ ] Tracker", " [ ] Synth 1", " [ ] Synth 2"]
    assert press(u, st, "confirm", now=5.0) == [f"midiroute usb-keys/0 {TRK}/0"]
    assert text(u, st, 5.5)[1].startswith(">[x] Tracker")
    on = midi_status(routes=[{"src": "usb-keys/0", "dst": f"{TRK}/0"}])
    assert text(u, on, 6.0)[1].startswith(">[x] Tracker") and not u.overlay
    assert press(u, on, "confirm", now=6.0) == [f"midiunroute usb-keys/0 {TRK}/0"]
    waiting = midi_status(routes=[{"src": "usb-keys/0", "dst": f"{TRK}/0", "waiting": "not here"}])
    assert text(u, waiting, 30.0)[1].startswith(">[~] Tracker")


def test_a_device_is_not_offered_its_own_midi_ports():
    u, st = display.UI(), midi_status()
    press(u, st, "cw", "cw", "cw", "confirm", "cw", "cw", "confirm")
    assert [r.strip(">").strip() for r in text(u, st)[1:3]] == ["[ ] Tracker", ""]
    assert press(u, st, "push", now=1.0) == [f"midiroute usb-synth/0 {TRK}/0"]


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
    assert text(v, gone)[1].strip() == ">[ ] Synth 1"


def test_a_local_dac_has_a_mute_and_no_level():
    st = status()
    st["devices"].append({"identity": "local-dac", "card": "sndrpihifiberry", "name": "pHAT DAC", "local": True,
                          "out": {"channels": 2, "muted": False, "fixed_level": True}})
    u = display.UI()
    press(u, st, "cw", "cw", "confirm", "cw", "cw", "cw", "confirm")   # Devices -> pHAT DAC
    assert text(u, st)[0].strip() == "pHAT DAC"
    assert [r.strip(">").strip() for r in text(u, st)[1:4]] == ["Out mute off", "", ""]
    assert press(u, st, "confirm", now=1.0) == ["mute local-dac out on"]
    press(u, st, "back", "back", "ccw", "ccw", "confirm", "confirm")
    assert [r.strip(">").strip() for r in text(u, st)[1:4]] == ["[ ] GP-150", "[ ] Tracker", "[ ] pHAT DAC"]


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
    press(none, {"devices": []}, "confirm")
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
    scenarios = [(status(), ("confirm", "confirm", "cw", "confirm")),                  # route
                 (saved, ("confirm", "confirm", "cw", "confirm")),                     # unroute
                 (saved, (*("cw",) * 4, "confirm", "confirm", "confirm")),  # preset load
                 (saved, (*("cw",) * 4, "confirm", "confirm", "cw", "push", "confirm")),  # preset save
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


def test_settings_rows_step_to_the_next_value_and_wrap():
    u, st = display.UI({"idle_s": 600, "saver_s": 30, "saver_style": "clock", "contrast": 0xFF, "flip": True}), status()
    press(u, st, *("cw",) * 7, "confirm")   # Home -> Settings
    assert u.screen.title == "Settings"
    rows = display.plain(u.render(st))
    assert rows[1].strip() == ">Sleep   10 min" and "Saver   30 s" in rows[2] and "Style   clock" in rows[3]
    assert "Bright  100%" in rows[4] and "Flip    on" in rows[5] and "Encoder normal" in rows[6]
    sent = []
    for _ in range(6):
        sent += u.handle("confirm", st)
        u.handle("cw", st)
    assert sent == ["ui idle_s 0", "ui saver_s 60", "ui saver_style status", "ui contrast 26", "ui flip false",
                    "ui invert_encoder true"]


def test_settings_follow_the_prefs_and_back_returns_home():
    u, st = display.UI(), status()
    press(u, st, *("cw",) * 7, "confirm")
    assert "Sleep   1 min" in display.plain(u.render(st))[1]
    u.prefs["idle_s"] = 0
    assert "Sleep   never" in display.plain(u.render(st))[1]
    assert u.handle("back", st) == [] and u.screen.title == "rpi-audio"


def test_the_screensaver_moves_and_stays_on_the_screen():
    import time
    wall = time.strptime("2026-11-02 09:05", "%Y-%m-%d %H:%M")
    seen = set()
    for step in range(200):
        rows = display.saver_rows("bounce", step * display.SAVER_STEP_S)
        assert len(rows) == display.ROWS and all(len(r.text) == display.COLS for r in rows)
        lit = [(y, r.text.index("rpi-audio")) for y, r in enumerate(rows) if "rpi-audio" in r.text]
        assert len(lit) == 1 and sum(bool(r.text.strip()) for r in rows) == 1
        seen.add(lit[0])
    assert len(seen) > 20
    rows = display.saver_rows("clock", 0.0, wall)
    assert [r.text.strip() for r in rows if r.text.strip()] == ["09:05"]


def test_footer_counts_physical_devices_once_and_stays_visible_with_a_message():
    st = midi_status()
    u = display.UI()
    u.hardware = {"wifi": {"state": "up", "signal": 84}, "usb_state": "configured",
                  "devices": [{"identity": "card:KEYS", "card": "KEYS", "midi": True},
                              {"identity": "local-dac", "local": True, "out": {"channels": 2}}]}
    # Physical MIDI-only card, local DAC and three audio devices; MIDI ports do not add duplicates.
    assert u.render(st)[-1].footer == ("84%", "5", "IDLE")
    u.message = "working..."
    rows = u.render(st)
    assert rows[-2].text.strip() == "working..." and rows[-1].footer == ("84%", "5", "IDLE")


@pytest.mark.parametrize("state,extra,label", [
    ("not attached", {}, "OFF"), ("configured", {}, "IDLE"), ("suspended", {}, "SUSP"),
    ("addressed", {}, "WAIT"), ("unknown", {}, "?"),
    ("configured", {"host_capture_rate": 44100, "host_playback_rate": 44100}, "WAIT"),
    ("configured", {"host_capture_rate": 44100, "host_playback_rate": 44100,
                    "jack_ready": True, "feeder": "jack"}, "LIVE"),
    ("configured", {"host_playback_rate": 44100, "feeder": "silence"}, "SIL"),
    ("configured", {"standalone": {"card": "DAC"}, "jack_ready": True, "feeder": "jack"}, "LOC"),
])
def test_bridge_indicator_uses_connection_and_stream_state(state, extra, label):
    assert display.bridge_state(extra, {"usb_state": state}) == label


def test_connections_lists_idle_audio_midi_and_local_devices_and_handles_unplugging():
    u = display.UI()
    u.hardware = {"devices": [{"identity": "card:CODEC", "card": "CODEC", "name": "Mixer",
                               "in": {"channels": 2}, "out": {"channels": 2}, "midi": True},
                              {"identity": "card:KEYS", "card": "KEYS", "name": "Keys", "midi": True},
                              {"identity": "card:DAC", "card": "sndrpihifiberry", "name": "pHAT DAC",
                               "local": True, "out": {"channels": 2}}]}
    press(u, {}, *("cw",) * 5, "confirm")
    assert u.screen.title == "Connections"
    assert [r.text.strip("> ") for r in u.render({})[3:6]] == ["A+M Mixer", "MID Keys", "LOC pHAT DAC"]
    press(u, {}, "cw", "cw", "confirm")
    assert text(u, {})[0].strip() == "Mixer"
    assert "Audio + MIDI" in text(u, {})[1] and "In: 2 ch" in text(u, {})[4]
    # The routing identity changes when audio starts; the physical card keeps the detail screen stable.
    st = {"devices": [{"identity": "usb-mixer", "card": "CODEC", "name": "Live Mixer",
                       "in": {"channels": 2, "running": True, "rate": 48000}}]}
    assert text(u, st)[0].strip() == "Live Mixer" and "Bridged" in text(u, st)[3]
    u.hardware = {"devices": []}
    assert text(u, {})[0].strip() == "(disconnected)"


def test_a_message_does_not_hide_the_selected_item_or_the_connection_bar():
    u, st = display.UI(), status()
    press(u, st, *("cw",) * 4, "confirm", *("cw",) * 7, "confirm", "confirm")
    rows = u.render(st)
    assert rows[1].selected and rows[1].text.startswith(">Load")
    assert rows[6].text.strip() == "8 is empty" and rows[7].footer


def test_overview_startup_menu_navigation_and_real_meter_values():
    interface = display.UI(overview=True)
    st = status(host_playback_rate=44100, host_capture_rate=44100, jack_ready=True, feeder="jack")
    st["devices"][1]["in"].update(start=3, running=True)
    interface.hardware = {"usb_state": "configured"}
    interface.levels = {"in": 0.25, "out": None}
    rows = interface.render(st)
    assert rows[0].text.strip() == "Overview"
    assert rows[1].text.strip() == "USB bridge" and "44.1k" in rows[2].text
    assert rows[-1].footer[-1] == 'LIVE'
    assert "Routes 1" in rows[3].text and rows[4].meter[2] == "-12" and rows[5].meter[2] == "--"
    assert rows[7].footer
    press(interface, st, "push")
    assert interface.screen.title == "rpi-audio"
    press(interface, st, "cw", "confirm", "back", "back")
    assert interface.screen.title == "Overview"
    press(interface, st, "back")
    assert len(interface.stack) == 1


def test_channel_and_midi_mapping_show_allocated_ranges_and_saved_assignments():
    interface = display.UI()
    st = status()
    st["devices"][1]["in"].update(start=3, slots=6)
    st["devices"][1]["out"].update(start=9, channels=4)
    st["midi"] = {"endpoints": [{"endpoint": GP + "/0", "port": 2}]}
    screen = display.DeviceInfo(GP)
    details = screen.details(interface, st)
    assert "USB IN: 3-8" in details and "USB OUT: 9-12" in details
    assert "MIDI p1: cable 2" in details
    # An idle device shows saved allocations explicitly, rather than claiming they are active.
    interface.hardware = {"devices": [{"identity": GP, "card": "GP150", "in": {"channels": 2}, "midi": True}],
                          "assignments": {"in": {GP: 3}, "in_channels": {GP: 6}, "midi": {GP + "/0": 2}}}
    details = screen.details(interface, {})
    assert "IN saved: 3-8" in details and "MIDI p1 saved: 2" in details
    assert "USB map: standalone" in screen.details(interface, {"standalone": {"card": "DAC"}})


def test_output_switches_details_and_engine_confirmation():
    output = {'identity': 'network-rtp', 'name': 'Network RTP', 'state': 'disabled', 'enabled': False,
              'protocol': 'RTP/PCM', 'channels': 2, 'address': '239.69.1.1', 'port': 5004,
              'http_port': 8080, 'sdp': '/run/rpi-audio/network-rtp.sdp'}
    st = status(engine_mode='hub', outputs=[output])
    u = display.UI()
    u.hardware = {'wifi': {'ip': '192.168.2.229'}}
    press(u, st, 'cw', 'push', 'push')
    assert press(u, st, 'push') == ['output network-rtp on']
    assert 'Enabled: on' in text(u, st)[1]
    press(u, st, 'cw', 'cw', 'push')
    assert '/network-rtp.sdp' in u.screen.details(u, st)
    press(u, st, 'back', 'back', 'cw', 'push', 'cw', 'push')
    assert text(u, st)[0].strip() == 'Restart audio?'
    assert press(u, st, 'back') == []
    assert press(u, st, 'push', 'push') == ['engine host']


def test_one_source_can_select_multiple_outputs_and_specific_usb_pairs():
    st = status()
    st['devices'][0]['in']['start'] = 5
    st['devices'] += [{'identity': 'usb-host', 'name': 'USB host', 'virtual': True, 'out': {'channels': 26}},
                      {'identity': 'network-rtp', 'name': 'Network RTP', 'virtual': True, 'out': {'channels': 2}}]
    u = display.UI()
    press(u, st, 'push', 'push')
    assert press(u, st, 'push') == [f'route {MIXER} {GP} src=1 dst=1']
    press(u, st, 'cw', 'cw')
    assert press(u, st, 'push') == [f'route {MIXER} usb-host src=1 dst=3']
    press(u, st, 'cw')
    assert press(u, st, 'push') == [f'route {MIXER} network-rtp src=1 dst=1']
    press(u, st, 'cw', 'push')
    assert u.screen.title == 'Output pairs'
    # Pair choices include all 13 host pairs; loopback to the source is excluded.
    rows = u.screen.items(u, st, 0)
    assert len([r for r in rows if r[1][0][1] == 'usb-host']) == 13


def test_hub_details_show_explicit_usb_routes_instead_of_old_reservations():
    routes = [{'src': GP, 'dst': 'usb-host', 'dst_pair': 4},
              {'src': 'usb-host', 'dst': GP, 'src_pair': 2, 'waiting': 'not here'}]
    st = status(hub={'card': 'DAC'}, routes=routes)
    st['devices'][1]['in'].update(start=None, running=True)
    details = display.DeviceInfo(GP).details(display.UI(), st)
    assert 'State: Bridged' in details and 'To USB: 7-8' in details and 'From USB: 3-4 ~' in details
    assert not any('unassigned' in line for line in details if 'USB' in line)


def test_host_row_lists_profiles_and_confirms_a_change():
    st = status(outputs=[], host_profile=None, host_profiles=['akai-force', 'generic'])
    u = display.UI()
    press(u, st, 'cw', 'push', 'cw', 'push')
    assert text(u, st)[0].strip() == 'Host profiles'
    assert [(r.label, r.badge) for r in u.render(st)[1:4]] == [
        ('default', 'R*'), ('akai-force', 'R'), ('generic', 'R')]
    press(u, st, 'cw', 'push')
    assert press(u, st, 'push') == []
    assert text(u, st)[0].strip() == 'Use host profile?'
    assert press(u, st, 'push') == ['host akai-force']


def test_oled_can_save_both_host_types_without_typing_a_name():
    st = status(host_profiles=['host-1', 'generic'])
    for full, command in ((False, 'host save host-2 new'), (True, 'host save host-2 new full')):
        u = display.UI()
        u.stack = [display.HostProfiles()]
        press(u, st, *('cw',) * 3, 'push')
        assert isinstance(u.screen, display.HostSaveAs)
        if full:
            press(u, st, 'cw')
        assert press(u, st, 'push') == [command]
        assert isinstance(u.screen, display.HostProfiles)


def test_oled_profile_actions_confirm_setup_loading_and_scene_linking():
    st = status(presets=[{'slot': 3, 'name': 'Live'}], host_profiles=['studio'],
                host_profile_details={'studio': {'origin': 'user', 'kind': 'snapshot'}})
    for button in ('push', 'confirm'):
        u = display.UI()
        u.stack = [display.HostActions('studio')]
        press(u, st, button)
        assert 'Replace audio setup' in text(u, st)[2]
        assert press(u, st, 'back') == []
        press(u, st, 'cw', 'cw', button, 'cw', button)
        assert text(u, st)[0].strip() == 'Replace saved setup?'
        assert press(u, st, button) == ['host preset studio 3']


def test_output_level_editor_is_bounded_and_back_cancels():
    st = status(outputs=[{'identity': 'local-dac', 'name': 'pHAT DAC', 'enabled': True, 'level': 100}])
    for button in ('push', 'confirm'):
        u = display.UI()
        u.stack = [display.OutputActions('local-dac')]
        press(u, st, 'cw', button, 'cw')
        assert u.screen.value == 100
        press(u, st, *('ccw',) * 10)
        assert press(u, st, button) == ['output local-dac level 50']
        press(u, st, button, *('ccw',) * 40)
        assert u.screen.value == 0
        assert press(u, st, 'back') == []


def test_profile_readiness_and_session_history_have_human_readable_details():
    st = status(profile_readiness={'state': 'partial', 'issues': [{'message': 'Missing: GP-150'}]},
                session={'started': '2026-11-03 12:00:00', 'monitor_available': True, 'counters': {'xruns': 3},
                         'events': [{'id': 1, 'time': '2026-11-03 12:01:00', 'severity': 'warning',
                                     'detail': 'USB host disconnected', 'count': 1}]})
    u = display.UI()
    assert 'State: Partial' in display.ProfileReadiness().details(u, st)
    assert 'Missing: GP-150' in display.ProfileReadiness().details(u, st)
    assert 'XRuns: 3' in display.SessionInfo().details(u, st)
    u.stack = [display.RecentEvents()]
    press(u, st, 'push')
    assert isinstance(u.screen, display.EventInfo) and 'Count: 1' in u.screen.details(u, st)
