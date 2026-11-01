# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's names and routing presets (docs/MIDI.md), on the slots.json and presets.json
dicts. The functions edit the dict they get in place: callers pass a copy. Nothing here touches
the system; tests/test_presets.py checks it."""

import copy
import re

NAME_MAX = 24          # a device name or a preset name
CHANNEL_NAME_MAX = 16  # the name of one device channel
SLOTS = 8              # presets 1..8
# What a preset keeps: the gadget slots, mutes, levels, and the audio and MIDI routes between devices.
STATE_KEYS = ("in", "out", "midi", "mute", "volume", "in_channels", "out_channels", "routes", "midi_routes")


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


def save_preset(store, state, slot, text, saved):
    """Puts the routing state in preset `slot` of the presets dict `store`. Without text it keeps
    the slot's name, or is "Preset N" for a new one."""
    old = store.get(str(slot))
    name = text or (old.get("name") if isinstance(old, dict) else "") or f"Preset {slot}"
    store[str(slot)] = {"name": name, "saved": saved,
                        "state": copy.deepcopy({k: state[k] for k in STATE_KEYS if k in state})}


def load_preset(state, store, slot):
    """Replaces the routing keys of state with the preset's (those it lacks are removed);
    the names stay. ValueError when the slot is empty."""
    preset = store.get(str(slot))
    if not isinstance(preset, dict) or not isinstance(preset.get("state"), dict):
        raise ValueError(f"preset {slot} is empty")
    for key in STATE_KEYS:
        state.pop(key, None)
    state.update(copy.deepcopy({k: v for k, v in preset["state"].items() if k in STATE_KEYS}))


def summary(store):
    """[{"slot", "name", "saved"}] for the saved presets, in slot order, for the status."""
    return [{"slot": n, "name": store[str(n)].get("name", ""), "saved": store[str(n)].get("saved", "")}
            for n in range(1, SLOTS + 1) if isinstance(store.get(str(n)), dict)]
