# SPDX-License-Identifier: GPL-3.0-or-later
"""The display service's loop (bridge/rpi-audio-ui/uiservice.py), run with a pretend GPIO, display and service."""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge" / "rpi-audio-ui"))
import inputs  # noqa: E402
import uiservice  # noqa: E402

STATUS = {"devices": [{"identity": "usb-mixer", "card": "CODEC", "name": "Mixer", "in": {"channels": 2}},
                      {"identity": "usb-trk", "card": "Tracker", "name": "Tracker", "in": {"channels": 2},
                       "out": {"channels": 2}}], "presets": []}


class Reader:
    """The lines at rest; feed() queues edges that the next read() gives."""

    def __init__(self):
        self.queue = []

    def levels(self):
        return {name: 1 for name in inputs.PINS}

    def read(self, timeout):
        out, self.queue = self.queue, []
        return out

    def feed(self, *edges):
        self.queue += edges


class Screen:
    def __init__(self):
        self.shown, self.powered = [], []

    def show(self, canvas):
        self.shown.append(bytes(b for page in canvas.pages for b in page))

    def power(self, on):
        self.powered.append(on)


class Rig:
    def __init__(self, **settings):
        self.reader, self.screen, self.status, self.commands = Reader(), Screen(), dict(STATUS), []
        self.errors, self.logs, self.broken = {}, [], 0
        self.app = uiservice.App(self.reader, self.make_display, lambda: self.status, self.run,
                                 uiservice.Settings(**settings), self.logs.append)
        self.app.start(0.0)
        self.now = 0.0

    def make_display(self):
        if self.broken:
            raise OSError("no device")
        return self.screen

    def run(self, text):
        self.commands.append(text)
        return self.errors.get(text, "")

    def step(self, dt=0.1):
        self.now += dt
        self.app.step(self.now)

    def press(self, name):
        """A button: down, then up a moment later."""
        self.reader.feed((name, 0))
        self.step(0.1)
        self.reader.feed((name, 1))
        self.step(0.1)

    def turn(self, detents):
        """The encoder, one detent per unit: positive clockwise (the edges of tests/test_inputs.py)."""
        for _ in range(abs(detents)):
            edges = (("a", 0), ("b", 0), ("a", 1), ("b", 1)) if detents > 0 else \
                    (("b", 0), ("a", 0), ("b", 1), ("a", 1))
            for edge in edges:
                self.reader.feed(edge)
                self.step(0.01)
            self.step(0.05)


def test_settings_defaults_and_overrides():
    cfg, warnings = uiservice.settings({})
    assert (cfg.bus, cfg.address, cfg.flip, cfg.idle_s) == (1, 0x3C, False, 60.0)
    assert cfg.pins == inputs.PINS and not warnings
    cfg, warnings = uiservice.settings({"bus": 3, "address": 0x3D, "flip": True, "idle_s": 0, "invert_encoder": True,
                                        "pins": {"a": 5}})
    assert (cfg.bus, cfg.address, cfg.flip, cfg.idle_s, cfg.invert_encoder) == (3, 0x3D, True, 0, True)
    assert cfg.pins == {**inputs.PINS, "a": 5} and not warnings
    assert uiservice.settings({"idle_s": 2.5})[0].idle_s == 2.5


def test_settings_keep_the_default_and_say_why_for_a_bad_key():
    bad = {"bus": True, "address": 0x80, "flip": 1, "idle_s": "never", "contrast": 300, "colour": 1,
           "pins": {"a": 99}}
    cfg, warnings = uiservice.settings(bad)
    assert cfg == uiservice.Settings() and len(warnings) == len(bad)
    assert "[ui] colour: unknown key, ignored" in warnings and "[ui] bus: wrong value, ignored" in warnings
    assert uiservice.settings({"pins": {"x": 1}})[1] == ["[ui] pins: wrong value, ignored"]
    assert uiservice.settings(None) == (uiservice.Settings(), [])


def test_read_status(tmp_path):
    path = tmp_path / "status.json"
    assert uiservice.read_status(path) is None
    path.write_text("{")
    assert uiservice.read_status(path) is None
    path.write_text("[1]")
    assert uiservice.read_status(path) is None
    path.write_text(json.dumps(STATUS))
    assert uiservice.read_status(path) == STATUS
    old = time.time() - uiservice.STALE_S - 1
    os.utime(path, (old, old))
    assert uiservice.read_status(path) is None   # rpi-audiod stopped writing it


def test_the_first_pass_draws_the_home_screen_once():
    rig = Rig()
    rig.step()
    assert len(rig.screen.shown) == 1
    rig.step()
    assert len(rig.screen.shown) == 1   # nothing changed, nothing sent to the display


def test_the_encoder_and_buttons_drive_the_menus_and_a_command_runs():
    rig = Rig()
    rig.step()
    rig.turn(2)
    rig.press("confirm")   # Home -> Devices
    assert rig.app.ui.screen.title == "Devices"
    rig.press("confirm")   # -> Mixer
    rig.press("confirm")   # its In mute
    assert rig.commands == ["mute usb-mixer in on"]
    rig.press("back")
    rig.press("back")
    assert rig.app.ui.screen.title == "rpi-audio"
    rig.turn(-1)
    assert rig.commands == ["mute usb-mixer in on"]


def test_a_command_that_fails_is_shown_and_logged():
    rig = Rig()
    rig.errors["preset load 1"] = "preset 1 is empty"
    rig.step()
    rig.status = {**STATUS, "presets": [{"slot": 1, "name": "A", "saved": "x"}]}
    rig.step(1.0)
    rig.press("confirm")   # Presets
    rig.press("confirm")   # load 1
    assert rig.commands == ["preset load 1"]
    assert rig.app.ui.render(rig.app.status)[-1].text.strip() == "preset 1 is empty"
    assert any("preset load 1: preset 1 is empty" in line for line in rig.logs)


def test_without_a_status_the_last_row_says_so_and_it_clears():
    rig = Rig()
    rig.status = None
    rig.app.load_status = lambda: rig.status
    rig.step(1.0)
    assert rig.screen.shown and rig.app.status == {}
    first = rig.screen.shown[-1]
    rig.status = dict(STATUS)
    rig.step(1.0)
    assert rig.app.status == STATUS and rig.screen.shown[-1] != first


def test_the_display_goes_dark_when_idle_and_the_first_touch_only_wakes_it():
    rig = Rig(idle_s=30.0)
    rig.step()
    shown = len(rig.screen.shown)
    rig.step(29.0)
    assert rig.screen.powered == []
    rig.step(2.0)
    assert rig.screen.powered == [False]
    rig.status = {**STATUS, "presets": [{"slot": 1, "name": "A", "saved": "x"}]}
    rig.step(1.0)
    assert len(rig.screen.shown) == shown   # nothing is drawn on a dark display
    rig.press("confirm")   # wakes
    assert rig.screen.powered == [False, True] and rig.app.ui.screen.title == "rpi-audio" and not rig.commands
    assert len(rig.screen.shown) > shown   # and draws again
    rig.press("confirm")
    assert rig.app.ui.screen.title == "Presets"


def test_idle_zero_never_blanks():
    rig = Rig(idle_s=0)
    rig.step(10000.0)
    assert rig.screen.powered == []


def test_a_missing_display_is_tried_again_and_reported_once():
    rig = Rig()
    rig.broken = 1
    rig.step()
    rig.step(uiservice.RETRY_S / 2)
    assert rig.screen.shown == [] and rig.logs == ["rpi-audio-ui: no display: no device"]
    rig.step(uiservice.RETRY_S)
    assert rig.screen.shown == [] and len(rig.logs) == 1   # tried again, still gone, not repeated
    rig.press("confirm")   # the controls still work with no display
    assert rig.app.ui.screen.title == "Presets"
    rig.broken = 0
    rig.step(uiservice.RETRY_S + 1)
    assert len(rig.screen.shown) == 1 and rig.logs[-1] == "rpi-audio-ui: display ready"


def test_an_i2c_error_drops_the_display_and_it_comes_back():
    rig = Rig()
    rig.step()
    shown = len(rig.screen.shown)

    def fail(canvas):
        raise OSError(121, "Remote I/O error")
    rig.screen.show = fail
    rig.press("confirm")
    assert rig.app.display is None and any("display error" in line for line in rig.logs)
    rig.screen.show = Screen.show.__get__(rig.screen)
    rig.step(1.0)
    assert rig.app.display is rig.screen and len(rig.screen.shown) == shown + 1


def test_close_leaves_the_display_dark():
    rig = Rig()
    rig.step()
    rig.app.close()
    assert rig.screen.powered == [False]
    Rig().app.close()   # and does nothing without one
