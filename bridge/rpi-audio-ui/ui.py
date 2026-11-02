# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audio's small-display interface: a state machine from an encoder with three buttons to rows of
text, and from what the user does to the commands of docs/MIDI.md. It reads the service's status
(status.json) and only ever answers with command strings (`route A B src=1 dst=1`, `mute ID in on`,
`preset load 2`...), the same ones the command line and the MIDI control port take, so the display is
one more client and the audio never depends on it. Nothing here touches hardware or the system:
tests/test_ui.py checks it, tools/ui-sim.py plays it in a terminal, and a display driver only has to
draw render()'s rows and feed handle() the events.

Events: "cw" and "ccw" (the encoder turns), "push" (its button), "confirm" and "back".
Display: ROWS rows of COLS characters, the first one a title."""

import time
from dataclasses import dataclass

COLS, ROWS = 21, 8   # 6x8-pixel cells on a 128x64 display (bridge/rpi-audio-ui/font5x7.py)
BODY = ROWS - 1            # rows under the title
LEVEL_STEP = 5             # percent per encoder click
LEVEL_DEFAULT = 80         # where an edit starts when the device has no stored level
OPTIMISM_S = 4.0           # how long a change is shown as made while the status has not caught up
SIDES = (("in", "In"), ("out", "Out"))   # a device's capture (what it sends) and playback (what it gets)
EVENTS = ("cw", "ccw", "push", "confirm", "back")

# The Settings screen: each row cycles through these on CONFIRM. A choice is a `ui KEY VALUE` command, which the
# display service applies itself (uiservice.App.set_pref) instead of sending it to rpi-audiod.
SLEEP_STEPS = (0, 15, 30, 60, 120, 300, 600)       # seconds without input before the display goes dark; 0 never
SAVER_STEPS = (0, 10, 20, 30, 60, 120, 300)        # ... before the screensaver; 0 off
SAVER_STYLES = ("bounce", "clock")
CONTRAST_STEPS = (0x1A, 0x40, 0x7F, 0xBF, 0xFF)    # the panel's contrast register: 10, 25, 50, 75 and 100 %
SAVER_STEP_S = 3.0                                  # the screensaver's picture moves one cell this often
PREFS = {"idle_s": 60, "saver_s": 30, "saver_style": "bounce", "contrast": 0x7F, "flip": False,
         "invert_encoder": False}


@dataclass(frozen=True)
class Row:
    text: str
    inverse: bool = False


def fit(text, width=COLS):
    return text[:width].ljust(width)


def device_label(dev):
    return dev.get("name") or dev.get("card") or dev.get("identity", "?")


def pair_count(channels):
    return max((channels + 1) // 2, 1)


def pair_label(dev, side, pair):
    """The device's name, with the channels of the pair when it has more than one."""
    channels = (dev.get(side) or {}).get("channels", 2)
    if pair_count(channels) == 1:
        return device_label(dev)
    last = min(2 * pair, channels)
    return f"{device_label(dev)} {2 * pair - 1}" + (f"-{last}" if last > 2 * pair - 1 else "")


def endpoints(status, side):
    """[(device, pair)] for every stereo pair of the devices that have `side` ("in": sources, "out":
    destinations)."""
    return [(dev, pair) for dev in status.get("devices", []) if side in dev
            for pair in range(1, pair_count(dev[side].get("channels", 2)) + 1)]


def route_key(src, dst, src_pair, dst_pair):
    return (src, dst, src_pair, dst_pair)


def midi_ends(status, side):
    """[(label, endpoint)] for the MIDI ports that send (`side` "in") or receive ("out"), from the status's
    midi_ports. The endpoint is IDENTITY/PORT; a device with several such ports gets the port number in its label
    (from 1), as the sequencer numbers them from 0."""
    ports = [p for p in status.get("midi_ports", []) if p.get(side)]
    many = {p["identity"] for p in ports if sum(q["identity"] == p["identity"] for q in ports) > 1}
    return [((p.get("name") or p["identity"]) + (f" {p['port'] + 1}" if p["identity"] in many else ""),
             f"{p['identity']}/{p['port']}") for p in ports]


def stored_midi_routes(status):
    """{(src endpoint, dst endpoint): waiting reason or None} from the status."""
    return {(r["src"], r["dst"]): r.get("waiting") for r in status.get("midi_routes", [])}


def stored_routes(status):
    """{(src, dst, src pair, dst pair): waiting reason or None} from the status."""
    return {route_key(r["src"], r["dst"], r.get("src_pair", 1), r.get("dst_pair", 1)): r.get("waiting")
            for r in status.get("routes", [])}


class Menu:
    """A list the encoder moves through; CONFIRM acts on the row, PUSH does too unless the screen says otherwise."""
    title = ""

    def __init__(self):
        self.cursor = self.top = 0

    def items(self, ui, status, now):
        """[(text, payload)]; only these rows can be selected."""
        raise NotImplementedError

    def select(self, ui, payload, status, now):
        return []

    def press(self, ui, payload, status, now):
        """The encoder's push: the same as CONFIRM unless the screen has its own use for it."""
        return self.select(ui, payload, status, now)

    def heading(self, ui, status):
        return self.title

    def handle(self, event, ui, status, now):
        items = self.items(ui, status, now)
        self.cursor = min(self.cursor, max(len(items) - 1, 0))
        if event == "back":
            if len(ui.stack) > 1:
                ui.stack.pop()
        elif event == "cw":
            self.cursor = min(self.cursor + 1, max(len(items) - 1, 0))
        elif event == "ccw":
            self.cursor = max(self.cursor - 1, 0)
        elif items and event in ("confirm", "push"):
            act = self.select if event == "confirm" else self.press
            return act(ui, items[self.cursor][1], status, now)
        return []

    def rows(self, ui, status, now):
        items = self.items(ui, status, now)
        self.cursor = min(self.cursor, max(len(items) - 1, 0))
        self.top = min(max(self.top, self.cursor - BODY + 1), self.cursor)
        out = [Row(fit(self.heading(ui, status)), True)]
        if not items:
            out.append(Row(fit(" (nothing here)")))
        for n, (text, _) in list(enumerate(items))[self.top:self.top + BODY]:
            out.append(Row(fit((">" if n == self.cursor else " ") + text)))
        return out


class Home(Menu):
    title = "rpi-audio"

    def items(self, ui, status, now):
        return [("Presets", Presets), ("Routes", Routes), ("Devices", Devices), ("MIDI", MidiTo),
                ("Settings", Settings)]

    def select(self, ui, payload, status, now):
        ui.stack.append(payload())
        return []


def seconds(value, zero):
    """15 s, 2 min...; `zero` is what 0 is called."""
    value = int(value)   # the service keeps these as floats
    if not value:
        return zero
    return f"{value} s" if value < 60 else f"{value // 60} min"


def following(steps, value):
    """The first step above `value`; the first step when there is none (wrapping round)."""
    return next((step for step in steps if step > value), steps[0])


class Settings(Menu):
    """The display's own settings. CONFIRM (or PUSH) steps a row to its next value and wraps; the display service
    applies it at once and keeps it across restarts."""
    title = "Settings"

    def items(self, ui, status, now):
        p = ui.prefs
        nxt = lambda key, steps: ("ui", key, following(steps, p[key]))   # noqa: E731
        contrast = p["contrast"]
        style = SAVER_STYLES[(SAVER_STYLES.index(p["saver_style"]) + 1) % len(SAVER_STYLES)]
        return [
            (f"Sleep   {seconds(p['idle_s'], 'never')}", nxt("idle_s", SLEEP_STEPS)),
            (f"Saver   {seconds(p['saver_s'], 'off')}", nxt("saver_s", SAVER_STEPS)),
            (f"Style   {p['saver_style']}", ("ui", "saver_style", style)),
            (f"Bright  {round(contrast * 100 / 255)}%", nxt("contrast", CONTRAST_STEPS)),
            (f"Flip    {'on' if p['flip'] else 'off'}", ("ui", "flip", not p["flip"])),
            (f"Encoder {'reversed' if p['invert_encoder'] else 'normal'}",
             ("ui", "invert_encoder", not p["invert_encoder"])),
        ]

    def select(self, ui, payload, status, now):
        _, key, value = payload
        return [f"ui {key} {str(value).lower()}"]


def tri(n, size):
    """A triangle wave: 0, 1... size, size-1... 0, repeating: a position that bounces between 0 and `size`."""
    n %= 2 * size or 1
    return n if n <= size else 2 * size - n


def saver_rows(style, now, wall=None):
    """The screensaver: ROWS blank rows with a word that drifts a cell every SAVER_STEP_S, so no pixel stays lit
    (an OLED burns in). "bounce" is the name, "clock" the time (`wall`, a time.struct_time)."""
    text = time.strftime("%H:%M", wall or time.localtime()) if style == "clock" else "rpi-audio"
    step = int(now // SAVER_STEP_S)
    x, y = tri(step, COLS - len(text)), tri(step, ROWS - 1)
    rows = [Row(fit(""))] * ROWS
    rows[y] = Row(fit(" " * x + text))
    return rows


class Presets(Menu):
    """CONFIRM loads a preset, PUSH saves the routing into it (after asking)."""
    title = "Presets"

    def items(self, ui, status, now):
        saved = {p["slot"]: p.get("name", "") for p in status.get("presets", [])}
        return [(f"{n} {saved[n] or 'Preset ' + str(n)}" if n in saved else f"{n} -empty-", n) for n in range(1, 9)]

    def select(self, ui, slot, status, now):
        if not any(p["slot"] == slot for p in status.get("presets", [])):
            ui.message = f"{slot} is empty"
            return []
        ui.message = f"loaded {slot}"
        return [f"preset load {slot}"]

    def press(self, ui, slot, status, now):
        ui.stack.append(Confirm("Save preset?", f"Slot {slot}", [f"preset save {slot}"], f"saved {slot}"))
        return []


class Confirm:
    """A yes/no question: CONFIRM runs the commands, BACK drops it."""

    def __init__(self, title, text, commands, done):
        self.title, self.text, self.commands, self.done = title, text, commands, done

    def handle(self, event, ui, status, now):
        if event == "back":
            ui.stack.pop()
        elif event == "confirm":
            ui.stack.pop()
            ui.message = self.done
            return list(self.commands)
        return []

    def rows(self, ui, status, now):
        return [Row(fit(self.title), True), Row(fit("")), Row(fit(" " + self.text)), Row(fit("")),
                Row(fit(" CONFIRM = yes")), Row(fit(" BACK    = no"))]


class Routes(Menu):
    """Destinations: pick where a signal should go, then which sources feed it."""
    title = "Route to..."

    def items(self, ui, status, now):
        return [(pair_label(dev, "out", pair), (dev["identity"], pair)) for dev, pair in endpoints(status, "out")]

    def select(self, ui, dst, status, now):
        ui.stack.append(Sources(*dst))
        return []


class Sources(Menu):
    """The sources that can feed one destination pair; CONFIRM turns each on or off."""

    def __init__(self, dst, dst_pair):
        super().__init__()
        self.dst, self.dst_pair = dst, dst_pair

    def heading(self, ui, status):
        dev = next((d for d in status.get("devices", []) if d["identity"] == self.dst), {})
        return "-> " + pair_label(dev, "out", self.dst_pair) if dev else "-> (gone)"

    def items(self, ui, status, now):
        stored = stored_routes(status)
        out = []
        for dev, pair in endpoints(status, "in"):
            if dev["identity"] == self.dst:
                continue   # a device is never routed to itself (docs/MIDI.md)
            key = route_key(dev["identity"], self.dst, pair, self.dst_pair)
            on = ui.shown(("route",) + key, key in stored, now)
            waiting = on and stored.get(key) is not None
            out.append((("[~] " if waiting else "[x] " if on else "[ ] ") + pair_label(dev, "in", pair), (key, on)))
        return out

    def select(self, ui, payload, status, now):
        key, on = payload
        src, dst, src_pair, dst_pair = key
        ui.overlay[("route",) + key] = (not on, now + OPTIMISM_S)
        verb = "unroute" if on else "route"
        return [f"{verb} {src} {dst} src={src_pair} dst={dst_pair}"]


class MidiTo(Menu):
    """MIDI destinations: pick the port that should receive, then which ports feed it."""
    title = "MIDI to..."

    def items(self, ui, status, now):
        return midi_ends(status, "out")

    def select(self, ui, dst, status, now):
        ui.stack.append(MidiFrom(dst))
        return []


class MidiFrom(Menu):
    """The MIDI ports that can feed one destination; CONFIRM turns each on or off."""

    def __init__(self, dst):
        super().__init__()
        self.dst = dst

    def heading(self, ui, status):
        label = next((name for name, end in midi_ends(status, "out") if end == self.dst), None)
        return "-> " + label if label else "-> (gone)"

    def items(self, ui, status, now):
        stored = stored_midi_routes(status)
        out = []
        for name, src in midi_ends(status, "in"):
            if src.rpartition("/")[0] == self.dst.rpartition("/")[0]:
                continue   # a device is never routed to itself
            on = ui.shown(("midi", src, self.dst), (src, self.dst) in stored, now)
            waiting = on and stored.get((src, self.dst)) is not None
            out.append((("[~] " if waiting else "[x] " if on else "[ ] ") + name, (src, on)))
        return out

    def select(self, ui, payload, status, now):
        src, on = payload
        ui.overlay[("midi", src, self.dst)] = (not on, now + OPTIMISM_S)
        return [f"{'midiunroute' if on else 'midiroute'} {src} {self.dst}"]


class Devices(Menu):
    title = "Devices"

    def items(self, ui, status, now):
        out = []
        for dev in status.get("devices", []):
            waits = any((dev.get(side) or {}).get("blocked") for side, _ in SIDES)
            out.append((("~ " if waits else "") + device_label(dev), dev["identity"]))
        return out

    def select(self, ui, identity, status, now):
        ui.stack.append(Device(identity))
        return []


class Device(Menu):
    """One device's mutes and levels. CONFIRM toggles a mute or starts a level edit; in an edit the
    encoder changes the level and CONFIRM or PUSH sets it (BACK drops it)."""

    def __init__(self, identity):
        super().__init__()
        self.identity = identity
        self.editing = None   # (side, level) while a level is being changed

    def device(self, status):
        return next((d for d in status.get("devices", []) if d["identity"] == self.identity), {})

    def heading(self, ui, status):
        dev = self.device(status)
        return ("Level" if self.editing else device_label(dev)) if dev else "(gone)"

    def items(self, ui, status, now):
        dev, out = self.device(status), []
        for side, name in SIDES:
            if side not in dev:
                continue
            info = dev[side]
            muted = ui.shown(("mute", self.identity, side), bool(info.get("muted")), now)
            out.append((f"{name:<4}mute {'on' if muted else 'off'}", ("mute", side, muted)))
            if info.get("fixed_level"):
                continue   # a DAC with no volume of its own
            if self.editing and self.editing[0] == side:
                out.append((f"{name:<4}lvl [{self.editing[1]}%]", ("level", side, self.editing[1])))
            else:
                level = ui.shown(("level", self.identity, side), info.get("level"), now)
                out.append((f"{name:<4}lvl {'--' if level is None else str(level) + '%'}", ("level", side, level)))
        return out

    def handle(self, event, ui, status, now):
        if self.editing and event in ("cw", "ccw", "confirm", "push", "back"):
            side, level = self.editing
            if event in ("cw", "ccw"):
                step = LEVEL_STEP if event == "cw" else -LEVEL_STEP
                self.editing = (side, min(max(level + step, 0), 100))
            elif event == "back":
                self.editing = None
            else:
                self.editing = None
                ui.overlay[("level", self.identity, side)] = (level, now + OPTIMISM_S)
                return [f"volume {self.identity} {side} {level}"]
            return []
        return super().handle(event, ui, status, now)

    def select(self, ui, payload, status, now):
        kind, side, value = payload
        if kind == "level":
            self.editing = (side, LEVEL_DEFAULT if value is None else value)
            return []
        ui.overlay[("mute", self.identity, side)] = (not value, now + OPTIMISM_S)
        return [f"mute {self.identity} {side} {'off' if value else 'on'}"]


class UI:
    def __init__(self, prefs=None):
        self.stack = [Home()]
        self.prefs = {**PREFS, **(prefs or {})}   # the Settings screen's values, kept up to date by the service
        self.message = ""     # one line shown at the bottom until the next event
        self.overlay = {}     # key -> (value, deadline): a change shown as made until the status shows it

    @property
    def screen(self):
        return self.stack[-1]

    def shown(self, key, actual, now):
        """What to show for a value: the one just set until the status agrees or OPTIMISM_S passes."""
        if key in self.overlay:
            value, deadline = self.overlay[key]
            if actual == value or now >= deadline:
                del self.overlay[key]
            else:
                return value
        return actual

    def handle(self, event, status, now=0.0):
        """Takes one event; returns the commands to run, in order."""
        self.message = ""
        if event not in EVENTS:
            raise ValueError(f"unknown event {event}")
        return self.screen.handle(event, self, status, now) or []

    def render(self, status, now=0.0):
        """ROWS rows for the display."""
        rows = self.screen.rows(self, status, now)
        rows += [Row(fit(""))] * (ROWS - len(rows))
        if self.message:
            rows[-1] = Row(fit(self.message), True)
        return rows[:ROWS]


def plain(rows):
    """The rows as lines of text, for tests and the terminal simulator."""
    return [row.text for row in rows]
