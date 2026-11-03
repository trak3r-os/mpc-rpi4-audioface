# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's names and routing presets (docs/MIDI.md), on the slots.json and presets.json
dicts. The functions edit the dict they get in place: callers pass a copy. Nothing here touches
the system; tests/test_presets.py checks it."""

import copy
import re
import hashlib
import json

NAME_MAX = 24          # a device name or a preset name
CHANNEL_NAME_MAX = 16  # the name of one device channel
SLOTS = 8              # presets 1..8
# What a preset keeps: the gadget slots, mutes, levels, and the audio and MIDI routes between devices.
STATE_KEYS = ("in", "out", "midi", "mute", "volume", "in_channels", "out_channels", "routes", "midi_routes",
              "outputs", "hub_routes_initialized", "names", "output_levels")


def set_name(state, identity, text, side=None, channel=None):
    """Sets, or with empty text clears, the name of a device (side None) or of its channel
    `channel` in direction `side`, in state["names"]; empty entries are removed."""
    names = state.setdefault("names", {})
    entry = names.setdefault(identity, {})
    target, key = (entry, "name") if side is None else (entry.setdefault(side, {}), str(channel))
    if text:
        target[key] = text
    else:
        target.pop(key, None)
    if side is not None and not entry[side]:
        del entry[side]
    if not entry:
        del names[identity]
    if not names:
        del state["names"]


def device_name(profile_name, entry):
    """The custom name of a device (entry is its slots.json "names" entry), else the profile's."""
    return (entry or {}).get("name") or profile_name or ""


def channel_names(profile_names, custom, channels):
    """The names of a direction's device channels: a list of `channels` strings, "" for an
    unnamed one, a custom name ({"K": text}, K from 1) over the profile's. None when all are empty."""
    names = [*profile_names][:channels]
    names += [""] * (channels - len(names))
    for key, text in (custom or {}).items():
        if re.fullmatch(r"\d+", key) and 1 <= int(key) <= channels and text:
            names[int(key) - 1] = text
    return names if any(names) else None


def capture_state(state):
    """A portable setup; empty names are explicit so new snapshots can restore an unnamed setup."""
    saved = copy.deepcopy({k: state[k] for k in STATE_KEYS if k in state})
    saved.setdefault('names', {})
    saved.setdefault('output_levels', {})
    return saved


def mark_active(state, slot):
    state['active_scene'] = {'slot': slot, 'signature': signature(state)}


def signature(state):
    return hashlib.sha256(json.dumps(capture_state(state), sort_keys=True).encode()).hexdigest()


def active_scene(state, store):
    marker = state.get('active_scene')
    if not isinstance(marker, dict) or type(marker.get('slot')) is not int:
        return None
    slot = marker['slot']
    scene = store.get(str(slot))
    return {'slot': slot, 'name': scene.get('name', f'Scene {slot}') if isinstance(scene, dict) else f'Scene {slot}',
            'available': isinstance(scene, dict), 'modified': marker.get('signature') != signature(state)}


def validate_state(saved):
    if not isinstance(saved, dict):
        raise ValueError('saved setup must be an object')
    mappings = ('in', 'out', 'midi', 'mute', 'volume', 'in_channels', 'out_channels', 'names',
                'outputs', 'output_levels')
    if any(key in saved and not isinstance(saved[key], dict) for key in mappings):
        raise ValueError('saved setup contains an invalid mapping')
    for key in ('in_channels', 'out_channels'):
        if any(type(v) is not int or v < 0 for v in saved.get(key, {}).values()):
            raise ValueError('saved setup contains invalid channel counts')
    for entry in saved.get('names', {}).values():
        if not isinstance(entry, dict) or ('name' in entry and not isinstance(entry['name'], str)):
            raise ValueError('saved setup contains invalid names')
        for side in ('in', 'out'):
            if side in entry and (not isinstance(entry[side], dict) or
                                  any(not isinstance(v, str) for v in entry[side].values())):
                raise ValueError('saved setup contains invalid channel names')
    for key in ('routes', 'midi_routes'):
        routes = saved.get(key, [])
        invalid = not isinstance(routes, list)
        if not invalid:
            invalid = any(not isinstance(r, dict) or
                          any(not isinstance(r.get(side), str) for side in ('src', 'dst')) for r in routes)
        if invalid:
            raise ValueError('saved setup contains invalid routes')
        for route in routes:
            if key == 'midi_routes':
                for endpoint in (route['src'], route['dst']):
                    if '/' in endpoint and not endpoint.rpartition('/')[2].isdigit():
                        raise ValueError('saved setup contains an invalid MIDI port')
            for side in ('src_pair', 'dst_pair'):
                if side in route and (type(route[side]) is not int or route[side] < 1):
                    raise ValueError('saved setup contains an invalid channel pair')
    for endpoint in saved.get('midi', {}):
        if '/' in endpoint and not endpoint.rpartition('/')[2].isdigit():
            raise ValueError('saved setup contains an invalid MIDI port')
    if any(type(value) is not int or not 0 <= value <= 100 for value in saved.get('output_levels', {}).values()):
        raise ValueError('saved setup contains invalid output levels')
    for side in ('in', 'out'):
        if not isinstance(saved.get('volume', {}).get(side, {}), dict):
            raise ValueError('saved setup contains invalid device levels')
        if not isinstance(saved.get('mute', {}).get(side, []), list):
            raise ValueError('saved setup contains invalid mutes')


def restore_state(state, saved):
    """Restore setup keys. Legacy scenes without names preserve the current names."""
    validate_state(saved)
    for key in STATE_KEYS:
        if key not in ('names', 'output_levels') or key in saved:
            state.pop(key, None)
    state.update(copy.deepcopy({k: v for k, v in saved.items() if k in STATE_KEYS}))


def save_preset(store, state, slot, text, saved):
    """Puts the routing state in preset `slot` of the presets dict `store`. Without text it keeps
    the slot's name, or is "Preset N" for a new one."""
    old = store.get(str(slot))
    name = text or (old.get("name") if isinstance(old, dict) else "") or f"Preset {slot}"
    store[str(slot)] = {"name": name, "saved": saved,
                        "state": capture_state(state)}


def load_preset(state, store, slot):
    """Replaces the routing keys of state with the preset's (those it lacks are removed);
    legacy scenes preserve names. ValueError when the slot is empty."""
    preset = store.get(str(slot))
    if not isinstance(preset, dict) or not isinstance(preset.get("state"), dict):
        raise ValueError(f"preset {slot} is empty")
    restore_state(state, preset['state'])


def summary(store):
    """[{"slot", "name", "saved"}] for the saved presets, in slot order, for the status."""
    return [{"slot": n, "name": store[str(n)].get("name", ""), "saved": store[str(n)].get("saved", "")}
            for n in range(1, SLOTS + 1) if isinstance(store.get(str(n)), dict)]
