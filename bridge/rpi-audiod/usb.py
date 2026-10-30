# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's USB bandwidth logic: the isochronous load of a full-speed device from its
descriptors, and the per-bus budget (docs/PLAN.md, "Presupuesto USB Full-Speed"). Nothing
here touches the system, so tests/test_usb.py checks it on any machine."""

from typing import NamedTuple

FS_BUDGET = 1099   # B per frame the Pi 4's VL805 accepted (docs/hw/2026-10-29-f2-usb-devices.md)
ISOCHRONOUS = 1


class Endpoint(NamedTuple):
    address: int
    attributes: int
    packet: int     # wMaxPacketSize as it is in the descriptor
    interval: int


def parse_descriptors(data, active):
    """{(interface, altset): [Endpoint, ...]} of configuration `active` (its
    bConfigurationValue), from the raw sysfs `descriptors` file: the device descriptor, then
    each configuration's. Stops at a descriptor that is empty or runs past the end."""
    found, config, key, pos = {}, None, None, 0
    while pos + 2 <= len(data):
        length, kind = data[pos], data[pos + 1]
        if length < 2 or pos + length > len(data):
            break
        body = data[pos:pos + length]
        if kind == 2 and length >= 6:
            config, key = body[5], None
        elif kind == 4 and length >= 4:
            key = (body[2], body[3])
            if config == active:
                found.setdefault(key, [])
        elif kind == 5 and length >= 7 and key and config == active:
            found[key].append(Endpoint(body[2], body[3], body[4] | body[5] << 8, body[6]))
        pos += length
    return found


def full_speed(speed):
    """True for a full or low speed device (sysfs `speed`, in Mbit/s), False for faster
    ones, None when it is not a number."""
    try:
        return float(speed) <= 12
    except ValueError:
        return None


def direction_load(speed, altsets, plan, interfaces):
    """Isochronous bytes per frame one bridge direction takes on the bus: 0 for a device faster
    than full speed; otherwise the largest total of wMaxPacketSize (data and feedback
    endpoints) among the altsets that match the plan (same channels, supports its rate).
    None when it cannot be told (an altset the descriptors lack or give no
    isochronous endpoint). interfaces is parse_descriptors()'s result."""
    fs = full_speed(speed)
    if fs is None or not plan:
        return None
    if not fs:
        return 0
    rate, channels = plan
    loads = []
    for a in altsets:
        if a.channels != channels or not a.supports(rate):
            continue
        endpoints = interfaces.get((a.interface, a.altset))
        total = sum(e.packet & 0x7ff for e in endpoints or () if e.attributes & 3 == ISOCHRONOUS)
        if not total:   # not in the descriptors, or a stream altset with no isochronous endpoint
            return None
        loads.append(total)
    return max(loads) if loads else None


def budget_reason(load, used, budget, bus):
    """Why a bridge of `load` B cannot start with `used` B taken on its bus, or None when it
    fits (or the check is off: budget 0, or no known load)."""
    if not budget or not load or load <= budget - used:
        return None
    free = max(budget - used, 0)
    return f"USB full-speed budget: needs {load} B, {free} B of {budget} B free on bus {bus}"
