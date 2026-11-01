# MIDI: gadget ports, MIDI pass-through and the control map

When `GADGET_MIDI_PORTS` is greater than 0, the gadget adds a USB MIDI function (`f_midi`) next to the audio. The host sees one device with N MIDI ports in each direction. We call these ports cables. On Linux they are named `rpi-audio MIDI 1` … `rpi-audio MIDI N`. Any USB host understands them, and `rpi-audiod` uses them for two things:

- **MIDI pass-through:** every MIDI port of every USB device plugged into the Pi goes to a cable of its own, in both directions.
- **Control:** one cable carries commands for `rpi-audiod`: assign channels, mute, set levels, set names, and save or load routing presets. Any host can send them. On an MPC, a MIDI track is enough. A DAW or a VST can also read the state back.

Evidence status:
- tested against a Linux laptop: all four cables, pass-through in both directions, SysEx commands and CCs [Pi][laptop];
- on the Force, MPC opens the audio and subscribes to all four cables [Force];
- control from MPC, end to end: CCs sent by MPC (a MIDI track, output `rpi-audio MIDI 1`, channel 16) mute the GP-150 and set its level [Force][Pi] (`docs/hw/2026-10-30-boot-soak.md`, section 7). The CCs entered MPC through MPC Remote, not from a Q-Link or a hardware controller, so the physical Q-Link path is still untested [?]. SysEx from MPC is untested too [?].

Details: `docs/hw/2026-10-30-f4-midi.md`.

**Replies are written to the gadget's raw MIDI output** of the control cable, which `rpi-audiod` keeps open. If that fails, it falls back to `aplaymidi`. Do not use `aseqsend`: a kernel sequencer port only opens its output when something is subscribed to it, and `aseqsend` sends without subscribing [Pi].

**Replies go out in 64-byte pieces, 6 ms apart**, so a 1.5 KB `status` takes about 150 ms. On the Pi's USB controller, a long burst of MIDI to the host delays the audio going to the host. In one go, the panel's replies cost empty audio packets and made the host restart its streams; paced, they cost nothing (`docs/hw/2026-10-30-boot-soak.md`, section 9).

## Gadget

| Setting (`gadget.env`) | Default | What it does |
|---|---|---|
| `GADGET_MIDI_PORTS` | 0 | Cables per direction, from 0 (no MIDI) to 16 |
| `GADGET_MIDI_ID` | `MIDIGadget` | ALSA card id of the MIDI function on the Pi. `rpi-audiod` finds the gadget by it |

- The audio function is linked first, so its interface numbers do not change.
- With MIDI, `bcdDevice` goes from 0x0100 to 0x0101. A host that caches descriptors by VID, PID and revision (Windows) then reads them again.
- On the Pi, cable k is port k−1 of the ALSA sequencer client of the card `GADGET_MIDI_ID`. For that client to exist, `snd-seq` and `snd-seq-midi` must be loaded. `deploy.sh` makes them load at boot.

## Cables

- The control cable is `[midi] control_port` (1 by default).
- **MIDI endpoints:** every sequencer port of a USB sound card is a MIDI endpoint. Its identity is `IDENTITY/P`: the device identity (the same one the audio uses) and the port number, for example `usb-1234:5678-ABC/0`.
- **Assignment:** each endpoint gets a cable other than the control cable, fixed per identity. Assignments are stored in `slots.json` under `"midi"`. They are handed out like audio channels, but one at a time and without pair alignment.
  - An endpoint that comes back gets its cable back.
  - A new endpoint takes the first free cable that has no saved absent endpoint. If there is none, it takes the cable of an absent endpoint. If that fails too, it is parked.
- **With a single cable** (`GADGET_MIDI_PORTS=1`), all endpoints share cable 1 with the control. This is for hosts that only use one cable.
- `rpi-audiod assign IDENTITY/P --midi K` pins a cable. Without `/P`, port 0 is meant.

## Routes

- **When:** only while the gadget is connected to a host (`/sys/class/udc/*/state` is `configured`).
- **How:** kernel sequencer subscriptions (`aconnect`), so they add no user-space latency.
- **Which routes:** for an endpoint on cable k:
  - if the device port is readable (R), the route goes from the device to the gadget, port k−1: the host receives it;
  - if it is writable (W), the route goes from the gadget, port k−1, to the device: whatever the host sends on that cable.
- **Cleanup:** `rpi-audiod` removes the subscriptions between a gadget port and a USB card client that do not match any route of its own, for example after a reassignment. It never touches any others: those of `aseqdump`, of other programs, or the ones you add by hand between devices.

## Control

Everything goes over the control cable, in both directions.

### Text SysEx

```
F0 7D 52 41 <ASCII text> F7      command
F0 7D 52 42 <ASCII text> F7      reply
```

- `7D` is the manufacturer ID for non-commercial use. `52 41` ("RA") tells these messages apart from other uses of `7D`.
- The text may only contain bytes from 0x20 to 0x7E.
- **The reply goes out on the same cable with `52 42` ("RB").** That way, if a host sends the cable back as an echo (for example through MIDI thru), a reply does not re-enter as a command. Its text starts with `ok` or `error: `, or, for `status`, it is JSON starting with `{`.
- **Rate:** up to 20 commands are handled per tenth of a second, and replies go out in order from a separate thread. If more than 20 replies are pending, the new one is dropped.

| Command | Reply | Effect |
|---|---|---|
| `ping` | `ok rpi-audio VERSION`, e.g. `ok rpi-audio 0.1.0 (3c48288)` | — |
| `status` | JSON | The same content as `/run/rpi-audio/status.json`, with `version` |
| `assign IDENTITY [in=N] [out=N] [midi=K]` | `ok` | Pins the first IN channel, the first OUT channel or the MIDI cable. `midi=` without `/P` means `/0` |
| `mute IDENTITY in\|out on\|off` | `ok` | Cuts or restores the audio routes in that direction |
| `volume IDENTITY in\|out PERCENT` | `ok` | The device's own level, 0 to 100: `in` is its capture (what reaches the host) and `out` its playback |
| `name IDENTITY [TEXT]` | `ok` | The device name. Without text, it clears it |
| `name IDENTITY in\|out K [TEXT]` | `ok` | The name of channel K (from 1) of the device in that direction. Without text, it clears it |
| `route SRC DST [src=P] [dst=P]` | `ok` or `error: a device cannot be routed to itself` | Plays what SRC captures into DST's playback: stereo pair P of each (pair 1 is channels 1-2, 1 by default). A mono side is copied to, or summed from, both channels of the other |
| `unroute SRC DST [src=P] [dst=P]` | `ok` | Removes that route; without pairs, every route from SRC to DST |
| `midiroute SRC DST` | `ok` or `error: a device cannot be routed to itself` | Sends what SRC's MIDI port sends into DST's MIDI port. Each end is `IDENTITY` or `IDENTITY/PORT` (port 0 when left out) |
| `midiunroute SRC DST` | `ok` | Removes it; an end without a port is any port of that device |
| `preset save N [TEXT]` | `ok` | Saves the current routing in preset N (1 to 8) |
| `preset load N` | `ok` or `error: preset N is empty` | Restores the routing saved in preset N |
| `preset clear N` | `ok` | Deletes preset N |

Commands change the stored state (`slots.json`, and `presets.json` for presets), exactly like the command line (`rpi-audiod assign|mute|volume|route|unroute|name|preset ...`). The service applies the change within one or two seconds. With an unknown identity, the command is still stored and applied when the device shows up.

### Device routes

- `route` joins two USB devices, with no host involved: what SRC captures is played into DST. It makes JACK connections between their bridges, so it needs the audio engine to be running, and it works next to the host's own channels without touching them.
- A device is never routed to itself: its playback often leaks into its capture, and that would be a loop.
- Several routes may feed one destination (JACK sums them) and one source may feed several. Levels are the devices' own (`volume`), not per route.
- A route whose device is absent, muted or still starting waits and is made when it can be. `mute IDENTITY in` cuts the routes it feeds and `mute IDENTITY out` those that reach it.
- In standalone mode (`docs/STANDALONE.md`) the local DAC is a destination named `local-dac` (settings: `[standalone] identity`): `route usb-mixer local-dac`. It has no capture, no level of its own, and `mute local-dac out on` cuts what reaches it.

### MIDI routes between devices

- `midiroute` joins two USB devices' MIDI ports with no host involved, by a kernel sequencer subscription (`aconnect`), so it adds no user-space latency. The source must be a port that sends (readable) and the destination one that receives (writable). A device is never routed to itself.
- They work in both modes and are stored in `slots.json` under `midi_routes`; presets keep them next to the audio routes.
- A route whose device is absent, or whose port cannot send or receive, waits with the reason in `status` (`midi_routes`, `waiting`) and is made when it can be.
- **Ownership:** in standalone mode (`docs/STANDALONE.md`) every subscription between two USB devices belongs to `rpi-audiod`, so one you add by hand between them is removed within a second. With a host, only the subscriptions `rpi-audiod` made are removed: what you connect by hand stays, as with the gadget's routes.
- Standalone mode also lists the devices' MIDI ports in `status` (`midi_ports`: identity, port, name, and whether it sends and receives), which is what the display's MIDI screens use.

### Names

- `TEXT` is everything after `IDENTITY` (or after `K`), with leading and trailing spaces removed and inner spaces kept. Only bytes from 0x20 to 0x7E.
- **Maximum length:** 24 characters for a device name and 16 for a channel name. A longer one gives `error: ...` and changes nothing.
- **Channel form:** it is recognised when the word after `IDENTITY` is `in` or `out` and the next one is an integer. An integer below 1 is an error. **A device name cannot start with `in N` or `out N`** (with `N` an integer): it would be taken for the channel form. `in` or `out` alone, or followed by something else (`in the mix`), are fine.
- The device name takes priority over the profile name (`name` in `devices.d`), and a channel name over `names_in` / `names_out`, channel by channel.
- Names are not part of presets: loading a preset leaves them as they are.

### Presets

- A preset stores the routing state: the `in`, `out`, `midi`, `mute`, `volume`, `in_channels`, `out_channels` and `routes` keys of `slots.json`. It does not store names.
- `preset save N TEXT` names it (up to 24 characters, same bytes). Without text it keeps the preset's name, or uses `Preset N` if the slot was empty. It also stores the time.
- `preset load N` replaces those keys of `slots.json` with the preset's (keys the preset lacks are removed) and leaves `names` alone. The service re-applies it like any other change: it reassigns channels and MIDI cables, and restores levels and mutes.
- `save`, `load` and `clear` take the same lock as `slots.json` (`slots.lock`), so they are atomic against other writers.

### Program Change

A Program Change on channel `[midi] channel_in` (16 by default) of the control cable is `preset load`: program p, from 0 to 7, loads preset p+1. Any other program is ignored and logged, like a CC with no device. On other channels it does nothing. If CCs are pending in the same cycle, they are applied before the program change. There is no reply: the result is in the log.

### CCs on the control channels

These are for hosts that cannot send SysEx, such as an MPC MIDI track with automation, or Q-Links. They go over the control cable: on `[midi] channel_in` (16 by default) for what goes to the host (IN) and on `channel_out` (15) for what comes from it (OUT).

The CC number selects the device: N is the host channel where the device's block starts in that direction, from 1 to 27. For example, if the GP-150 goes into MPC on IN 3–8, its capture level is CC 35 on channel 16.

| Channel | CC | Effect | Value |
|---|---|---|---|
| `channel_in` (16) | 32 + N (33–59) | Capture level of the device whose IN block starts at N | 0–127 → 0–100 % |
| `channel_in` (16) | 64 + N (65–91) | Mutes its input (IN) | ≥ 64 mutes, < 64 restores |
| `channel_out` (15) | 32 + N (33–59) | Playback level of the device whose OUT block starts at N | 0–127 → 0–100 % |
| `channel_out` (15) | 64 + N (65–91) | Mutes its output (OUT) | ≥ 64 mutes, < 64 restores |

No other CC is a command. That leaves out the channel mode messages (120–127, such as "All Notes Off"), which many hosts send when they stop, and the CCs that often reset things: 0, 1, 7, 10 and 64. A CC in those two ranges that matches no device is ignored and logged. With a single cable, devices also receive these CCs and SysEx messages: a device listening on channels 15 or 16, or in omni mode, will see them.

A SysEx command must fit in about 200 bytes. The sequencer splits long SysEx messages into chunks, and a split command is not recognised. A reply longer than about 4 KB might arrive truncated [?]: the kernel's output buffer for the port is 4 KB. With two devices, `status` takes less than 1 KB, and each audio device adds about 340 bytes, plus any names it has.

**If `status` is over 4000 bytes**, the SysEx reply (not `status.json`, which stays complete) drops diagnostic keys first, one at a time until it fits: `fs_load` of each direction, `usbbus`, `client` of each direction and `card`. It never drops names, levels, mutes, routes or presets. With 6 devices of 6 channels per direction, all with 16-character names, device names and 8 preset names of 16 characters, and 6 MIDI endpoints, the full state is 4616 bytes and the reply is 3962 (`tests/test_usb.py`).

## `status` keys for names and presets

Besides what was already there, `status` (the SysEx reply and `status.json`) carries:

| Key | Where | What it is |
|---|---|---|
| `name` | each device | The device's own name if it has one, otherwise the profile's. Absent if there is none |
| `names` | `in` and `out` of each device | Channel names of the device: a list with as many strings as `channels`, with `""` for unnamed ones. The device's own name takes priority over the profile's, channel by channel. Absent if all are empty |
| `routes` | root | Only when there are device routes: `[{"src": ID, "dst": ID, "src_pair": P, "dst_pair": P, "waiting": WHY}]`. The pairs are left out when they are 1, and `waiting` is `null` when the route is made, otherwise a short reason (`muted`, `starting`, `ID is not here`...) |
| `presets` | root | `[{"slot": N, "name": "...", "saved": "YYYY-MM-DD HH:MM"}]`, only the saved presets, in slot order |

`rpi-audiod status` shows the names (the device's and its channels') and the saved presets.

## Stored state (`/var/lib/rpi-audio/slots.json`)

```json
{
 "in": {"IDENTITY": 3}, "out": {"IDENTITY": 5},
 "in_channels": {"IDENTITY": 6}, "out_channels": {"IDENTITY": 4},
 "midi": {"IDENTITY/0": 2},
 "mute": {"in": ["IDENTITY"], "out": []},
 "volume": {"in": {"IDENTITY": 100}, "out": {"IDENTITY": 80}},
 "routes": [{"src": "IDENTITY", "dst": "IDENTITY2"}, {"src": "IDENTITY", "dst": "IDENTITY3", "src_pair": 2, "dst_pair": 1}],
 "names": {"IDENTITY": {"name": "Desk", "in": {"1": "Voice"}, "out": {"2": "Monitor R"}}}
}
```

- A stored level is applied again every time the device shows up.
- With no stored level, `[bridge] min_volume` applies: if playback starts at 0, it is raised to that level.
- `names` stores, per identity, the device name (`name`) and its channel names (`in` and `out`, with the channel number as a string key). Clearing a name removes its entry, and empty entries are not stored.

## Stored presets (`/var/lib/rpi-audio/presets.json`)

```json
{"1": {"name": "Live", "saved": "2026-10-30 18:05", "state": {"in": {"IDENTITY": 3}, "mute": {"in": [], "out": []}}}}
```

- The key is the slot number, from "1" to "8". `state` holds the routing keys of `slots.json` that existed when it was saved (see Presets).
- It is written like `slots.json`: a temporary file that replaces the previous one, readable by all, under the same lock (`slots.lock`).
