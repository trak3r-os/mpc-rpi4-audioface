# SPDX-License-Identifier: GPL-3.0-or-later
"""The display service's logic: what to do on each pass of its loop. App takes edges from a reader, feeds the
panel and the interface, runs the commands they ask for, and draws the rows on the display when they change,
blanking it after a while without input (an OLED burns in). The reader, the display, the status and the commands
are passed in, so tests/test_uiservice.py runs it all with fakes; bridge/rpi-audio-ui/rpi-audio-ui is the thin
program that passes in the real ones. The audio never depends on this: a display that is missing or fails is
retried every RETRY_S and nothing else happens."""

import json
import os
import time
from dataclasses import dataclass, field

import inputs
import render
import sh1106
import ui

STATUS_S = 0.5       # how often the service's status is read
STALE_S = 10.0       # a status file older than this is not rpi-audiod's any more (it writes one every 2 s)
RETRY_S = 5.0        # between tries to reach the display
NO_SERVICE = "no rpi-audiod status"


@dataclass
class Settings:
    bus: int = 1
    address: int = 0x3C
    flip: bool = False
    contrast: int = 0x7F
    idle_s: float = 60.0          # blank the display after this long without input; 0 never
    invert_encoder: bool = False
    pins: dict = field(default_factory=lambda: dict(inputs.PINS))


KINDS = {"bus": int, "address": int, "contrast": int, "flip": bool, "invert_encoder": bool, "idle_s": float,
         "pins": dict}
RANGES = {"bus": (0, 99), "address": (0x03, 0x77), "contrast": (0, 255), "idle_s": (0, 86400)}


def whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def settings(table):
    """Settings from the [ui] table of rpi-audio.toml; a key that is unknown or has a wrong value keeps its default
    and is named in the warnings. Returns (Settings, [warning])."""
    out, warnings = Settings(), []
    for key, value in (table or {}).items():
        kind = KINDS.get(key)
        if kind is None:
            warnings.append(f"[ui] {key}: unknown key, ignored")
            continue
        if kind is bool:
            ok = isinstance(value, bool)
        elif kind is dict:
            ok = isinstance(value, dict) and set(value) <= set(inputs.PINS)
            ok = ok and all(whole(v) and 0 <= v < 64 for v in value.values())
            value = {**inputs.PINS, **value} if ok else value
        else:
            low, high = RANGES[key]
            ok = (whole(value) if kind is int else whole(value) or isinstance(value, float)) and low <= value <= high
        if ok:
            setattr(out, key, value)
        else:
            warnings.append(f"[ui] {key}: wrong value, ignored")
    return out, warnings


def read_status(path):
    """The service's status.json as a dict, or None when it is missing, unreadable or stale."""
    try:
        with open(path) as f:
            data = json.load(f)
            age = time.time() - os.fstat(f.fileno()).st_mtime
    except (OSError, ValueError):
        return None
    if age > STALE_S:
        return None
    return data if isinstance(data, dict) else None


class App:
    def __init__(self, reader, make_display, load_status, run_command, settings=None, log=print):
        """reader: GpioReader-like (read(timeout) -> [(line, level)]); make_display(): a sh1106.Display or raises
        OSError; load_status(): dict or None; run_command(text): "" when it worked, else the error text."""
        self.cfg = settings or Settings()
        self.reader, self.make_display = reader, make_display
        self.load_status, self.run_command, self.log = load_status, run_command, log
        self.panel = inputs.Panel(invert=self.cfg.invert_encoder)
        self.ui = ui.UI()
        self.canvas = sh1106.Canvas()
        self.status, self.last_rows = {}, None
        self.display, self.retry_at, self.said_down = None, 0.0, False
        self.blank, self.last_input, self.next_status = False, 0.0, 0.0

    def start(self, now):
        """Takes the lines' levels as the starting point; call once before step()."""
        self.panel.sync(self.reader.levels())
        self.last_input = now

    def step(self, now, timeout=0.05):
        for name, level in self.reader.read(timeout):
            for event in self.panel.edge(name, level, now):
                self.press(event, now)
        if now >= self.next_status:
            self.status = self.load_status() or {}
            self.next_status = now + STATUS_S
        self.draw(now)

    def press(self, event, now):
        self.last_input = now
        if self.blank:   # the first touch only wakes the display
            self.blank, self.last_rows = False, None
            if self.display:
                self.safe(lambda: self.display.power(True))
            return
        for command in self.ui.handle(event, self.status, now):
            error = self.run_command(command)
            if error:
                self.log(f"rpi-audio-ui: {command}: {error}")
                self.ui.message = error[:ui.COLS]

    def draw(self, now):
        if self.cfg.idle_s and not self.blank and now - self.last_input > self.cfg.idle_s:
            self.blank = True
            if self.display:
                self.safe(lambda: self.display.power(False))
        if self.blank:
            return
        if self.display is None and now >= self.retry_at:
            try:
                self.display = self.make_display()
                self.last_rows, self.said_down = None, False
                self.log("rpi-audio-ui: display ready")
            except OSError as e:
                self.retry_at = now + RETRY_S
                if not self.said_down:   # once, not every try
                    self.log(f"rpi-audio-ui: no display: {e}")
                    self.said_down = True
        if self.display is None:
            return
        rows = self.ui.render(self.status, now)
        if not self.status:
            rows[-1] = ui.Row(ui.fit(NO_SERVICE), True)
        if rows != self.last_rows:
            if self.safe(lambda: self.display.show(render.draw_rows(self.canvas, rows))):
                self.last_rows = rows

    def close(self):
        """Leaves the display dark (a lit OLED left on the last screen burns in)."""
        if self.display:
            self.safe(lambda: self.display.power(False))

    def safe(self, action):
        """Runs a display action; an I2C error drops the display (it is tried again in RETRY_S)."""
        try:
            action()
            return True
        except OSError as e:
            self.log(f"rpi-audio-ui: display error: {e}")
            self.display, self.retry_at, self.said_down = None, 0.0, True
            return False
