# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's device-to-device routes: what one USB device captures, played into another (or into a
local output). They live in slots.json under "routes" and in presets; the service turns them into JACK
connections between the bridges' ports. Nothing here touches the system; tests/test_routing.py checks it.

A route joins one stereo pair of the source's capture to one stereo pair of the destination's playback
(pair 1 is channels 1-2, pair 2 is 3-4...). A mono side takes or feeds both channels of the other: a mono
source is copied to both, a stereo source into a mono destination is summed. Naming follows audiod: a
device's "in" bridge is its capture (a source here) and its "out" bridge is its playback (a destination).
A device is never routed to itself: its playback often leaks into its capture, and that is a loop."""

from dataclasses import dataclass

from audiod import IN, OUT


@dataclass(frozen=True)
class Route:
    src: str            # identity of the device whose capture feeds the route
    dst: str            # identity of the device (or local output) whose playback receives it
    src_pair: int = 1
    dst_pair: int = 1


def check(route):
    """ValueError when a route can never work, whatever is plugged in."""
    if route.src == route.dst:
        raise ValueError("a device cannot be routed to itself")
    if route.src_pair < 1 or route.dst_pair < 1:
        raise ValueError("pairs start at 1")


def entry(route):
    """The slots.json form: pairs equal to 1 are left out."""
    out = {"src": route.src, "dst": route.dst}
    for key in ("src_pair", "dst_pair"):
        if getattr(route, key) != 1:
            out[key] = getattr(route, key)
    return out


def from_state(state):
    """The routes of a slots.json dict, in stored order. Entries that are not valid are skipped, so a
    hand-edited file cannot stop the service."""
    routes = []
    for item in (state or {}).get("routes", []):
        try:
            route = Route(item["src"], item["dst"], int(item.get("src_pair", 1)), int(item.get("dst_pair", 1)))
            check(route)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if isinstance(route.src, str) and isinstance(route.dst, str) and route not in routes:
            routes.append(route)
    return routes


def store(state, routes):
    """Writes `routes` back into the state dict in place; no routes, no key."""
    if routes:
        state["routes"] = [entry(r) for r in routes]
    else:
        state.pop("routes", None)


def add(state, route):
    """Adds a route to the state dict in place; False when it was already there. ValueError from check."""
    check(route)
    routes = from_state(state)
    if route in routes:
        return False
    store(state, [*routes, route])
    return True


def remove(state, src, dst, src_pair=None, dst_pair=None):
    """Removes the routes src -> dst (only those of the given pair, when one is given) from the state dict
    in place; how many went."""
    routes = from_state(state)
    keep = [r for r in routes if not (r.src == src and r.dst == dst
                                      and src_pair in (None, r.src_pair) and dst_pair in (None, r.dst_pair))]
    store(state, keep)
    return len(routes) - len(keep)


def toggle(state, route):
    """Adds the route, or removes it when it is there; True when it is now on."""
    if add(state, route):
        return True
    remove(state, route.src, route.dst, route.src_pair, route.dst_pair)
    return False


def pair_count(channels):
    return (channels + 1) // 2


def pair_channels(pair, channels):
    """The channels (1-based) of a stereo pair on a device with `channels`: two, or one for the odd last."""
    return [c for c in (2 * pair - 1, 2 * pair) if c <= channels]


def links(src, dst):
    """[(source channel, destination channel)] joining two pairs given as channel lists."""
    if len(src) == len(dst):
        return list(zip(src, dst))
    if len(src) == 1:
        return [(src[0], d) for d in dst]
    return [(s, dst[0]) for s in src]


def wanted(routes, bridges, muted, ports):
    """(connections, pending) for the routes.

    bridges: {(identity, "in"|"out"): (jack client, channels)} for every bridge that exists.
    muted: {"in": set of identities, "out": set} whose routes are cut.
    ports: the JACK ports that exist now; a connection whose ports are missing waits.
    connections: {(output port, input port)} to have; pending: [(route, why)] for routes that
    cannot be made now, with a short reason for the status."""
    connections, pending = set(), []
    for route in routes:
        src, dst = bridges.get((route.src, IN)), bridges.get((route.dst, OUT))
        if src is None or dst is None:
            pending.append((route, f"{route.src if src is None else route.dst} is not here"))
            continue
        if route.src in muted.get(IN, ()) or route.dst in muted.get(OUT, ()):
            pending.append((route, "muted"))
            continue
        if route.src_pair > pair_count(src[1]) or route.dst_pair > pair_count(dst[1]):
            pending.append((route, "the device has no such pair"))
            continue
        pairs = [(f"{src[0]}:capture_{s}", f"{dst[0]}:playback_{d}")
                 for s, d in links(pair_channels(route.src_pair, src[1]), pair_channels(route.dst_pair, dst[1]))]
        if all(a in ports and b in ports for a, b in pairs):
            connections.update(pairs)
        else:
            pending.append((route, "starting"))
    return connections, pending


def reconcile(connections, existing, clients):
    """([to connect], [to disconnect]) to bring JACK to `connections`, each as (output port, input port).

    existing: the connected pairs now, as frozensets of two ports (audiod.parse_connections).
    clients: the JACK clients of the bridges. Only a pair between two of them is ours to remove: the
    gadget's connections (system:) are not, and "system" must not be among `clients` while a host is
    attached."""
    wanted_sets = {frozenset(c) for c in connections}

    def ours(pair):
        return all(port.split(":", 1)[0] in clients for port in pair)

    def ordered(pair):   # a bridge's capture port is the output, its playback port the input
        return tuple(sorted(pair, key=lambda port: ":playback_" in port))

    return ([c for c in sorted(connections) if frozenset(c) not in existing],
            sorted(ordered(p) for p in existing if ours(p) and p not in wanted_sets))
