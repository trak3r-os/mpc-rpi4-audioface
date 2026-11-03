# SPDX-License-Identifier: GPL-3.0-or-later
"""Output identities, validated network configuration and migration of legacy host mappings."""

import ipaddress

USB = "usb-host"
RTP = "network-rtp"
LINK = "network-link"
IDS = ("local-dac", USB, RTP, LINK)


def enabled(state, identity, default=True):
    value = state.get("outputs", {}).get(identity, default)
    return value if isinstance(value, bool) else default


LEVEL_CLIENTS = {'local-dac': 'level_dac_out', USB: 'level_usb_out',
                 RTP: 'level_rtp_out', LINK: 'level_link_out'}


def level(state, identity):
    value = state.get('output_levels', {}).get(identity, 100)
    return value if type(value) is int and 0 <= value <= 100 else 100


def network(table):
    address = str(table.get("address", "239.69.1.1"))
    address = str(ipaddress.IPv4Address(address))
    port = table.get("port", 5004)
    ttl = table.get("ttl", 1)
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65534 or port % 2:
        raise ValueError("[network] port must be an even integer from 1024 to 65534")
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 32:
        raise ValueError("[network] ttl must be 1..32")
    http_port = table.get("http_port", 8080)
    if isinstance(http_port, bool) or not isinstance(http_port, int) or http_port and not 1024 <= http_port <= 65535:
        raise ValueError("[network] http_port must be 0 (off) or 1024..65535")
    return {"address": address, "port": port, "ttl": ttl, "http_port": http_port}


def migrate_host_routes(state):
    """One-time preservation of legacy USB routing. Future routes are explicit and removable."""
    if state.get("hub_routes_initialized"):
        return state
    import routing
    for side in ("in", "out"):
        for identity, start in state.get(side, {}).items():
            size = state.get(side + "_channels", {}).get(identity, 0)
            if not isinstance(start, int) or not isinstance(size, int) or start < 1 or start % 2 == 0:
                continue
            for pair in range(1, (size + 1) // 2 + 1):
                host_pair = (start + 1) // 2 + pair - 1
                if side == "in":
                    route = routing.Route(identity, USB, pair, host_pair)
                else:
                    route = routing.Route(USB, identity, host_pair, pair)
                routing.add(state, route)
    state["hub_routes_initialized"] = True
    return state
