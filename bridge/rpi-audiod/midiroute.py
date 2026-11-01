# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's MIDI routes between USB devices: what one device's MIDI port sends, played into another's.
They live in slots.json under "midi_routes" and in presets; the service turns them into kernel sequencer
subscriptions (aconnect) between the devices' ports. Nothing here touches the system; tests/test_midiroute.py
checks it.

An end of a route is a MIDI endpoint, IDENTITY/PORT (docs/MIDI.md): the device identity the audio uses and the
port number of its sequencer client, from 0; IDENTITY alone is port 0. The source must be a readable port (the
device sends MIDI) and the destination a writable one (it receives). A device is never routed to itself."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Link:
    src: str   # IDENTITY/PORT of the port that sends
    dst: str   # IDENTITY/PORT of the port that receives


def split(endpoint):
    """(identity, port) from IDENTITY/PORT; the port is None when there is none."""
    m = re.fullmatch(r"(.*)/(\d+)", endpoint)
    return (m[1], int(m[2])) if m else (endpoint, None)


def normal(endpoint):
    """IDENTITY/PORT, with the port 0 when it was left out."""
    identity, port = split(endpoint)
    return f"{identity}/{port or 0}"


def check(link):
    """ValueError when a route can never work, whatever is plugged in."""
    if split(link.src)[0] == split(link.dst)[0]:
        raise ValueError("a device cannot be routed to itself")


def entry(link):
    return {"src": link.src, "dst": link.dst}


def from_state(state):
    """The links of a slots.json dict, in stored order. Entries that are not valid are skipped, so a
    hand-edited file cannot stop the service."""
    links = []
    for item in (state or {}).get("midi_routes", []):
        try:
            link = Link(normal(item["src"]), normal(item["dst"]))
            check(link)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if link not in links:
            links.append(link)
    return links


def store(state, links):
    """Writes `links` back into the state dict in place; no links, no key."""
    if links:
        state["midi_routes"] = [entry(link) for link in links]
    else:
        state.pop("midi_routes", None)


def add(state, link):
    """Adds a link to the state dict in place (the ports normalised); False when it was already there.
    ValueError from check."""
    link = Link(normal(link.src), normal(link.dst))
    check(link)
    links = from_state(state)
    if link in links:
        return False
    store(state, [*links, link])
    return True


def matches(end, given):
    """Is the endpoint `end` (IDENTITY/PORT) what `given` names? A given IDENTITY alone is any of its ports."""
    identity, port = split(given)
    return split(end)[0] == identity and port in (None, split(end)[1])


def remove(state, src, dst):
    """Removes the links from src to dst (a side without a port is any port of that device) from the state
    dict in place; how many went."""
    links = from_state(state)
    keep = [k for k in links if not (matches(k.src, src) and matches(k.dst, dst))]
    store(state, keep)
    return len(links) - len(keep)


def wanted(links, eps, caps):
    """(subscriptions, pending): the ((client, port), (client, port)) pairs to subscribe, and [(link, why)] for
    the links that cannot be made yet. eps is midi.endpoints(): [(endpoint, client, port)]; caps is
    midi.parse_seq_caps(): {(client, port): (readable, writable)}."""
    ports = {ep: (client, port) for ep, client, port in eps}
    subs, pending = set(), []
    for link in links:
        src, dst = ports.get(link.src), ports.get(link.dst)
        if src is None or dst is None:
            pending.append((link, f"{link.src if src is None else link.dst} is not here"))
        elif not caps.get(src, (False, False))[0]:
            pending.append((link, f"{link.src} cannot send MIDI"))
        elif not caps.get(dst, (False, False))[1]:
            pending.append((link, f"{link.dst} cannot receive MIDI"))
        else:
            subs.add((src, dst))
    return subs, pending


def reconcile(subs, connections, device_clients, owned=None):
    """(to_connect, to_disconnect): what to subscribe and what to drop so the subscriptions between two USB
    devices' clients are `subs`. connections is midi.parse_aconnect()'s set. Others, a device's own loop
    included, are never touched. owned limits what may be dropped to those subscriptions (the ones this service
    made); None: every subscription between two devices is the service's."""
    between = {c for c in connections
               if c[0][0] in device_clients and c[1][0] in device_clients and c[0][0] != c[1][0]}
    stale = between - subs
    if owned is not None:
        stale &= owned
    return sorted(subs - connections), sorted(stale)
