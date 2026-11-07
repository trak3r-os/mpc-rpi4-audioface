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
import math
import health
from dataclasses import dataclass, replace

COLS, ROWS = 21, 8   # 6x8-pixel cells on a 128x64 display (bridge/rpi-audio-ui/font5x7.py)
BODY = ROWS - 2            # title and persistent connection bar leave six content rows
LEVEL_STEP = 5             # percent per encoder click
LEVEL_DEFAULT = 80         # where an edit starts when the device has no stored level
OPTIMISM_S = 4.0           # how long a change is shown as made while the status has not caught up
SIDES = (("in", "In"), ("out", "Out"))   # a device's capture (what it sends) and playback (what it gets)
EVENTS = ("cw", "ccw", "push", "confirm", "back")

# The Settings screen: each row cycles through these on CONFIRM. A choice is a `ui KEY VALUE` command, which the
# display service applies itself (uiservice.App.set_pref) instead of sending it to rpi-audiod.
SLEEP_STEPS = (0, 15, 30, 60, 120, 300, 600)       # seconds without input before the display goes dark; 0 never
SAVER_STEPS = (0, 10, 20, 30, 60, 120, 300)        # ... before the screensaver; 0 off
SAVER_STYLES = ("bounce", "clock", "status")
CONTRAST_STEPS = (0x1A, 0x40, 0x7F, 0xBF, 0xFF)    # the panel's contrast register: 10, 25, 50, 75 and 100 %
SAVER_STEP_S = 3.0                                  # the screensaver's picture moves one cell this often
PREFS = {"idle_s": 60, "saver_s": 30, "saver_style": "bounce", "contrast": 0x7F, "flip": False,
         "invert_encoder": False}


@dataclass(frozen=True)
class Row:
    text: str
    inverse: bool = False
    selected: bool = False
    icon: str = ""
    scroll: tuple = ()
    footer: tuple = ()
    meter: tuple = ()
    label: str = ""       # full, untruncated name for the graphical renderer
    badge: str = ""       # separate right-aligned state
    tick: int = 0         # quantised marquee time; zero keeps the initial view
    large: str = ""       # double-size value, occupying this row and the next
    peak: int = -1


def fit(text, width=COLS):
    return text[:width].ljust(width)


def device_label(dev):
    return dev.get("name") or dev.get("card") or dev.get("identity", "?")


def inventory(status, hardware):
    """Merge physical cards with routing state; MIDI ports belong to their physical device, not extra devices."""
    devices = [{**d} for d in hardware.get("devices", [])]
    for dev in devices:
        name = hardware.get("assignments", {}).get("names", {}).get(dev["identity"], {}).get("name")
        if name:
            dev["name"] = name
    for source in status.get("devices", []):
        if source.get("virtual"):
            continue
        target = next((d for d in devices if d.get("identity") == source.get("identity")
                       or (d.get("card") and d.get("card") == source.get("card"))), None)
        if target is None:
            target = {}
            devices.append(target)
        target.update(source)
    for port in status.get("midi_ports", []):
        target = next((d for d in devices if d.get("identity") == port["identity"]), None)
        if target is None:
            if "devices" in hardware:
                # The physical scan already includes MIDI-only cards, whose routing identity
                # may not be available in the status. Do not count their ports a second time.
                continue
            target = {"identity": port["identity"], "name": port.get("name", port["identity"])}
            devices.append(target)
        target["midi"] = True
    for endpoint in (status.get("midi") or {}).get("endpoints", []):
        identity = endpoint["endpoint"].rsplit("/", 1)[0]
        target = next((d for d in devices if d.get("identity") == identity), None)
        if target is not None:
            target["midi"] = True
    return devices


def device_mode(dev):
    if dev.get("local"):
        return "Local DAC"
    audio = "in" in dev or "out" in dev
    if audio and dev.get("midi"):
        return "Audio + MIDI"
    if "in" in dev and "out" in dev:
        return "Full duplex"
    if "in" in dev:
        return "Capture only"
    if "out" in dev:
        return "Playback only"
    return "MIDI only" if dev.get("midi") else "Unknown"


def bridge_state(status, hardware):
    """USB enumeration alone does not mean the audio bridge is running."""
    if status.get("standalone"):
        return "LOC"
    state = hardware.get("usb_state", "unknown")
    if state == "unknown":
        connected = (status.get("midi") or {}).get("host_connected")
        state = "configured" if connected else "unknown" if connected is None else "not attached"
    if state == "suspended":
        return "SUSP"
    if state == "not attached":
        return "OFF"
    if state != "configured":
        return "?" if state == "unknown" else "WAIT"
    if not (status.get("host_playback_rate") or status.get("host_capture_rate")):
        return "IDLE"
    if status.get("feeder") == "silence":
        return "SIL"
    return "LIVE" if status.get("jack_ready") and status.get("feeder") == "jack" else "WAIT"


def wifi_label(hardware):
    wifi = hardware.get("wifi", {})
    state = wifi.get("state", "unknown")
    if state == "up":
        return f"{wifi['signal']}%" if wifi.get("signal") is not None else "ON"
    return {"off": "OFF", "down": "--", "missing": "N/A"}.get(state, "?")


def footer(status, hardware):
    count = len(inventory(status, hardware))
    values = (wifi_label(hardware), str(min(count, 99)), bridge_state(status, hardware))
    return Row(fit(f"W:{values[0]} D:{values[1]} USB:{values[2]}"), footer=values)


def meter_row(label, amplitude):
    if amplitude is None or not math.isfinite(amplitude) or amplitude < 0:
        return Row(fit(f"{label}  --"), meter=(label, -1, "--", False))
    db = max(-60, round(20 * math.log10(max(amplitude, 0.001))))
    segments = min(18, max(0, round((db + 60) * 18 / 60))) if amplitude else 0
    clipped = amplitude >= 1 or getattr(amplitude, 'clipped', False)
    value = "CLIP" if clipped else "-inf" if not amplitude else str(db)
    peak = getattr(amplitude, 'peak', None)
    marker = min(18, max(0, round((60 + 20 * math.log10(max(peak, .001))) * 18 / 60))) if peak else -1
    return Row(fit(f"{label} {value} dBFS"), meter=(label, segments, value, clipped), peak=marker)


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
    icon = "list"
    headless = False    # True: no title row, the list uses the top row too

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

    def badge(self, ui, status, payload):
        return ""

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
        visible = BODY + self.headless - (1 if ui.message or ui.notice else 2 if ui.notification else 0)
        self.cursor = min(self.cursor, max(len(items) - 1, 0))
        self.top = min(max(self.top, self.cursor - visible + 1), self.cursor)
        scroll = (self.top, len(items), visible) if len(items) > visible else ()
        title = self.heading(ui, status)
        out = [] if self.headless else [Row(fit(title), True, icon=self.icon, scroll=scroll, label=title)]
        if not items:
            out.append(Row(fit(" (nothing here)")))
        for n, (text, payload) in list(enumerate(items))[self.top:self.top + visible]:
            selected = n == self.cursor
            icon = getattr(payload, "icon", "") if isinstance(self, Home) else ""
            badge = self.badge(ui, status, payload)
            width = COLS - 1 - (len(badge) + 1 if badge else 0)
            line = text[:width].ljust(width) + (" " + badge if badge else "")
            out.append(Row(fit((">" if selected else " ") + line), inverse=selected, selected=selected,
                           icon=icon, label=text, badge=badge))
        return out


class Home(Menu):
    title = "rpi-audio"
    icon = "home"
    headless = True     # no title row: the list starts on the top row, one more item in view

    def items(self, ui, status, now):
        return [("Send audio", SendAudio), ("Outputs", Outputs), ("Levels & mute", Devices),
                ("MIDI", MidiSources), ("Scenes", Presets), ("Connections", Connections), ("Status", Status),
                ("Settings", Settings), ("Power", Power)]

    def select(self, ui, payload, status, now):
        ui.stack.append(payload())
        return []


class Status(Menu):
    title = 'Status'
    icon = 'info'

    def items(self, ui, status, now):
        return [('Machine & buffers', MachineInfo), ('All inputs', lambda: IOStatus('in')),
                ('All outputs', lambda: IOStatus('out')), ('Profile readiness', ProfileReadiness),
                ('Session counters', SessionInfo), ('Recent events', RecentEvents),
                (f'WiFi [{wifi_label(ui.hardware)}]', WifiInfo)]

    def select(self, ui, payload, status, now):
        ui.stack.append(payload())
        return []


class IOStatus(Menu):
    icon = 'info'

    def __init__(self, side):
        super().__init__()
        self.side = side
        self.title = 'Inputs status' if side == 'in' else 'Outputs status'

    def items(self, ui, status, now):
        return [(e['name'], e) for e in health.endpoints(status, ui.hardware) if e['side'] == self.side]

    def select(self, ui, payload, status, now):
        ui.stack.append(EndpointStatus(payload['key']))
        return []

    def rows(self, ui, status, now):
        items = self.items(ui, status, now)
        visible = 2 if ui.message or ui.notice or ui.notification else 3
        self.cursor = min(self.cursor, max(0, len(items) - 1))
        self.top = min(max(self.top, self.cursor - visible + 1), self.cursor)
        rows = [Row(fit(self.title), True, icon=self.icon,
                    scroll=(self.top, len(items), visible) if len(items) > visible else ())]
        for n, (name, endpoint) in list(enumerate(items))[self.top:self.top + visible]:
            selected = n == self.cursor
            state = 'mute' if endpoint.get('muted') else 'on' if endpoint.get('running') else 'wait'
            rows.append(Row(fit(f"{'>' if selected else ' '}{name}"), selected, selected,
                            label=name, badge=state))
            rows.append(meter_row(self.side.upper(), ui.levels.get(endpoint['meter'])))
        if not items:
            rows.append(Row(fit(' No audio endpoints')))
        return rows


class Overview:
    title = "Overview"
    icon = "home"

    def handle(self, event, ui, status, now):
        if event in ("cw", "ccw", "push", "confirm"):
            if len(ui.stack) > 1 and isinstance(ui.stack[-2], Home):
                ui.stack.pop()
            else:
                ui.stack.append(Home())
        elif event == "back" and len(ui.stack) > 1:
            ui.stack.pop()
        return []

    def rows(self, ui, status, now):
        alone = status.get("standalone") or status.get("hub")
        mode = "Audio hub" if status.get("hub") else "Standalone" if alone else "USB bridge" if status else "No service"
        rate = alone.get("rate", 0) if alone else max(status.get("host_playback_rate", 0),
                                                      status.get("host_capture_rate", 0))
        devices = len(inventory(status, ui.hardware))
        audio = sum(not r.get("waiting") for r in status.get("routes", []))
        midi = sum(not r.get("waiting") for r in status.get("midi_routes", []))
        # Host mode has implicit gadget routes in addition to the stored device-to-device routes.
        if not alone:
            audio += sum(bool(d.get(side, {}).get("running")) and not d.get(side, {}).get("muted", False)
                         and d.get(side, {}).get("start") is not None
                         for d in status.get("devices", []) for side, _ in SIDES)
            if (status.get("midi") or {}).get("host_connected"):
                midi += sum(e.get("port") is not None for e in (status.get("midi") or {}).get("endpoints", []))
        rate_text = f"{rate / 1000:g}k" if rate else "No stream"
        device_text = f"{devices} device" + ("s" if devices != 1 else "")
        scene = status.get('active_scene')
        context = ('Scene: ' + ('*' if scene.get('modified') else '') + scene['name']) if scene else \
                  ('Profile: ' + (status.get('host_profile_selection') or status.get('host_profile') or 'default'))
        return [Row(fit(self.title), True, icon=self.icon),
                Row(fit(mode)),
                Row(fit(f"{rate_text} / {device_text}")),
                Row(fit(f"Routes {audio}   MIDI {midi}")),
                meter_row("IN", ui.levels.get("in")), meter_row("OUT", ui.levels.get("out")),
                Row(fit(context), label=context)]


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
    icon = "settings"

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


class Power(Menu):
    title = "Power"
    icon = "power"

    def items(self, ui, status, now):
        return [("Shut down", "poweroff"), ("Restart", "reboot")]

    def select(self, ui, action, status, now):
        ui.stack.append(PowerConfirm(action))
        return []


class PowerConfirm(Menu):
    icon = "power"

    def __init__(self, action):
        super().__init__()
        self.action = action
        self.title = "Shut down?" if action == "poweroff" else "Restart?"

    def items(self, ui, status, now):
        return [("Cancel", False), ("Shut down" if self.action == "poweroff" else "Restart", True)]

    def rows(self, ui, status, now):
        return super().rows(ui, status, now) + [Row(fit('')), Row(fit('Audio will stop.'))]

    def select(self, ui, confirmed, status, now):
        if not confirmed:
            ui.stack.pop()
            return []
        ui.stack.append(PowerWait(self.action))
        ui.message = 'Shutting down...' if self.action == 'poweroff' else 'Restarting...'
        return [f'system {self.action}']


class PowerWait:
    def __init__(self, action):
        self.action = action
        self.title = 'Shutting down...' if action == 'poweroff' else 'Restarting...'

    def handle(self, event, ui, status, now):
        # Once submitted, repeated turns/presses must not queue another system action.
        if event == 'back' and ui.message_kind == 'error':
            ui.stack.pop()
            ui.message = ''
        return []

    def rows(self, ui, status, now):
        lines = ('Wait for shutdown.', 'Before unplugging:', 'wait for Pi activity', 'LED to stop.') if \
                self.action == 'poweroff' else ('Please wait.', 'Keep power connected.', 'Audio will reconnect.')
        if ui.message_kind == 'error':
            lines = ('Request failed.', 'BACK to return.')
        return [Row(fit(self.title), icon='power'), Row(fit(''))] + [Row(fit(line)) for line in lines]


def tri(n, size):
    """A triangle wave: 0, 1... size, size-1... 0, repeating: a position that bounces between 0 and `size`."""
    n %= 2 * size or 1
    return n if n <= size else 2 * size - n


def saver_rows(style, now, wall=None, status=None, hardware=None, levels=None):
    """The screensaver: ROWS blank rows with a word that drifts a cell every SAVER_STEP_S, so no pixel stays lit
    (an OLED burns in). "bounce" is the name, "clock" the time (`wall`, a time.struct_time)."""
    if style == 'status':
        status, hardware, levels = status or {}, hardware or {}, levels or {}
        lines = health.machine_lines(status, hardware, levels)
        page = int(now // 6) % 3
        selected = ([f"rpi-audio {status.get('engine_mode', '?')}", lines[2], lines[3], lines[4], lines[12]],
                    [lines[1], lines[5], lines[6], lines[8], lines[9]],
                    [lines[10], lines[11], f"Inputs: {sum(e['side'] == 'in' for e in health.endpoints(status))}",
                     f"Outputs: {sum(e['side'] == 'out' for e in health.endpoints(status))}", lines[14]])[page]
        step = int(now // SAVER_STEP_S)
        x, y = tri(step, 1), tri(step // 2, 3)
        rows = [Row(fit('')) for _ in range(ROWS)]
        for n, line in enumerate(selected):
            rows[y + n] = Row(fit(' ' * x + line[:20]))
        return rows
    text = time.strftime("%H:%M", wall or time.localtime()) if style == "clock" else "rpi-audio"
    step = int(now // SAVER_STEP_S)
    x, y = tri(step, COLS - len(text)), tri(step, ROWS - 1)
    rows = [Row(fit(""))] * ROWS
    rows[y] = Row(fit(" " * x + text))
    return rows


class Presets(Menu):
    """Eight scenes with explicit, consistent load/save actions."""
    title = "Scenes"
    icon = "preset"

    def items(self, ui, status, now):
        saved = {p["slot"]: p.get("name", "") for p in status.get("presets", [])}
        return [(f"{n} {saved[n] or 'Preset ' + str(n)}" if n in saved else f"{n} -empty-", n) for n in range(1, 9)]

    def select(self, ui, slot, status, now):
        ui.stack.append(SceneActions(slot))
        return []

    def badge(self, ui, status, payload):
        scene = status.get('active_scene') or {}
        return ('*edit' if scene.get('modified') else 'live') if scene.get('slot') == payload else ''

    def press(self, ui, slot, status, now):
        return self.select(ui, slot, status, now)


class SceneActions(Menu):
    icon = "preset"

    def __init__(self, slot):
        super().__init__()
        self.slot = slot
        self.title = f"Scene {slot}"

    def items(self, ui, status, now):
        return [("Load", "load"), ("Save here...", "save")]

    def select(self, ui, action, status, now):
        slot = self.slot
        if action == "save":
            ui.stack.append(Confirm("Save scene?", f"Replace slot {slot}?", [f"preset save {slot}"], f"saved {slot}"))
        elif not any(p["slot"] == slot for p in status.get("presets", [])):
            ui.message = f"{slot} is empty"
        else:
            ui.message = f"loaded {slot}"
            return [f"preset load {slot}"]
        return []


class Confirm:
    """A yes/no question: CONFIRM runs the commands, BACK drops it."""

    def __init__(self, title, text, commands, done):
        self.title, self.text, self.commands, self.done = title, text, commands, done

    def handle(self, event, ui, status, now):
        if event == "back":
            ui.stack.pop()
        elif event in ("confirm", "push"):
            ui.stack.pop()
            ui.message = self.done
            return list(self.commands)
        return []

    def rows(self, ui, status, now):
        return [Row(fit(self.title), True), Row(fit("")), Row(fit(" " + self.text)), Row(fit("")),
                Row(fit(" Press = confirm")), Row(fit(" BACK  = cancel"))]


class SendAudio(Menu):
    title = "Send audio from..."
    icon = "route"

    def items(self, ui, status, now):
        return [(pair_label(dev, "in", pair), (dev["identity"], pair)) for dev, pair in endpoints(status, "in")]

    def select(self, ui, source, status, now):
        ui.stack.append(SendTargets(*source))
        return []


class SendTargets(Menu):
    title = "Send to..."
    icon = "route"

    def __init__(self, src, src_pair):
        super().__init__()
        self.src, self.src_pair = src, src_pair

    def items(self, ui, status, now):
        routes = stored_routes(status)
        source = next((d for d in status.get("devices", []) if d["identity"] == self.src), {})
        rows = []
        for dev in status.get("devices", []):
            if "out" not in dev or dev["identity"] == self.src:
                continue
            matches = [key for key in routes if key[0] == self.src and key[1] == dev["identity"]
                       and key[2] == self.src_pair]
            default_pair = 1
            start = source.get("in", {}).get("start")
            if dev["identity"] == "usb-host" and start:
                default_pair = (start + 1) // 2 + self.src_pair - 1
            on = ui.shown(("send", self.src, self.src_pair, dev["identity"]), bool(matches), now)
            waiting = on and matches and any(routes[key] for key in matches)
            mark = "[~]" if waiting else "[x]" if on else "[ ]"
            rows.append((f"{mark} {device_label(dev)}", (dev["identity"], default_pair, on)))
        rows.append(("More output pairs...", None))
        return rows

    def select(self, ui, target, status, now):
        if target is None:
            ui.stack.append(OutputPairs(self.src, self.src_pair))
            return []
        dst, pair, on = target
        ui.overlay[("send", self.src, self.src_pair, dst)] = (not on, now + OPTIMISM_S)
        verb = "unroute" if on else "route"
        suffix = "" if on else f" dst={pair}"
        return [f"{verb} {self.src} {dst} src={self.src_pair}{suffix}"]


class OutputPairs(Menu):
    title = "Output pairs"
    icon = "route"

    def __init__(self, src, src_pair):
        super().__init__()
        self.src, self.src_pair = src, src_pair

    def items(self, ui, status, now):
        routes = stored_routes(status)
        rows = []
        for dev, pair in endpoints(status, "out"):
            if dev["identity"] == self.src:
                continue
            key = route_key(self.src, dev["identity"], self.src_pair, pair)
            on = ui.shown(("route",) + key, key in routes, now)
            mark = "[~] " if on and routes.get(key) else "[x] " if on else "[ ] "
            rows.append((mark + pair_label(dev, "out", pair), (key, on)))
        return rows

    def select(self, ui, payload, status, now):
        key, on = payload
        ui.overlay[("route",) + key] = (not on, now + OPTIMISM_S)
        src, dst, src_pair, dst_pair = key
        return [f"{'unroute' if on else 'route'} {src} {dst} src={src_pair} dst={dst_pair}"]


SAVE_HOST = object()  # the HostProfiles row that saves the current reservation as a new profile
HOST_ROW = object()   # the Outputs row that opens HostProfiles; the others carry an output identity


class Outputs(Menu):
    title = "Outputs"
    icon = "device"

    def items(self, ui, status, now):
        rows = [(o['name'], o['identity']) for o in status.get('outputs', [])]
        rows.append((f"Audio mode: {status.get('engine_mode', 'host')}", None))
        if status.get("host_profiles"):
            rows.append((f"Host: {status.get('host_profile') or 'default'}", HOST_ROW))
        return rows

    def badge(self, ui, status, payload):
        output = next((o for o in status.get('outputs', []) if o['identity'] == payload), {})
        return {'disabled': 'off', 'waiting': 'wait', 'sending': 'send', 'active': 'on',
                'error': 'err'}.get(output.get('state'), '')

    def select(self, ui, identity, status, now):
        ui.stack.append(EngineModes() if identity is None else HostProfiles() if identity is HOST_ROW
                        else OutputActions(identity))
        return []


class OutputActions(Menu):
    icon = "device"

    def __init__(self, identity):
        super().__init__()
        self.identity = identity

    def output(self, status):
        return next((o for o in status.get("outputs", []) if o["identity"] == self.identity), {})

    def heading(self, ui, status):
        return self.output(status).get("name", "Output")

    def items(self, ui, status, now):
        enabled = ui.shown(("output", self.identity), self.output(status).get("enabled", False), now)
        level = ui.shown(('output_level', self.identity), self.output(status).get('level', 100), now)
        return [(f"Enabled: {'on' if enabled else 'off'}", ('enable', enabled)),
                (f'Level: {level}%', ('level', level)), ('Details', ('details', None))]

    def select(self, ui, payload, status, now):
        action, enabled = payload
        if action == 'level':
            ui.stack.append(OutputLevel(self.identity, enabled))
            return []
        if action == "details":
            ui.stack.append(OutputInfo(self.identity))
            return []
        ui.overlay[("output", self.identity)] = (not enabled, now + OPTIMISM_S)
        return [f"output {self.identity} {'off' if enabled else 'on'}"]


class OutputLevel:
    title = 'Output level'

    def __init__(self, identity, value):
        self.identity, self.value = identity, value

    def handle(self, event, ui, status, now):
        if event in ('cw', 'ccw'):
            self.value = min(100, max(0, self.value + (LEVEL_STEP if event == 'cw' else -LEVEL_STEP)))
        elif event == 'back':
            ui.stack.pop()
        elif event in ('confirm', 'push'):
            ui.stack.pop()
            ui.overlay[('output_level', self.identity)] = (self.value, now + OPTIMISM_S)
            ui.message = 'Output level saved'
            return [f'output {self.identity} level {self.value}']
        return []

    def rows(self, ui, status, now):
        name = next((o['name'] for o in status.get('outputs', []) if o['identity'] == self.identity), 'Output')
        return [Row(fit('Edit output level'), True, icon='edit'), Row(fit(name), True, label=name, selected=True),
                Row(fit(f'Level: {self.value}%'), large=f'{self.value}%'), Row(fit('')),
                Row(fit(''), meter=('OUT', round(self.value * 18 / 100), f'{self.value}%', False)),
                Row(fit('Turn: adjust')),
                Row(fit('Press: save BACK:exit'))]


def next_host_name(status):
    taken, n = set(status.get('host_profiles', [])), 1
    while f'host-{n}' in taken:
        n += 1
    return f'host-{n}'


def host_kind(status, name):
    return status.get('host_profile_details', {}).get(name, {})


class HostProfiles(Menu):
    title = 'Host profiles'
    icon = 'settings'

    def items(self, ui, status, now):
        rows = []
        for name in ['default', *status.get('host_profiles', [])]:
            rows.append((name, name))
        return rows + [('Save current as...', SAVE_HOST)]

    def badge(self, ui, status, payload):
        if payload is SAVE_HOST:
            return ''
        current = status.get('host_profile_selection', status.get('host_profile')) or 'default'
        kind = host_kind(status, payload)
        mark = 'S' if kind.get('kind') == 'snapshot' else str(kind['preset']) if 'preset' in kind else 'R'
        state = kind.get('readiness', {}).get('state')
        availability = '!' if state == 'error' else '~' if state == 'partial' else ''
        return mark + ('*' if payload == current else '') + availability

    def select(self, ui, name, status, now):
        ui.stack.append(HostSaveAs() if name is SAVE_HOST else HostActions(name))
        return []


class HostSaveAs(Menu):
    title = 'Save current as...'
    icon = 'preset'

    def items(self, ui, status, now):
        return [('Reservations only', False), ('Full setup + names', True)]

    def select(self, ui, full, status, now):
        name = next_host_name(status)
        ui.stack.pop()
        ui.message = f'Saved {name}'
        return [f"host save {name} new" + (' full' if full else '')]


class HostActions(Menu):
    icon = 'settings'

    def __init__(self, name):
        super().__init__()
        self.name = name

    def heading(self, ui, status):
        return self.name

    def items(self, ui, status, now):
        rows = [('Use this profile', 'use'), ('Details', 'details')]
        if self.name != 'default':
            rows.append(('Attach a scene...', 'scene'))
        if host_kind(status, self.name).get('origin') == 'user':
            rows += [('Update from current', 'overwrite'), ('Delete profile...', 'delete')]
        return rows

    def select(self, ui, action, status, now):
        name, info = self.name, host_kind(status, self.name)
        if action == 'details':
            ui.stack.append(HostInfo(name))
        elif action == 'scene':
            ui.stack.append(HostScenes(name))
        elif action == 'overwrite':
            ui.stack.append(HostOverwrite(name))
        elif action == 'delete':
            ui.stack.append(Confirm('Delete profile?', name, [f'host delete {name}'], 'Profile deleted'))
        else:
            if info.get('kind') == 'preset' and not info.get('preset_available', True):
                ui.message = 'Linked scene is empty'
                return []
            text = 'Replace audio setup' if info.get('kind') in ('preset', 'snapshot') else 'Channels may move'
            ui.stack.append(Confirm('Use host profile?', text, [f'host {name}'], 'Profile loaded'))
        return []


class HostOverwrite(HostSaveAs):
    title = 'Update profile'

    def __init__(self, name):
        super().__init__()
        self.name = name

    def select(self, ui, full, status, now):
        text = 'Full setup + names' if full else 'Reservations only'
        ui.stack.append(Confirm('Overwrite profile?', text,
                                [f'host save {self.name}' + (' full' if full else '')], 'Profile saved'))
        return []


class HostScenes(Menu):
    title = 'Attach a scene'
    icon = 'preset'

    def __init__(self, name):
        super().__init__()
        self.name = name

    def items(self, ui, status, now):
        return [('Reservations only', None), *[(f"Scene {p['slot']}: {p.get('name', '')}", p['slot'])
                                               for p in status.get('presets', [])]]

    def select(self, ui, slot, status, now):
        ui.stack.append(Confirm('Replace saved setup?', f'Scene {slot}' if slot else 'Reservations only',
                                [f"host preset {self.name} {slot or 'none'}"], 'Profile link saved'))
        return []


class EngineModes(Menu):
    title = "Audio mode"
    icon = "settings"

    def items(self, ui, status, now):
        return [("Hub: DAC + USB + net", "hub"), ("USB host clock", "host"), ("Standalone DAC", "standalone")]

    def select(self, ui, mode, status, now):
        if mode != status.get("engine_mode", "host"):
            ui.stack.append(Confirm("Restart audio?", "Audio will pause", [f"engine {mode}"], "Switching audio..."))
        return []


class MidiSources(Menu):
    title = "MIDI from..."
    icon = "midi"

    def items(self, ui, status, now):
        return midi_ends(status, "in")

    def select(self, ui, source, status, now):
        ui.stack.append(MidiTargets(source))
        return []


class MidiTargets(Menu):
    title = "MIDI to..."
    icon = "midi"

    def __init__(self, source):
        super().__init__()
        self.source = source

    def items(self, ui, status, now):
        stored = stored_midi_routes(status)
        rows = []
        for name, dst in midi_ends(status, "out"):
            if dst.rpartition("/")[0] == self.source.rpartition("/")[0]:
                continue
            on = ui.shown(("midi", self.source, dst), (self.source, dst) in stored, now)
            waiting = on and stored.get((self.source, dst)) is not None
            rows.append((("[~] " if waiting else "[x] " if on else "[ ] ") + name, (dst, on)))
        return rows

    def select(self, ui, payload, status, now):
        dst, on = payload
        ui.overlay[("midi", self.source, dst)] = (not on, now + OPTIMISM_S)
        return [f"{'midiunroute' if on else 'midiroute'} {self.source} {dst}"]


class Devices(Menu):
    title = "Levels & mute"
    icon = "device"

    def items(self, ui, status, now):
        out = []
        for dev in status.get("devices", []):
            if dev.get("virtual"):
                continue
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

    def rows(self, ui, status, now):
        rows = super().rows(ui, status, now)
        if self.editing:
            rows[0] = replace(rows[0], icon='edit')
            rows.append(Row(fit('Press:save BACK:undo')))
        return rows

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


class Connections(Menu):
    """The USB host, wireless network and every physical audio/MIDI device, even while audio is idle."""
    title = "Connections"
    icon = "info"

    def items(self, ui, status, now):
        rows = [(f"USB host [{bridge_state(status, ui.hardware)}]", USBInfo),
                (f"WiFi [{wifi_label(ui.hardware)}]", WifiInfo)]
        for dev in inventory(status, ui.hardware):
            mode = {"Local DAC": "LOC", "Audio + MIDI": "A+M", "Full duplex": "I/O",
                    "Capture only": "IN", "Playback only": "OUT", "MIDI only": "MID", "Unknown": "?"}[device_mode(dev)]
            rows.append((f"{mode} {device_label(dev)}", dev.get("card") or dev["identity"]))
        return rows

    def select(self, ui, payload, status, now):
        ui.stack.append(payload() if isinstance(payload, type) else DeviceInfo(payload))
        return []


class Info(Menu):
    """Read-only details; the encoder scrolls and BACK returns without changing the audio."""
    icon = "info"

    def details(self, ui, status):
        return []

    def items(self, ui, status, now):
        return [(text, None) for text in self.details(ui, status)]


class USBInfo(Info):
    title = "USB bridge"
    icon = "usb"

    def details(self, ui, status):
        label = bridge_state(status, ui.hardware)
        states = {"OFF": "Disconnected", "IDLE": "Connected / idle", "LIVE": "Audio bridge active",
                  "WAIT": "Waiting for audio", "SIL": "Sending silence", "SUSP": "Host suspended",
                  "LOC": "Standalone mode", "?": "Unknown"}
        mode = "Audio hub" if status.get("hub") else "Standalone" if status.get("standalone") else \
               "USB bridge" if status else "Unknown"
        rate = max(status.get("host_capture_rate", 0), status.get("host_playback_rate", 0))
        return [f"Mode: {mode}", states[label], f"Link: {ui.hardware.get('usb_state', 'unknown')}",
                f"Audio: {rate / 1000:g} kHz" if rate else "Audio: no stream",
                f"Channels: {status.get('gadget_channels', '?')} x {status.get('gadget_channels', '?')}",
                f"Engine: {'ready' if status.get('jack_ready') else 'idle'}"]


class OutputInfo(Info):
    icon = "device"

    def __init__(self, identity):
        super().__init__()
        self.identity = identity

    def output(self, status):
        return next((o for o in status.get("outputs", []) if o["identity"] == self.identity), {})

    def heading(self, ui, status):
        return self.output(status).get("name", "Output details")

    def details(self, ui, status):
        output = self.output(status)
        detail = output.get("detail", "")
        rows = [f"State: {output.get('state', 'unknown')}", output.get("protocol", ""),
                f"Channels: {output.get('channels', '?')}", f"Level: {output.get('level', 100)}%"]
        if output.get("address"):
            rows.append(f"{output['address']}:{output['port']}")
        rows += [detail[n:n + 20] for n in range(0, len(detail), 20)]
        if output.get("sdp"):
            rows += ["Receiver: open SDP", "network-rtp.sdp"]
            if output.get("http_port"):
                ip = ui.hardware.get("wifi", {}).get("ip") or "Pi-IP"
                rows += ["SDP download:", f"http://{ip}:", str(output["http_port"]), "/network-rtp.sdp"]
            if output.get("http_error"):
                rows += ["SDP HTTP error", output["http_error"]]
        metrics = output.get("metrics", {})
        if output.get("protocol") == "Link Audio":
            rows += [f"Peers: {metrics.get('peers', 0)}", "Live: Link Audio IN", "Select Network mix"]
        if metrics:
            rows += [f"XRuns: {metrics.get('xruns', 0)}", f"Dropped: {metrics.get('dropped_frames', 0)}"]
        return rows


class HostInfo(Info):
    icon = 'settings'

    def __init__(self, name):
        super().__init__()
        self.name = name

    def heading(self, ui, status):
        return self.name

    def details(self, ui, status):
        info = host_kind(status, self.name)
        kind = info.get('kind', 'reservations')
        rows = [{'factory': 'Factory profile', 'user': 'Your saved profile',
                 'configuration': 'Installation default'}.get(info.get('origin'), 'Host profile'),
                {'snapshot': 'Full setup + names', 'preset': f"Linked scene {info.get('preset')}",
                 'reservations': 'Reservations only'}[kind]]
        readiness = info.get('readiness')
        if readiness:
            rows += ['State: ' + readiness['state'].title()]
            for issue in readiness.get('issues', []):
                text = issue['message']
                rows += [text[n:n + 20] for n in range(0, len(text), 20)]
        if kind == 'preset' and not info.get('preset_available', True):
            rows.append('Linked scene is empty')
        for side in ('in', 'out'):
            rows.append('Reserved ' + side.upper() + ':')
            channels = ','.join(map(str, info.get('reserve_' + side, []))) or 'none'
            rows += [channels[n:n + 20] for n in range(0, len(channels), 20)]
        rows += ['Use applies the setup', 'Engine mode stays', 'Rename: MIDI or CLI']
        return rows


class ProfileReadiness(Info):
    title = 'Profile readiness'
    icon = 'info'

    def details(self, ui, status):
        info = status.get('profile_readiness')
        if not info:
            return ['No profile status']
        rows = [status.get('host_profile_selection') or 'default', 'State: ' + info['state'].title()]
        for issue in info.get('issues', []):
            text = issue['message']
            rows += [text[n:n + 20] for n in range(0, len(text), 20)]
        if not info.get('issues'):
            rows.append('Requirements present')
        rows.append('Saved profile checked')
        rows.append('Not a sound test')
        return rows


class SessionInfo(Info):
    title = 'Session counters'
    icon = 'info'

    def details(self, ui, status):
        session = status.get('session', {})
        if not session.get('started'):
            return ['No session data']
        counts = session.get('counters', {})
        labels = [('XRuns', 'xruns'), ('Engine faults', 'engine_faults'), ('Bridge faults', 'bridge_failures'),
                  ('USB unplug', 'usb_disconnects'), ('Devices lost', 'device_disconnects'),
                  ('TX dropped frames', 'network_dropped_frames'), ('Rate changes', 'rate_changes'),
                  ('Buffer changes', 'buffer_changes'), ('Adapter faults', 'adapter_failures'),
                  ('Link send stops', 'network_stops'), ('USB budget blocks', 'bandwidth_blocks')]
        rows = ['Observer: ' + ('active' if session.get('monitor_available') else 'waiting'),
                'Since:', session['started']]
        rows += [f'{label}: {counts.get(key, 0)}' for label, key in labels]
        rows += ['Retained this boot', 'Reset after reboot']
        return rows


class RecentEvents(Menu):
    title = 'Recent events'
    icon = 'info'

    def items(self, ui, status, now):
        return [(event.get('last_time', event['time'])[-8:] + ' ' + event['detail'], event['id'])
                for event in reversed(status.get('session', {}).get('events', []))]

    def select(self, ui, payload, status, now):
        ui.stack.append(EventInfo(payload))
        return []


class EventInfo(Info):
    title = 'Event details'
    icon = 'info'

    def __init__(self, identity):
        super().__init__()
        self.identity = identity

    def details(self, ui, status):
        event = next((e for e in status.get('session', {}).get('events', []) if e['id'] == self.identity), {})
        if not event:
            return ['Event no longer kept']
        text = event['detail']
        return [event['severity'].title(), event['time'], f"Count: {event['count']}",
                *[text[n:n + 20] for n in range(0, len(text), 20)],
                *(['Last: ' + event['last_time'][-8:]] if event.get('last_time') else [])]


class MachineInfo(Info):
    title = 'Machine & buffers'
    icon = 'info'

    def details(self, ui, status):
        rows = health.machine_lines(status, ui.hardware, ui.levels)
        for output in status.get('outputs', []):
            metrics = output.get('metrics', {})
            rows += [output['name'] + ': ' + output['state']]
            if metrics:
                rows += [f"XRuns: {metrics.get('xruns', '--')}", f"Lost f: {metrics.get('dropped_frames', '--')}"]
        return rows

    def rows(self, ui, status, now):
        rows = super().rows(ui, status, now)
        machine = ui.hardware.get('machine', {})
        for n, row in enumerate(rows):
            for label, key in (('CPU', 'cpu_pct'), ('RAM', 'memory_pct')):
                if row.text.lstrip('> ').startswith(label + ' '):
                    value = machine.get(key)
                    rows[n] = Row(row.text, meter=(label, -1 if value is None else round(value * 18 / 100),
                                                   '--' if value is None else f'{value:.0f}%', False))
        return rows


class EndpointStatus(Info):
    icon = 'info'

    def __init__(self, key):
        super().__init__()
        self.key = key

    def endpoint(self, ui, status):
        return next((e for e in health.endpoints(status, ui.hardware) if e['key'] == self.key), {})

    def heading(self, ui, status):
        return self.endpoint(ui, status).get('name', '(disconnected)')

    def details(self, ui, status):
        endpoint = self.endpoint(ui, status)
        if not endpoint:
            return ['Device disconnected']
        pcm = health.pcm(endpoint, ui.hardware)
        rate = pcm.get('rate', endpoint.get('rate', 0))
        period, buffer = pcm.get('period_size'), pcm.get('buffer_size')
        rows = ['Signal peak', f"Direction: {endpoint['side'].upper()}",
                'State: ' + ('muted' if endpoint.get('muted') else 'running' if endpoint.get('running') else 'waiting'),
                f"Channels: {endpoint.get('channels', '--')}", f"Rate: {rate / 1000:g} kHz" if rate else 'Rate: --',
                f"ALSA: {pcm.get('state', '--')}", f"Period: {period} f" if period else 'Period: --',
                f"Buffer: {buffer} f" if buffer else 'Buffer: --',
                f"Buffer: {buffer * 1000 / rate:.1f} ms" if buffer and rate else 'Buffer: -- ms']
        avail = pcm.get('avail')
        if buffer and avail is not None and 0 <= avail <= buffer:
            fill = avail if endpoint['side'] == 'in' else buffer - avail
            rows += ['Fill ' + health.bar(fill * 100 / buffer)]
        else:
            rows += ['Fill: --']
        rows += [f"Delay: {pcm.get('delay', '--')} f", f"Avail max: {pcm.get('avail_max', '--')} f"]
        if not pcm and endpoint.get('running') and not endpoint.get('card'):
            rows += ['Network / USB client', 'No ALSA buffer read']
        for output in status.get('outputs', []):
            if output['identity'] == endpoint['identity']:
                metrics = output.get('metrics', {})
                if 'queue_frames' in metrics:
                    rows += [f"Queue: {metrics['queue_frames']} f",
                             f"Capacity: {metrics.get('capacity_frames', '--')} f"]
                rows += [f"XRuns: {metrics.get('xruns', '--')}", f"Lost f: {metrics.get('dropped_frames', '--')}",
                         f"Packets: {metrics.get('packets', '--')}", f"Peer count: {metrics.get('peers', '--')}"]
        if endpoint.get('blocked'):
            rows += [endpoint['blocked']]
        return rows

    def rows(self, ui, status, now):
        rows = super().rows(ui, status, now)
        if self.top == 0 and len(rows) > 1:
            endpoint = self.endpoint(ui, status)
            rows[1] = meter_row(endpoint.get('side', '').upper(), ui.levels.get(endpoint.get('meter')))
        return rows


class WifiInfo(Info):
    title = "WiFi"
    icon = "wifi"

    def details(self, ui, status):
        wifi = ui.hardware.get("wifi", {})
        return [f"State: {wifi.get('state', 'unknown')}", wifi.get("name") or "No network",
                wifi.get("ip") or "No IP address", f"Signal: {wifi_label(ui.hardware)}"]


class DeviceInfo(Info):
    icon = "device"

    def __init__(self, identity):
        super().__init__()
        self.identity = identity

    def device(self, ui, status):
        return next((d for d in inventory(status, ui.hardware)
                     if self.identity in (d["identity"], d.get("card"))), {})

    def heading(self, ui, status):
        return device_label(self.device(ui, status)) if self.device(ui, status) else "(disconnected)"

    def details(self, ui, status):
        dev = self.device(ui, status)
        if not dev:
            return ["Device disconnected"]
        sides = [dev[s] for s, _ in SIDES if s in dev]
        blocked = next((s["blocked"] for s in sides if s.get("blocked")), "")
        unassigned = (not (status.get("standalone") or status.get("hub")) and
                      any("start" in s and s["start"] is None for s in sides))
        state = "Waiting" if blocked or unassigned else "Bridged" if any(s.get("running") for s in sides) else "Idle"
        rows = [device_mode(dev), "Bus: I2S / local" if dev.get("local") else "Bus: USB", f"State: {state}"]
        for side, label in SIDES:
            info = dev.get(side, {})
            if not info:
                continue
            rate = f" / {info['rate'] / 1000:g}k" if info.get("rate") else ""
            rows.append(f"{label}: {info.get('channels', 0)} ch{rate}")
        rows.append(f"MIDI: {'yes' if dev.get('midi') else 'no'}")
        if status.get("standalone"):
            rows.append("USB map: standalone")
        elif status.get("hub"):
            for side, label in (("in", "To USB"), ("out", "From USB")):
                pairs = []
                for route in status.get("routes", []):
                    match = (route["src"] == dev["identity"] and route["dst"] == "usb-host") if side == "in" else \
                            (route["src"] == "usb-host" and route["dst"] == dev["identity"])
                    if match:
                        pair = route.get("dst_pair" if side == "in" else "src_pair", 1)
                        pairs.append(f"{pair * 2 - 1}-{pair * 2}" + (" ~" if route.get("waiting") else ""))
                if side in dev:
                    rows.append(label + ": " + (", ".join(pairs) if pairs else "off"))
        else:
            for side, label in SIDES:
                info = dev.get(side, {})
                if not info:
                    continue
                start = info.get("start")
                size = info.get("slots", info.get("channels", 0))
                saved = ui.hardware.get("assignments", {})
                if "start" not in info and dev["identity"] in saved.get(side, {}):
                    start = saved[side][dev["identity"]]
                    size = saved.get(side + "_channels", {}).get(dev["identity"], size)
                    label = label.upper() + " saved"
                else:
                    label = "USB " + label.upper()
                mapped = f"{start}-{start + size - 1}" if start is not None and size else "unassigned"
                rows.append(f"{label}: {mapped}")
        mapped_midi = False
        for endpoint in (status.get("midi") or {}).get("endpoints", []):
            identity, port = endpoint["endpoint"].rsplit("/", 1)
            if identity == dev["identity"]:
                cable = endpoint.get("port")
                rows.append(f"MIDI p{int(port) + 1}: " + (f"cable {cable}" if cable is not None else "unassigned"))
                mapped_midi = True
        if dev.get("midi") and not mapped_midi:
            saved_midi = ui.hardware.get("assignments", {}).get("midi", {})
            for endpoint, cable in saved_midi.items():
                identity, port = endpoint.rsplit("/", 1)
                if identity == dev["identity"] and not status.get("standalone"):
                    rows.append(f"MIDI p{int(port) + 1} saved: {cable}")
                    mapped_midi = True
            if not mapped_midi:
                rows.append("MIDI: local routing" if status.get("standalone") else "MIDI: unassigned")
        if blocked:
            rows += [blocked[n:n + COLS - 1] for n in range(0, len(blocked), COLS - 1)]
            if "budget" in blocked.lower():
                rows += ["USB bandwidth full", "Unplug unused device"]
        elif unassigned:
            rows += ["No free USB channels", "Review channel map"]
        return rows


class UI:
    def __init__(self, prefs=None, overview=False):
        self.stack = [Overview() if overview else Home()]
        self.prefs = {**PREFS, **(prefs or {})}   # the Settings screen's values, kept up to date by the service
        self.message = ""     # one line shown at the bottom until the next event
        self.overlay = {}     # key -> (value, deadline): a change shown as made until the status shows it
        self.hardware, self.notice = {}, ""
        self.levels, self.notification = {}, ()
        self.focus, self.focus_at = None, 0.0
        self.message_kind, self.message_until = 'info', float('inf')

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
        if event not in EVENTS:
            raise ValueError(f"unknown event {event}")
        if isinstance(self.screen, PowerWait):
            return self.screen.handle(event, self, status, now)
        self.message = ""
        self.message_kind, self.message_until = 'info', float('inf')
        self.focus_at = now
        return self.screen.handle(event, self, status, now) or []

    def render(self, status, now=0.0):
        """ROWS rows for the display."""
        if now >= self.message_until:
            self.message, self.message_until = '', float('inf')
        rows = self.screen.rows(self, status, now)
        focus = (id(self.screen), tuple(r.label for r in rows if r.selected))
        if focus != self.focus:
            self.focus, self.focus_at = focus, now
        tick = int(max(0, now - self.focus_at) / 0.35)
        polished = []
        short = {'Profile readiness': 'Profile state', 'Session counters': 'Session', 'Machine & buffers': 'Machine',
                 'Recent events': 'Events', 'Inputs status': 'Inputs', 'Outputs status': 'Outputs'}
        headless = getattr(self.screen, 'headless', False)
        for n, row in enumerate(rows):
            heading = n == 0 and not headless
            if heading:
                # Quiet headings: white text on black.
                row = replace(row, inverse=False)
            if heading and row.icon:
                title = row.label or row.text.rstrip()
                row = replace(row, label=short.get(title, title))
            width = 19 if heading else 18 if row.icon else 20
            if heading and row.scroll:
                top, total, visible = row.scroll
                width = (127 - len(f'{min(top + visible, total)}/{total}') * 6 - 13) // 6
            elif row.badge:
                width = (127 - len(row.badge) * 6 - 14) // 6
            if row.label and len(row.label) > width and (heading or row.selected):
                row = replace(row, tick=tick)
            polished.append(row)
        rows = polished
        rows = rows[:ROWS - 1]
        rows += [Row(fit(""))] * (ROWS - 1 - len(rows))
        if self.message or self.notice:
            icon = {'busy': 'busy', 'success': 'check', 'error': 'error'}.get(self.message_kind, 'info')
            rows[-1] = Row(fit(self.message or self.notice), True, icon=icon if self.message else 'info')
        elif self.notification:
            rows[-2] = Row(fit(self.notification[0]), True)
            rows[-1] = Row(fit(self.notification[1]))
        return rows + [footer(status, self.hardware)]


def plain(rows):
    """The rows as lines of text, for tests and the terminal simulator."""
    return [row.text for row in rows]
