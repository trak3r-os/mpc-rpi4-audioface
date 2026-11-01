# SPDX-License-Identifier: GPL-3.0-or-later
"""The encoder and the three buttons as ui.py's events. Encoder, Button and Panel are pure (levels and times in,
events out: tests/test_inputs.py); GpioReader is the only part that touches the GPIO, through libgpiod.

Wiring: every line has a pull-up and a switch to ground, so a pressed button reads 0. The encoder rests with both
lines at 1, and one detent is four transitions."""

from datetime import timedelta

PINS = {"a": 17, "b": 27, "push": 22, "confirm": 23, "back": 24}   # BCM; docs/DISPLAY.md
BUTTONS = {"push": "push", "confirm": "confirm", "back": "back"}   # line -> event
DEBOUNCE_S = 0.03
# Gray code: the step (+1 or -1) for a move from the previous (a, b) to the new one, indexed prev << 2 | new.
# +1 (clockwise) is `a` changing before `b`, as on a KY-040 (its CLK is `a`); checked on the real knob
# (docs/hw/2026-11-01-hat-oled.md). `invert` is for an encoder wired the other way round.
STEP = (0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0)


class Encoder:
    """Quadrature decoder: one +1 or -1 per detent, whatever bounces in between. An encoder rests at a different
    pair of levels depending on the model (both high, both low...), so it learns it: the state the knob is in
    after it has been still for IDLE_S is its rest, and a detent is a full turn from rest back to rest."""

    IDLE_S = 0.4

    def __init__(self, invert=False):
        self.sign = -1 if invert else 1
        self.rest = self.state = 0b11
        self.count, self.last = 0, float("-inf")

    def sync(self, a, b):
        """Starts from the levels the lines have now, taken as the rest."""
        self.rest = self.state = (a << 1) | b
        self.count = 0

    def feed(self, a, b, now=0.0):
        new = (a << 1) | b
        if new == self.state:
            return 0
        if now - self.last > self.IDLE_S:   # the knob was still: where it was is where it rests
            self.rest, self.count = self.state, 0
        self.last = now
        self.count += STEP[self.state << 2 | new]
        self.state = new
        if new == self.rest:   # back at rest: a detent was completed, or it was a partial turn
            steps, self.count = (self.count > 3) - (self.count < -3), 0
            return steps * self.sign
        return 0


class Button:
    def __init__(self, debounce=DEBOUNCE_S):
        self.debounce, self.down, self.changed = debounce, False, float("-inf")

    def feed(self, pressed, now):
        """True once for each press; changes closer together than `debounce` are bounce."""
        if pressed == self.down or now - self.changed < self.debounce:
            return False
        self.down, self.changed = pressed, now
        return pressed


class Panel:
    """Edges on the five lines in, ui.py events out."""

    def __init__(self, invert=False, debounce=DEBOUNCE_S):
        self.encoder = Encoder(invert)
        self.buttons = {name: Button(debounce) for name in BUTTONS}
        self.level = {name: 1 for name in PINS}

    def sync(self, levels):
        """Takes the levels the lines are at now (GpioReader.levels()) as the starting point."""
        self.level.update(levels)
        self.encoder.sync(self.level["a"], self.level["b"])

    def edge(self, name, level, now):
        """The line `name` is now at `level`; the events that causes, as a list."""
        self.level[name] = level
        if name in ("a", "b"):
            step = self.encoder.feed(self.level["a"], self.level["b"], now)
            return ["cw"] * step if step > 0 else ["ccw"] * -step
        if name in self.buttons and self.buttons[name].feed(level == 0, now):
            return [BUTTONS[name]]
        return []


class GpioReader:
    """Edges of the panel's lines from libgpiod 2.x: read() waits up to `timeout` s and gives [(name, level)]."""

    def __init__(self, pins=None, chip="/dev/gpiochip0"):
        import gpiod
        from gpiod.line import Bias, Direction, Edge
        self.gpiod, self.pins = gpiod, pins or PINS
        self.names = {pin: name for name, pin in self.pins.items()}
        settings = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP, edge_detection=Edge.BOTH)
        self.request = gpiod.request_lines(chip, consumer="rpi-audio-ui",
                                           config={pin: settings for pin in self.pins.values()})
        self.rising = self.gpiod.EdgeEvent.Type.RISING_EDGE

    def levels(self):
        """The levels now, {name: 0 or 1}."""
        return {self.names[line]: int(value.value) for line, value in
                zip(self.request.lines, self.request.get_values())}

    def read(self, timeout):
        if not self.request.wait_edge_events(timedelta(seconds=timeout)):
            return []
        return [(self.names[e.line_offset], int(e.event_type == self.rising)) for e in self.request.read_edge_events()]

    def close(self):
        self.request.release()
