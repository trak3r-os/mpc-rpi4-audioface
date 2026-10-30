# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's pure logic: device capabilities, identities, channel slots, routes and
what has to feed the gadget. Nothing here touches the system, so tests/test_audiod.py
checks it on any machine. The service itself is bridge/rpi-audiod/rpi-audiod."""

import re
from dataclasses import dataclass

IN, OUT = "in", "out"  # gadget directions: IN is Pi -> host, OUT is host -> Pi


@dataclass(frozen=True)
class Altset:
    channels: int
    rates: tuple  # the discrete rates, or (lowest, highest) when continuous
    continuous: bool = False
    interface: int = 0  # USB interface and alternate setting numbers, 0 when stream0 gives none
    altset: int = 0

    def supports(self, rate):
        if self.continuous:
            return self.rates[0] <= rate <= self.rates[1]
        return rate in self.rates


def parse_stream(text):
    """Parses /proc/asound/cardN/stream0 of a USB audio card into
    {"playback": [Altset, ...], "capture": [Altset, ...]}. The "Interface = N" lines of a
    running stream's Status block are not altset headers and are skipped."""
    found = {"playback": [], "capture": []}
    section = channels = None
    interface = altset = 0
    for line in text.splitlines():
        s = line.strip()
        header = re.fullmatch(r"(Interface|Altset) (\d+)", s)
        if s in ("Playback:", "Capture:"):
            section = s[:-1].lower()
        elif header:
            if header[1] == "Interface":
                interface = int(header[2])
            else:
                altset = int(header[2])
        elif section and s.startswith("Channels:"):
            channels = int(s.split(":")[1])
        elif section and channels and s.startswith("Rates:"):
            value = s.split(":", 1)[1]
            span = re.match(r"\s*(\d+)\s*-\s*(\d+)", value)
            if span:
                found[section].append(Altset(channels, (int(span[1]), int(span[2])), True, interface, altset))
            else:
                rates = tuple(sorted(int(r) for r in re.findall(r"\d+", value)))
                found[section].append(Altset(channels, rates, False, interface, altset))
            channels = None
    return found


def plan_direction(altsets, preferred):
    """(rate, channels) to open one direction at: the first preferred rate the device
    supports, otherwise its highest; the most channels any altset offers at that rate.
    None when the direction does not exist."""
    if not altsets:
        return None
    rate = next((r for r in preferred if any(a.supports(r) for a in altsets)), None)
    if rate is None:
        rate = max(a.rates[-1] for a in altsets)
    return rate, max(a.channels for a in altsets if a.supports(rate))


FILLER_SERIAL = re.compile(r"^(.)\1*$|^0+1?$")


def identity(vendor, product, serial, port):
    """Stable identity (docs/PLAN.md §2): usb-VID:PID-serial, or usb-PORT-VID:PID when
    the device has no usable serial (missing, under 3 characters, one repeated
    character, or 0...01). bcdDevice stays out, so a firmware update keeps the slots.
    Spaces and slashes in the serial become _, so the identity is one word in a command
    and IDENTITY/PORT stays unambiguous (docs/MIDI.md)."""
    serial = re.sub(r"[\s/]", "_", (serial or "").strip())
    if len(serial) >= 3 and not FILLER_SERIAL.match(serial):
        return f"usb-{vendor}:{product}-{serial}"
    return f"usb-{port}-{vendor}:{product}"


def dedupe(identities):
    """Appends #2, #3... to repeated identities, in order."""
    seen, out = {}, []
    for i in identities:
        seen[i] = seen.get(i, 0) + 1
        out.append(i if seen[i] == 1 else f"{i}#{seen[i]}")
    return out


def client_name(card_id, direction):
    """JACK client name of a device's bridge, e.g. gp150_in."""
    return re.sub(r"[^a-z0-9_]", "_", card_id.lower()) + ("_in" if direction == IN else "_out")


def block(start, size):
    return set(range(start, start + size))


def free_start(size, total, taken, align=2):
    """First block of `size` gadget channels in 1..total that avoids `taken` and starts
    on an odd channel with align 2 (stereo pairs stay aligned), on any with align 1;
    None when there is none."""
    for start in range(1, total - size + 2, align):
        if not block(start, size) & taken:
            return start
    return None


def allocate(present, saved, sizes_saved, total, reserved, align=2, preferred=None):
    """Gives each present device a block of gadget channels in one direction.

    present: {identity: channels} for the devices plugged in now, in the order they appeared.
    saved: {identity: start} remembered from before, for present and absent devices.
    sizes_saved: {identity: channels} for the saved blocks of absent devices.
    A device gets its saved block back if it is still free; a new one gets the first free
    block that no absent device holds, then one taken from absent devices, else it is parked.
    New blocks start as free_start() places them with `align`.
    preferred: {identity: start} from device profiles, tried first for a device with no
    saved block, and only where the block is free of other devices, absent ones included;
    those devices are placed before the rest.
    Returns (assigned {identity: start}, parked [identity], saved')."""
    taken = set(reserved)
    assigned, parked, saved = {}, [], dict(saved)
    for dev, size in present.items():
        start = saved.get(dev)
        if start is not None and start + size - 1 <= total and not block(start, size) & taken:
            assigned[dev] = start
            taken |= block(start, size)
    absent = set()
    for dev, start in saved.items():
        if dev not in present and dev in sizes_saved:
            absent |= block(start, sizes_saved[dev])
    preferred = preferred or {}
    for dev in sorted((d for d in present if d not in assigned), key=lambda d: d not in preferred):
        size = present[dev]
        start = preferred.get(dev)
        if start is None or start < 1 or start + size - 1 > total or block(start, size) & (taken | absent):
            start = free_start(size, total, taken | absent, align)
        if start is None:
            start = free_start(size, total, taken, align)
        if start is None:
            parked.append(dev)
            continue
        for other in [d for d, s in saved.items() if d not in present and d in sizes_saved]:
            if block(saved[other], sizes_saved[other]) & block(start, size):
                del saved[other]
        assigned[dev] = saved[dev] = start
        taken |= block(start, size)
    return assigned, parked, saved


def kept_channels(channels, ignore):
    """The device channels (1-based) that get a gadget slot, out of `channels`."""
    return [k for k in range(1, channels + 1) if k not in ignore]


def routes(client, direction, start, kept):
    """JACK connections between a bridge and the gadget (jackd's system ports):
    device capture -> host IN on playback_N, host OUT on capture_N -> device playback.
    kept is a channel count or the list of device channels to route, which take
    consecutive slots from `start`."""
    if isinstance(kept, int):
        kept = range(1, kept + 1)
    slots = list(enumerate(kept))
    if direction == IN:
        return [(f"{client}:capture_{k}", f"system:playback_{start + i}") for i, k in slots]
    return [(f"system:capture_{start + i}", f"{client}:playback_{k}") for i, k in slots]


def feeder(playback_rate, capture_rate):
    """What has to play into the gadget: "jack" while the host streams both ways at one
    rate, "silence" while it only records from the Pi, None while it does not record.
    Some hosts drop the gadget when nothing plays into it (docs/hw/2026-10-29-f1-force.md)."""
    if not playback_rate:
        return None
    return "jack" if capture_rate == playback_rate else "silence"


def parse_controls(text):
    """{name: value} for the gadget's rate controls, from `amixer -c CARD contents`."""
    out, name = {}, None
    for line in text.splitlines():
        m = re.search(r"name='([^']*)'", line)
        if m:
            name = m[1]
            continue
        m = re.match(r"\s*: values=(\d+)", line)
        if m and name:
            out[name] = int(m[1])
            name = None
    return out


def silent_volumes(text):
    """Simple mixer controls whose playback volume is at 0 on every channel, from
    `amixer -c CARD scontents`, as "NAME,INDEX". Some devices come up like that (the
    GP-150) and would play nothing."""
    found, name, pvolume, levels = [], None, False, []

    def close():
        if name and pvolume and levels and not any(levels):
            found.append(name)

    for line in text.splitlines():
        m = re.match(r"Simple mixer control '(.*)',(\d+)", line)
        if m:
            close()
            name, pvolume, levels = f"{m[1]},{m[2]}", False, []
        elif "Capabilities:" in line:
            pvolume = "pvolume" in line.split()
        else:
            m = re.search(r"Playback (\d+) \[\d+%\]", line)
            if m:
                levels.append(int(m[1]))
    close()
    return found


def volume_controls(text, direction):
    """Simple mixer controls with a volume in one direction, from `amixer -c CARD scontents`,
    as "NAME,INDEX": device capture ("cvolume") for IN, device playback ("pvolume") for OUT."""
    want = "cvolume" if direction == IN else "pvolume"
    found, name = [], None
    for line in text.splitlines():
        m = re.match(r"Simple mixer control '(.*)',(\d+)", line)
        if m:
            name = f"{m[1]},{m[2]}"
        elif name and line.strip().startswith("Capabilities:") and want in line.split():
            found.append(name)
    return found


def parse_connections(text):
    """(ports, connected pairs) from `jack_lsp -c`: every port, and each connection as a
    frozenset of its two ports."""
    ports, pairs, current = set(), set(), None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0].isspace():
            if current:
                pairs.add(frozenset((current, line.strip())))
        else:
            current = line.strip()
            ports.add(current)
    return ports, pairs


def pcm_status(text):
    """(state, hw_ptr) from /proc/asound/CARD/pcm0p/sub0/status; ("closed", None) when closed."""
    state = re.search(r"state:\s*(\S+)", text)
    ptr = re.search(r"hw_ptr\s*:\s*(\d+)", text)
    return (state[1] if state else "closed"), (int(ptr[1]) if ptr else None)


@dataclass(frozen=True)
class Profile:
    """An optional device profile (config/devices.d/*.toml)."""
    match: str                 # "idVendor:idProduct", lowercase hex
    source: str = ""           # file name, for messages
    bcd: str = ""              # only this bcdDevice, when set
    name: str = ""
    rate: int = 0              # preferred rate, 0 for none
    start_in: int = 0          # preferred first gadget channel, 0 for none
    start_out: int = 0
    names_in: tuple = ()       # device channel names, from channel 1
    names_out: tuple = ()
    ignore_in: tuple = ()      # device channels that get no gadget slot
    ignore_out: tuple = ()

    def get(self, key, direction):
        return getattr(self, f"{key}_{direction}")


def _hex(digits):
    def check(value):
        if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{digits}}}", value):
            raise ValueError(f"{digits} lowercase hex digits")
        return value
    return check


def _int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("a positive integer")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("a non-empty string")
    return value.strip()


def _names(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("a list of strings")
    return tuple(value)


def _channels(value):
    try:
        return tuple(sorted({_int(v) for v in value}))
    except (TypeError, ValueError):
        raise ValueError("a list of channel numbers, 1 and up") from None


PROFILE_KEYS = {"bcd": _hex(4), "name": _text, "rate": _int, "start_in": _int, "start_out": _int,
                "names_in": _names, "names_out": _names, "ignore_in": _channels, "ignore_out": _channels}


def parse_profile(data, source=""):
    """(Profile or None, [warning]) from the table of one profile file: a bad `match` drops
    the file, an unknown key or a bad value only that key."""
    match = data.get("match")
    if not isinstance(match, str) or not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", match):
        return None, [f"{source}: match must be idVendor:idProduct in lowercase hex, like \"84ef:0186\"; file ignored"]
    fields, warnings = {}, []
    for key, value in data.items():
        if key == "match":
            continue
        if key not in PROFILE_KEYS:
            warnings.append(f"{source}: unknown key '{key}' ignored")
            continue
        try:
            fields[key] = PROFILE_KEYS[key](value)
        except ValueError as e:
            warnings.append(f"{source}: '{key}' must be {e}; ignored")
    return Profile(match, source, **fields), warnings


def match_profile(profiles, vendor, product, bcd):
    """(Profile or None, [warning]) for a device: those with its VID:PID and, when set, its
    bcdDevice; one with a bcd beats one without; of equals, the first by file name."""
    hits = [p for p in profiles if p.match == f"{vendor}:{product}".lower() and p.bcd in ("", bcd.lower())]
    best = [p for p in hits if p.bcd] or hits
    best.sort(key=lambda p: p.source)
    if len(best) > 1:
        names = ", ".join(p.source for p in best)
        return best[0], [f"profiles {names} match {vendor}:{product} equally; using {best[0].source}"]
    return (best[0] if best else None), []
