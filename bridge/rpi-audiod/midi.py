# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's MIDI logic (docs/MIDI.md): sequencer clients, cables, subscriptions and the
control cable's SysEx and CC commands. Nothing here touches the system: the service passes
in the outputs of aconnect, /proc/asound/seq/clients and aseqdump. tests/test_midi.py checks it."""

import copy
import json
import re
from dataclasses import dataclass

import midiroute
import presets
import outputs
import routing
from audiod import IN, OUT, allocate

SYSEX_HEAD = bytes((0xF0, 0x7D, 0x52, 0x41))  # non-commercial id 7D, then "RA": a command
REPLY_HEAD = bytes((0xF0, 0x7D, 0x52, 0x42))  # "RB": a reply, never taken for a command when echoed
SYSEX_END = 0xF7
USAGE = {
    "output": "output local-dac|usb-host|network-rtp|network-link on|off | output ID level PERCENT",
    "engine": "engine host|standalone|hub",
    "usb": "usb latency low|normal",
    "host": "host NAME|default | host save NAME [reserve_in=K,K] [reserve_out=K,K] [full|preset=N] [new] "
            "| host preset NAME N|none | host rename OLD NEW | host delete NAME",
    "ping": "ping",
    "status": "status",
    "assign": "assign IDENTITY [in=N] [out=N] [midi=K]",
    "mute": "mute IDENTITY in|out on|off",
    "volume": "volume IDENTITY in|out PERCENT",
    "name": "name IDENTITY [TEXT] | name IDENTITY in|out K [TEXT]",
    "preset": "preset save N [TEXT] | preset load N | preset clear N",
    "route": "route SRC DST [src=P] [dst=P]",
    "unroute": "unroute SRC DST [src=P] [dst=P]",
    "midiroute": "midiroute SRC DST",
    "midiunroute": "midiunroute SRC DST",
}
STATUS_LIMIT = 4000   # bytes the status reply may take (docs/MIDI.md)
# Dropped from the reply, one stage at a time, until it fits: (device keys, direction keys)
STATUS_TRIM = ((("usb",), ("fs_load",)), (("usbbus",), ()), ((), ("client",)), (("card",), ()),
               ((), ("rate", "running")))


@dataclass(frozen=True)
class Client:
    number: int
    name: str
    card: int | None
    ports: tuple  # ((port_number, port_name), ...)
    pid: int | None = None  # user clients only


def parse_aconnect(text):
    """({number: Client}, connections) from `aconnect -l`. Each connection is
    ((src_client, src_port), (dst_client, dst_port)), from the "Connecting To:" lines."""
    found, connections = {}, set()
    client = port = None
    for line in text.splitlines():
        m = re.match(r"client (\d+): '(.*)' \[(.*)\]", line)
        if m:
            card, pid = re.search(r"card=(\d+)", m[3]), re.search(r"pid=(\d+)", m[3])
            client, port = int(m[1]), None
            found[client] = Client(client, m[2], int(card[1]) if card else None, (), int(pid[1]) if pid else None)
            continue
        m = re.match(r"\s+(\d+) '(.*)'", line)
        if m and client is not None:
            port = int(m[1])
            c = found[client]
            found[client] = Client(c.number, c.name, c.card, c.ports + ((port, m[2].strip()),), c.pid)
            continue
        m = re.match(r"\s+Connecting To: (.*)", line)
        if m and port is not None:
            for entry in m[1].split(", "):
                dst = re.match(r"\s*(\d+):(\d+)", entry)
                if dst:
                    connections.add(((client, port), (int(dst[1]), int(dst[2]))))
    return found, connections


def parse_seq_caps(text):
    """{(client, port): (readable, writable)} from /proc/asound/seq/clients. Only R and W
    count: a lowercase r or w is a port that cannot be subscribed to."""
    caps, client = {}, None
    for line in text.splitlines():
        m = re.match(r"Client\s+(\d+) :", line)
        if m:
            client = int(m[1])
            continue
        m = re.match(r'\s+Port\s+(\d+) : ".*" \((.)(.)', line)
        if m and client is not None:
            caps[(client, int(m[1]))] = (m[2] == "R", m[3] == "W")
    return caps


def endpoints(clients, cards):
    """[(endpoint, client, port)] for every port of the clients of `cards` ({card: identity}),
    in client then port order. The endpoint is IDENTITY/PORT."""
    return [(f"{cards[c.card]}/{port}", c.number, port)
            for c in sorted(clients.values(), key=lambda c: c.number) if c.card in cards
            for port, _ in sorted(c.ports)]


def assign_cables(present, saved, ports, control):
    """(assigned {endpoint: cable}, parked [endpoint], saved') for the endpoints present, in
    order. With one cable all of them share it; otherwise they are allocated one cable each
    like audio blocks, around the control cable."""
    if ports == 1:
        return {ep: 1 for ep in present}, [], saved
    return allocate({ep: 1 for ep in present}, saved, {ep: 1 for ep in saved}, ports, [control], align=1)


def wanted_subscriptions(eps, assigned, caps, gadget_client, configured):
    """The subscriptions between the devices' ports and the gadget's while the gadget is
    configured: device -> gadget port k-1 when readable, gadget port k-1 -> device when writable."""
    wanted = set()
    if not configured or gadget_client is None:
        return wanted
    for ep, client, port in eps:
        cable = assigned.get(ep)
        if cable is None:
            continue
        readable, writable = caps.get((client, port), (False, False))
        if readable:
            wanted.add(((client, port), (gadget_client, cable - 1)))
        if writable:
            wanted.add(((gadget_client, cable - 1), (client, port)))
    return wanted


def stale_subscriptions(connections, wanted, gadget_client, device_clients):
    """The connections between a gadget port and a device client, either way, that are not wanted."""
    return {c for c in connections - wanted
            if (c[0][0] == gadget_client and c[1][0] in device_clients)
            or (c[1][0] == gadget_client and c[0][0] in device_clients)}


def parse_aseqdump(line):
    """("sysex", bytes), ("cc", channel 1-16, controller, value) or ("pc", channel 1-16, program)
    from one line of aseqdump; None for any other line."""
    m = re.match(r"\s*\d+:\d+\s+System exclusive\s+((?:[0-9A-Fa-f]{2}\s*)+)$", line)
    if m:
        return "sysex", bytes.fromhex(m[1])
    m = re.match(r"\s*\d+:\d+\s+Control change\s+(\d+), controller (\d+), value (\d+)\s*$", line)
    if m:
        return "cc", int(m[1]) + 1, int(m[2]), int(m[3])
    m = re.match(r"\s*\d+:\d+\s+Program change\s+(\d+), program (\d+)\s*$", line)
    if m:
        return "pc", int(m[1]) + 1, int(m[2])
    return None


def printable(text):
    return all(0x20 <= ord(ch) <= 0x7E for ch in text)


def sysex_text(data):
    """The text of an F0 7D 52 41 <text> F7 message; None for any other message."""
    if len(data) < 5 or data[:4] != SYSEX_HEAD or data[-1] != SYSEX_END:
        return None
    text = data[4:-1].decode("latin-1")
    return text if printable(text) else None


def sysex_hex(text, reply=False):
    """The F0 7D 52 41 <text> F7 message (52 42 for a reply) as uppercase hex bytes separated
    by spaces, as aseqsend and amidi take it."""
    if not printable(text):
        raise ValueError("text must be ASCII 0x20-0x7E")
    head = REPLY_HEAD if reply else SYSEX_HEAD
    return " ".join(f"{b:02X}" for b in head + text.encode("ascii") + bytes((SYSEX_END,)))


def smf_sysex(message):
    """A one-track Standard MIDI File holding one SysEx message (F0 ... F7), for aplaymidi.
    Unlike a direct send (aseqsend), aplaymidi subscribes to the port, and a kernel port
    drops events until something is subscribed to it."""
    def vlq(n):
        out = [n & 0x7F]
        while n > 0x7F:
            n >>= 7
            out.insert(0, (n & 0x7F) | 0x80)
        return bytes(out)
    track = b"\x00\xF0" + vlq(len(message) - 1) + message[1:] + b"\x00\xFF\x2F\x00"
    return (b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big")
            + (96).to_bytes(2, "big") + b"MTrk" + len(track).to_bytes(4, "big") + track)


@dataclass(frozen=True)
class Command:
    verb: str
    identity: str | None = None
    args: tuple = ()  # ((key, value), ...), so commands stay hashable

    def arg(self, key, default=None):
        return dict(self.args).get(key, default)


def number(key, value, low, high=None):
    if not re.fullmatch(r"-?\d+", value):
        raise ValueError(f"{key} must be an integer")
    n = int(value)
    if n < low or (high is not None and n > high):
        raise ValueError(f"{key} must be {low} or more" if high is None else f"{key} must be {low}..{high}")
    return n


def direction(value):
    if value not in (IN, OUT):
        raise ValueError("direction must be in or out")
    return value


def label(text, limit, what):
    """TEXT of a name command, checked."""
    if not printable(text):
        raise ValueError(f"{what} must be ASCII 0x20-0x7E")
    if len(text) > limit:
        raise ValueError(f"{what} must be at most {limit} characters")
    return text


def parse_name(text, usage):
    """name IDENTITY [TEXT] or name IDENTITY in|out K [TEXT]; TEXT is the rest of the line, trimmed.
    The channel form is taken when IDENTITY is followed by in or out and then an integer, so a
    device name cannot start with "in N" or "out N"."""
    m = re.fullmatch(r"\s*name\s+(\S+)(?:\s+(.*?))?\s*", text, re.S)
    if not m:
        raise usage
    tail = m[2] or ""
    ch = re.fullmatch(r"(in|out)\s+(-?\d+)(?:\s+(.*))?", tail, re.S)
    if ch:
        k = number("channel", ch[2], 1)
        return Command("name", m[1], (("direction", ch[1]), ("channel", k),
                                      ("text", label(ch[3] or "", presets.CHANNEL_NAME_MAX, "channel name"))))
    return Command("name", m[1], (("text", label(tail, presets.NAME_MAX, "name")),))


def parse_preset(text, usage):
    """preset save N [TEXT], preset load N or preset clear N."""
    m = re.fullmatch(r"\s*preset\s+(save|load|clear)\s+(\S+)(?:\s+(.*?))?\s*", text, re.S)
    if not m or (m[3] and m[1] != "save"):
        raise usage
    slot = number("slot", m[2], 1, presets.SLOTS)
    return Command("preset", None, (("action", m[1]), ("slot", slot),
                                    ("text", label(m[3] or "", presets.NAME_MAX, "preset name"))))


HOST_NAME = r"[A-Za-z0-9._-]{1,32}"


HOST_ACTIONS = ('save', 'delete', 'rename', 'preset')


def parse_host(rest, usage):
    def valid(name):
        return re.fullmatch(HOST_NAME, name) and name not in (*HOST_ACTIONS, 'default')

    if len(rest) == 1 and (rest[0] == 'default' or valid(rest[0])):
        return Command('host', None, (('action', 'select'), ('name', rest[0])))
    if len(rest) == 2 and rest[0] == 'delete' and valid(rest[1]):
        return Command('host', None, (('action', 'delete'), ('name', rest[1])))
    if len(rest) == 3 and rest[0] == 'rename' and valid(rest[1]) and valid(rest[2]):
        return Command('host', None, (('action', 'rename'), ('name', rest[1]), ('new_name', rest[2])))
    if len(rest) == 3 and rest[0] == 'preset' and valid(rest[1]):
        slot = None if rest[2] == 'none' else number('preset', rest[2], 1, presets.SLOTS)
        return Command('host', None, (('action', 'preset'), ('name', rest[1]), ('preset', slot)))
    if len(rest) >= 2 and rest[0] == 'save' and valid(rest[1]):
        given = {}
        for word in rest[2:]:
            if word in ('full', 'new') and word not in given:
                if word == 'full' and 'preset' in given:
                    raise usage
                given[word] = True
                continue
            key, eq, value = word.partition('=')
            key = {'in': 'reserve_in', 'out': 'reserve_out'}.get(key, key)
            if not eq or key not in ('reserve_in', 'reserve_out', 'preset') or key in given:
                raise usage
            if key == 'preset':
                if 'full' in given:
                    raise usage
                given[key] = number('preset', value, 1, presets.SLOTS)
            else:
                given[key] = sorted({number(key, k, 1) for k in value.split(',')} if value else set())
        return Command('host', None, (('action', 'save'), ('name', rest[1]), *given.items()))
    raise usage


def parse_command(text):
    """A Command from the text of a control SysEx (docs/MIDI.md). Raises ValueError with
    the message for the error reply."""
    words = text.split()
    if not words:
        raise ValueError("empty command")
    verb, rest = words[0], words[1:]
    if verb not in USAGE:
        raise ValueError(f"unknown command {verb}")
    usage = ValueError(f"usage: {USAGE[verb]}")
    if verb in ("ping", "status"):
        if rest:
            raise usage
        return Command(verb)
    if verb == "name":
        return parse_name(text, usage)
    if verb == "preset":
        return parse_preset(text, usage)
    if verb == "engine":
        if len(rest) != 1 or rest[0] not in ("host", "standalone", "hub"):
            raise usage
        return Command(verb, None, (("mode", rest[0]),))
    if verb == "host":
        return parse_host(rest, usage)
    if verb == "usb":
        if len(rest) != 2 or rest[0] != "latency" or rest[1] not in ("low", "normal"):
            raise usage
        return Command(verb, None, (("latency", rest[1]),))
    if verb == 'output':
        if len(rest) == 3 and rest[0] in outputs.IDS and rest[1] == 'level':
            return Command(verb, rest[0], (('level', number('level', rest[2], 0, 100)),))
        if len(rest) != 2 or rest[0] not in outputs.IDS or rest[1] not in ('on', 'off'):
            raise usage
        return Command(verb, rest[0], (('on', rest[1] == 'on'),))
    if verb in ("midiroute", "midiunroute"):
        if len(rest) != 2:
            raise usage
        return Command(verb, rest[0], (("dst", rest[1]),))
    if verb in ("route", "unroute"):
        if len(rest) < 2:
            raise usage
        given = {}
        for word in rest[2:]:
            key, eq, value = word.partition("=")
            if not eq or key not in ("src", "dst") or key in given:
                raise usage
            given[key] = number(key, value, 1)
        args = (("dst", rest[1]), *((f"{k}_pair", given[k]) for k in ("src", "dst") if k in given))
        return Command(verb, rest[0], args)
    if verb == "assign":
        if len(rest) < 2:
            raise usage
        given = {}
        for word in rest[1:]:
            key, eq, value = word.partition("=")
            if not eq or key not in ("in", "out", "midi") or key in given:
                raise usage
            given[key] = number(key, value, 1)
        return Command(verb, rest[0], tuple((k, given[k]) for k in ("in", "out", "midi") if k in given))
    if len(rest) != 3:
        raise usage
    if verb == "mute":
        if rest[2] not in ("on", "off"):
            raise ValueError("expected on or off")
        return Command(verb, rest[0], (("direction", direction(rest[1])), ("on", rest[2] == "on")))
    side = direction(rest[1])
    return Command(verb, rest[0], (("direction", side), ("percent", number("percent", rest[2], 0, 100))))


def status_reply(data, limit=STATUS_LIMIT):
    """The status dict as the compact JSON of the status reply. Over `limit` bytes, it first loses
    diagnostic keys (STATUS_TRIM), never names, levels, routes or presets; /run/rpi-audio/status.json
    keeps them all."""
    def dump(d):
        return json.dumps(d, separators=(",", ":"), sort_keys=True)
    text = dump(data)
    if len(text.encode()) <= limit:
        return text
    data = copy.deepcopy(data)
    data.pop("session", None)
    data.pop("profile_readiness", None)
    data.pop("engine", None)
    data.pop("bridge_buffer", None)
    data.pop("host_profiles", None)
    data.pop("host_profile_details", None)
    data.pop('active_scene', None)
    data.pop("usb_buses", None)
    data.pop("outputs", None)  # adapter diagnostics stay in the full local status file
    data.pop("time", None)
    data["devices"] = [dev for dev in data.get("devices", []) if not dev.get("virtual")]
    for dev_keys, dir_keys in STATUS_TRIM:
        for dev in data.get("devices", []):
            for key in dev_keys:
                dev.pop(key, None)
            for side in (IN, OUT):
                for key in dir_keys:
                    dev.get(side, {}).pop(key, None)
        text = dump(data)
        if len(text.encode()) <= limit:
            break
    return text


def cc_percent(value):
    """A 0-127 CC value as a 0-100 percentage."""
    return round(value * 100 / 127)


def cc_command(channel, controller, value, channels, starts):
    """The Command for a control CC (docs/MIDI.md). channels is (IN channel, OUT channel); on
    each, CC 32+N sets the level and CC 64+N mutes the device whose block in that direction
    starts at host channel N (1-27). No other CC is a command: not the channel mode messages
    (120-127) hosts send on stop, nor the CCs they reset (0, 1, 7, 10, 64...). starts is
    {IN: {start: identity}, OUT: {...}}. None when the CC is not for a device."""
    if channel not in channels:
        return None
    side = IN if channel == channels[0] else OUT
    bank, n = divmod(controller, 32)
    if bank not in (1, 2) or not 1 <= n <= 27:
        return None
    ident = starts.get(side, {}).get(n)
    if ident is None:
        return None
    if bank == 1:
        return Command("volume", ident, (("direction", side), ("percent", cc_percent(value))))
    return Command("mute", ident, (("direction", side), ("on", value >= 64)))


def program_command(channel, program, channel_in):
    """The `preset load` Command for a Program Change on the control channel (programs 0..7 are
    presets 1..8); None for any other channel or program."""
    if channel != channel_in or not 0 <= program < presets.SLOTS:
        return None
    return Command("preset", None, (("action", "load"), ("slot", program + 1), ("text", "")))


def split_endpoint(ident):
    """(device identity, port) from IDENTITY or IDENTITY/P; the port defaults to 0."""
    m = re.fullmatch(r"(.*)/(\d+)", ident)
    return (m[1], int(m[2])) if m else (ident, 0)


def apply_command(state, cmd):
    """(new state, reply) after assign, mute, volume or name on the slots.json dict, which is not
    modified. Audio settings are keyed by the device identity, MIDI cables by IDENTITY/P."""
    state = copy.deepcopy(state or {})
    device, port = split_endpoint(cmd.identity or "")
    if cmd.verb == "engine":
        state["engine_mode"] = cmd.arg("mode")
    elif cmd.verb == "usb":
        # Read by rpi-audio-gadget at boot: it takes effect on the next restart, not now.
        if cmd.arg("latency") == "low":
            state["usb_latency"] = "low"
        else:
            state.pop("usb_latency", None)
    elif cmd.verb == "host":
        if cmd.arg("action") != "select":
            raise ValueError("host save and delete change the profile store, not slots.json")
        if cmd.arg("name") == "default":
            state.pop("host_profile", None)
        else:
            state["host_profile"] = cmd.arg("name")
    elif cmd.verb == 'output':
        if cmd.arg('level') is not None:
            state.setdefault('output_levels', {})[cmd.identity] = cmd.arg('level')
        else:
            state.setdefault('outputs', {})[cmd.identity] = cmd.arg('on')
    elif cmd.verb == "midiroute":
        midiroute.add(state, midiroute.Link(cmd.identity, cmd.arg("dst")))
    elif cmd.verb == "midiunroute":
        midiroute.remove(state, cmd.identity, cmd.arg("dst"))
    elif cmd.verb == "route":
        routing.add(state, routing.Route(cmd.identity, cmd.arg("dst"), cmd.arg("src_pair", 1), cmd.arg("dst_pair", 1)))
    elif cmd.verb == "unroute":
        routing.remove(state, cmd.identity, cmd.arg("dst"), cmd.arg("src_pair"), cmd.arg("dst_pair"))
    elif cmd.verb == "assign":
        for key in (IN, OUT):
            if cmd.arg(key) is not None:
                state.setdefault(key, {})[device] = cmd.arg(key)
        if cmd.arg("midi") is not None:
            state.setdefault("midi", {})[f"{device}/{port}"] = cmd.arg("midi")
    elif cmd.verb == "mute":
        muted = state.setdefault("mute", {})
        side = set(muted.get(cmd.arg("direction"), []))
        muted[cmd.arg("direction")] = sorted(side | {device} if cmd.arg("on") else side - {device})
    elif cmd.verb == "volume":
        state.setdefault("volume", {}).setdefault(cmd.arg("direction"), {})[device] = cmd.arg("percent")
    elif cmd.verb == "name":
        presets.set_name(state, cmd.identity, cmd.arg("text"), cmd.arg("direction"), cmd.arg("channel"))
    else:
        raise ValueError(f"{cmd.verb} is not a state change")
    return state, "ok"


def apply_host(store, cmd, current, state=None):
    """Save reservations or a full setup, delete or rename a user-owned profile; never mutates its inputs."""
    store, name = copy.deepcopy(store or {}), cmd.arg('name')
    action = cmd.arg('action')
    if action in ('delete', 'rename'):
        if name not in store:
            raise ValueError(f'no saved host profile {name}')
        if action == 'rename':
            new = cmd.arg('new_name')
            if new != name and new in store:
                raise ValueError(f'host profile {new} already exists')
            if new != name:
                store[new] = store.pop(name)
        else:
            del store[name]
    elif action == 'save':
        profile = {f'reserve_{d}': cmd.arg(f'reserve_{d}', current.get(d, [])) for d in (IN, OUT)}
        if cmd.arg('full', False):
            profile['state'] = presets.capture_state(state or {})
        elif cmd.arg('preset') is not None:
            profile['preset'] = cmd.arg('preset')
        store[name] = profile
    else:
        raise ValueError('not a host save, delete or rename command')
    return store


def apply_preset(state, store, cmd, saved):
    """(new slots.json dict, new presets.json dict) after preset save, load or clear; neither is
    modified. `saved` is the time to record on a save. ValueError when loading an empty slot."""
    state, store = copy.deepcopy(state or {}), copy.deepcopy(store or {})
    slot = cmd.arg("slot")
    if cmd.verb != "preset":
        raise ValueError(f"{cmd.verb} is not a preset command")
    if cmd.arg("action") == "save":
        presets.save_preset(store, state, slot, cmd.arg("text"), saved)
        presets.mark_active(state, slot)
    elif cmd.arg("action") == "load":
        presets.load_preset(state, store, slot)
        presets.mark_active(state, slot)
    else:
        store.pop(str(slot), None)
        if (state.get('active_scene') or {}).get('slot') == slot:
            state.pop('active_scene', None)
    return state, store
