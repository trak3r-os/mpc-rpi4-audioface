#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plays the small-display interface (bridge/rpi-audio-ui/ui.py) in a terminal, against a pretend
service: some devices, the real command parser and the real route and preset logic of rpi-audiod,
and a one second delay before a command shows in the status, like the real one. No hardware needed.

  left/right or a/d   turn the encoder        space or p   its push button
  enter               CONFIRM                 b, backspace or esc   BACK        x or ctrl-c   quit"""

import os
import select
import sys
import termios
import time
import tty
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "bridge" / "rpi-audio-ui"), str(ROOT / "bridge" / "rpi-audiod")]
import midi  # noqa: E402
import midiroute  # noqa: E402
import presets  # noqa: E402
import routing  # noqa: E402
import ui as display  # noqa: E402

DELAY = 1.0   # seconds before a command shows in the status (the service looks within 0.5 s, writes every 2 s)
DEMO = [("usb-mixer", "CODEC", "Mixer", 2, 0), ("usb-gp150", "GP150", "GP-150", 2, 2),
        ("usb-tracker", "Tracker", "Tracker", 2, 2), ("usb-keys", "Keys", "Keys", 8, 0)]   # id, card, name, in, out
# id, name, port, sends, receives
MIDI_PORTS = [("usb-keys", "Keys", 0, True, False), ("usb-tracker", "Tracker", 0, True, True),
              ("usb-synth", "Synth", 0, True, True), ("usb-synth", "Synth", 1, True, True)]
KEYS = {"\x1b[C": "cw", "d": "cw", "\x1b[D": "ccw", "a": "ccw", " ": "push", "p": "push", "\r": "confirm",
        "\n": "confirm", "b": "back", "\x7f": "back", "\x1b": "back"}


class Service:
    """slots.json and presets.json in memory, and the status they make."""

    def __init__(self, devices=DEMO):
        self.devices, self.state, self.store = devices, {}, {}

    def run(self, line):
        """Applies one command the way rpi-audiod does; the error text, or "" when it worked."""
        try:
            cmd = midi.parse_command(line)
            if cmd.verb == "preset":
                self.state, self.store = midi.apply_preset(self.state, self.store, cmd, time.strftime("%Y-%m-%d %H:%M"))
            else:
                self.state, _ = midi.apply_command(self.state, cmd)
        except ValueError as e:
            return str(e)
        return ""

    def status(self):
        present = {d[0] for d in self.devices}
        devices = []
        for identity, card, name, channels_in, channels_out in self.devices:
            entry = {"identity": identity, "card": card, "name": name}
            for side, channels in (("in", channels_in), ("out", channels_out)):
                if channels:
                    entry[side] = {"channels": channels, "muted": identity in self.state.get("mute", {}).get(side, []),
                                   "level": self.state.get("volume", {}).get(side, {}).get(identity)}
            devices.append(entry)
        routes = [{**routing.entry(r), "waiting": None if {r.src, r.dst} <= present else "not here"}
                  for r in routing.from_state(self.state)]
        ports = [{"identity": i, "port": port, "name": name, "in": sends, "out": gets}
                 for i, name, port, sends, gets in MIDI_PORTS]
        links = [{**midiroute.entry(k), "waiting": None} for k in midiroute.from_state(self.state)]
        return {"devices": devices, "presets": presets.summary(self.store), "midi_ports": ports,
                **({"routes": routes} if routes else {}), **({"midi_routes": links} if links else {})}


def draw(rows, service_log):
    out = ["\x1b[2J\x1b[H", "+" + "-" * display.COLS + "+\r\n"]
    for row in rows:
        out.append("|" + (f"\x1b[7m{row.text}\x1b[0m" if row.inverse else row.text) + "|\r\n")
    out += ["+" + "-" * display.COLS + "+\r\n", "\r\n", service_log, "\r\n"]
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def read_key(fd):
    data = os.read(fd, 8).decode(errors="ignore")
    while data and data not in KEYS and data[0] == "\x1b" and len(data) < 3 and select.select([fd], [], [], 0.02)[0]:
        data += os.read(fd, 8).decode(errors="ignore")
    return data


def main():
    service, interface, due, log = Service(), display.UI(), [], ""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            now = time.monotonic()
            for when, line in [d for d in due if d[0] <= now]:
                error = service.run(line)
                log = f"{line}: {error}" if error else f"applied: {line}"
            due = [d for d in due if d[0] > now]
            draw(interface.render(service.status(), now), log)
            if not select.select([fd], [], [], 0.25)[0]:
                continue
            key = read_key(fd)
            if key in ("x", "\x03"):
                break
            if key in KEYS:
                for line in interface.handle(KEYS[key], service.status(), time.monotonic()):
                    due.append((time.monotonic() + DELAY, line))
                    log = f"sent: {line}"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[0m\r\n")


if __name__ == "__main__":
    main()
