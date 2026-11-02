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
WORKING = "working..."   # on the last row while a command runs (each takes ~0.7 s on a Pi 4)


@dataclass
class Settings:
    bus: int = 1
    address: int = 0x3C
    flip: bool = False
    contrast: int = 0x7F
    idle_s: float = 60.0          # blank the display after this long without input; 0 never
    saver_s: float = 30.0         # show the screensaver after this long without input; 0 never
    saver_style: str = "bounce"
    invert_encoder: bool = False
    pins: dict = field(default_factory=lambda: dict(inputs.PINS))


KINDS = {"bus": int, "address": int, "contrast": int, "flip": bool, "invert_encoder": bool, "idle_s": float,
         "saver_s": float, "saver_style": str, "pins": dict}
RANGES = {"bus": (0, 99), "address": (0x03, 0x77), "contrast": (0, 255), "idle_s": (0, 86400),
          "saver_s": (0, 86400)}
CHOICES = {"saver_style": ui.SAVER_STYLES}
# What the Settings screen can change (ui.PREFS), and the part of a display's picture it dims while the screensaver runs.
PREF_KEYS = tuple(ui.PREFS)
SAVER_CONTRAST = 0x08


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
        elif kind is str:
            ok = value in CHOICES[key]
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
    def __init__(self, reader, make_display, load_status, run_command, settings=None, log=print,
                 save_prefs=None, clock=time.localtime):
        """reader: GpioReader-like (read(timeout) -> [(line, level)]); make_display(): a sh1106.Display or raises
        OSError; load_status(): dict or None; run_command(text): "" when it worked, else the error text;
        save_prefs(dict): keeps what the Settings screen changed; clock(): the wall time for the screensaver."""
        self.cfg = settings or Settings()
        self.save_prefs, self.clock = save_prefs, clock
        self.reader, self.make_display = reader, make_display
        self.load_status, self.run_command, self.log = load_status, run_command, log
        self.panel = inputs.Panel(invert=self.cfg.invert_encoder)
        self.ui = ui.UI(self.prefs())
        self.canvas = sh1106.Canvas()
        self.status, self.last_rows = {}, None
        self.display, self.retry_at, self.said_down = None, 0.0, False
        self.blank, self.last_input, self.next_status = False, 0.0, 0.0
        self.saving = False   # the screensaver is up

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

    def prefs(self):
        return {key: getattr(self.cfg, key) for key in PREF_KEYS}

    def set_pref(self, key, text):
        """A `ui KEY VALUE` command from the Settings screen: applies it, shows it and keeps it."""
        kind = KINDS.get(key)
        try:
            value = {bool: lambda t: {"true": True, "false": False}[t], int: int, float: float, str: str}[kind](text)
        except (KeyError, ValueError):
            return f"{key}: {text}?"
        if key not in PREF_KEYS or (kind is not bool and not self.pref_ok(key, value)):
            return f"{key}: {text}?"
        setattr(self.cfg, key, value)
        self.ui.prefs = self.prefs()
        if key == "invert_encoder":
            self.panel.encoder.sign = -1 if value else 1
        elif key in ("flip", "contrast") and self.display:
            self.safe(lambda: self.display.configure(self.cfg.flip, self.cfg.contrast))
        if self.save_prefs:
            try:
                self.save_prefs(self.prefs())
            except OSError as e:
                self.log(f"rpi-audio-ui: cannot keep the settings: {e}")
                return "not saved"
        return ""

    def pref_ok(self, key, value):
        if key in CHOICES:
            return value in CHOICES[key]
        low, high = RANGES[key]
        return low <= value <= high

    def press(self, event, now):
        self.last_input = now
        if self.blank or self.saving:   # the first touch only wakes the display
            self.wake(self.blank)
            return
        commands = self.ui.handle(event, self.status, now)
        remote = [c for c in commands if not c.startswith("ui ")]
        if remote:   # the loop is stuck in run_command: show that something is happening before it starts
            done, self.ui.message = self.ui.message, WORKING
            self.draw(now)
        for command in commands:
            if command.startswith("ui "):
                _, key, value = command.split()
                error = self.set_pref(key, value)
            else:
                error = self.run_command(command)
            if error:
                self.log(f"rpi-audio-ui: {command}: {error}")
                self.ui.message = error[:ui.COLS]
        if remote and self.ui.message == WORKING:
            self.ui.message = done

    def wake(self, dark):
        """Back from the screensaver or from dark: the display at its own contrast, and the screen drawn again."""
        self.blank = self.saving = False
        self.last_rows = None
        if self.display:
            if dark:
                self.safe(lambda: self.display.power(True))
            self.safe(lambda: self.display.contrast(self.cfg.contrast))

    def draw(self, now):
        idle = now - self.last_input
        if self.cfg.idle_s and not self.blank and idle > self.cfg.idle_s:
            self.blank = True
            if self.display:
                self.safe(lambda: self.display.power(False))
        if self.blank:
            return
        if self.display is None and now >= self.retry_at:
            try:
                self.display = self.make_display()
                self.last_rows, self.said_down, self.saving = None, False, False
                self.log("rpi-audio-ui: display ready")
            except OSError as e:
                self.retry_at = now + RETRY_S
                if not self.said_down:   # once, not every try
                    self.log(f"rpi-audio-ui: no display: {e}")
                    self.said_down = True
        if self.display is None:
            return
        if self.cfg.saver_s and idle > self.cfg.saver_s:
            if not self.saving:   # a dim display, and a picture that moves: neither burns in
                self.saving = self.safe(lambda: self.display.contrast(SAVER_CONTRAST))
                if self.display is None:
                    return
            rows = ui.saver_rows(self.cfg.saver_style, now, self.clock())
        else:
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
