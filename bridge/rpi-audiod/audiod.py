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

    def supports(self, rate):
        if self.continuous:
            return self.rates[0] <= rate <= self.rates[1]
        return rate in self.rates


def parse_stream(text):
    """Parses /proc/asound/cardN/stream0 of a USB audio card into
    {"playback": [Altset, ...], "capture": [Altset, ...]}."""
    found = {"playback": [], "capture": []}
    section = channels = None
    for line in text.splitlines():
        s = line.strip()
        if s in ("Playback:", "Capture:"):
            section = s[:-1].lower()
        elif section and s.startswith("Channels:"):
            channels = int(s.split(":")[1])
        elif section and channels and s.startswith("Rates:"):
            value = s.split(":", 1)[1]
            span = re.match(r"\s*(\d+)\s*-\s*(\d+)", value)
            if span:
                found[section].append(Altset(channels, (int(span[1]), int(span[2])), True))
            else:
                rates = tuple(sorted(int(r) for r in re.findall(r"\d+", value)))
                found[section].append(Altset(channels, rates))
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


def allocate(present, saved, sizes_saved, total, reserved, align=2):
    """Gives each present device a block of gadget channels in one direction.

    present: {identity: channels} for the devices plugged in now, in the order they appeared.
    saved: {identity: start} remembered from before, for present and absent devices.
    sizes_saved: {identity: channels} for the saved blocks of absent devices.
    A device gets its saved block back if it is still free; a new one gets the first free
    block that no absent device holds, then one taken from absent devices, else it is parked.
    New blocks start as free_start() places them with `align`.
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
    for dev, size in present.items():
        if dev in assigned:
            continue
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


def routes(client, direction, start, channels):
    """JACK connections between a bridge and the gadget (jackd's system ports):
    device capture -> host IN on playback_N, host OUT on capture_N -> device playback."""
    if direction == IN:
        return [(f"{client}:capture_{k}", f"system:playback_{start + k - 1}") for k in range(1, channels + 1)]
    return [(f"system:capture_{start + k - 1}", f"{client}:playback_{k}") for k in range(1, channels + 1)]


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
