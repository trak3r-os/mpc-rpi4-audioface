# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's MIDI logic (docs/MIDI.md): sequencer clients, cables, subscriptions and the
control cable's SysEx and CC commands. Nothing here touches the system: the service passes
in the outputs of aconnect, /proc/asound/seq/clients and aseqdump. tests/test_midi.py checks it."""

import copy
import re
from dataclasses import dataclass

from audiod import IN, OUT, allocate

SYSEX_HEAD = bytes((0xF0, 0x7D, 0x52, 0x41))  # non-commercial id 7D, then "RA": a command
REPLY_HEAD = bytes((0xF0, 0x7D, 0x52, 0x42))  # "RB": a reply, never taken for a command when echoed
SYSEX_END = 0xF7
USAGE = {
    "ping": "ping",
    "status": "status",
    "assign": "assign IDENTITY [in=N] [out=N] [midi=K]",
    "mute": "mute IDENTITY in|out on|off",
    "volume": "volume IDENTITY in|out PERCENT",
}


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
    """("sysex", bytes) or ("cc", channel 1-16, controller, value) from one line of aseqdump;
    None for any other line."""
    m = re.match(r"\s*\d+:\d+\s+System exclusive\s+((?:[0-9A-Fa-f]{2}\s*)+)$", line)
    if m:
        return "sysex", bytes.fromhex(m[1])
    m = re.match(r"\s*\d+:\d+\s+Control change\s+(\d+), controller (\d+), value (\d+)\s*$", line)
    if m:
        return "cc", int(m[1]) + 1, int(m[2]), int(m[3])
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


def split_endpoint(ident):
    """(device identity, port) from IDENTITY or IDENTITY/P; the port defaults to 0."""
    m = re.fullmatch(r"(.*)/(\d+)", ident)
    return (m[1], int(m[2])) if m else (ident, 0)


def apply_command(state, cmd):
    """(new state, reply) after assign, mute or volume on the slots.json dict, which is not
    modified. Audio settings are keyed by the device identity, MIDI cables by IDENTITY/P."""
    state = copy.deepcopy(state or {})
    device, port = split_endpoint(cmd.identity or "")
    if cmd.verb == "assign":
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
    else:
        raise ValueError(f"{cmd.verb} is not a state change")
    return state, "ok"
