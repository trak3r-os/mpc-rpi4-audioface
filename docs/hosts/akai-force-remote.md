# Akai Force: MPC Remote, for driving MPC from here

**This is test tooling.** You do not need it to use rpi-audio. We use it so that rpi-audio tests that need someone at the Force can run remotely.

[MPC Remote](https://github.com/jacob-sabella/mpc-addin-remote) (MIT licence, by jacob-sabella, listed in sd88me's catalog) is an add-in that MPC loads with `LD_PRELOAD`. It serves MPC's screen in a browser and an MCP server. We use it for tests such as picking rpi-audio after each boot, building test tracks, or looking at the screen. The user authorised this on 2026-10-30 (`CLAUDE.md`, exception 2).

Our own code is in `tools/hosts/akai-force-remote/`.

## Installation

- **Version:** 1.0.3, pinned by its sha256 in `install.sh`. v1.1.0 has no published binary.
  - The library needs glibc 2.17 or later, `libc`, `libdl` and `libpthread`.
  - It only exports `mpc_remote_addin_start`, so it does not intercept ALSA functions and does not clash with MidiLoop or `mpc_internal_io` [code].
- **Its own installer is not used**, because it writes to `/data`, to `/etc` and to the system root. `install.sh enable` copies the `.so` and its configuration to `AddOns/mpcRemote/` on the MockbaMod SD card, together with `run_mpcRemote.sh`, the same way our add-on is installed. The add-in reads its settings next to the `.so`.
- **Configuration:** the default one, with `bind=127.0.0.1` and port 6720. **It has no password.** Reach it only through an SSH tunnel, and never open it to the network.

```sh
tools/hosts/akai-force-remote/install.sh fetch                    # downloads and checks the pinned version into out/
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-remote/install.sh enable    # then restart the Force
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-remote/install.sh tunnel    # localhost:6720, in the foreground
tools/hosts/akai-force-remote/mcp.py --list                       # the MCP tools
tools/hosts/akai-force-remote/mcp.py screenshot '{"zoom": 0.5}'   # screenshot to out/mpc-screen.png
```

`mcp.py` is a minimal MCP client that uses only the standard library, so the server does not need to be registered in an MCP client. If you prefer that, open the tunnel and run `claude mcp add --transport http mpc http://localhost:6720/mcp`.

## What was seen on the Force (2026-10-30)

- **Loading [Force]:** after a restart it loaded, and `/info` answers: 1280×800 screen, XR24, and the touchscreen on `/dev/input/event0`.
- **Buttons [Force]:**
  - button presses go to MockbaMod's `Virtual RawMIDI` (client 133), which the add-in finds by itself;
  - MENU opens the menu, although it does nothing in the project selector shown at boot.
- **Operation [Force]:**
  - a dropdown field with a red border opens with `double_tap`; a single tap does nothing;
  - this is how rpi-audio was picked in Preferences → Audio Device: MENU, PREFERENCES (1094, 720), AUDIO DEVICE (166, 420), a double tap on the field and the first line of the list. MPC opened the gadget at 26×26 and the add-on opened the codec.
- **Boot [Force]:** the first MPC boot after installing it came up without MidiLoop, and MockbaMod's `midicheck` restarted it after 15 s. This was the race on the `LD_PRELOAD` list between the add-ons' scripts, not the add-in itself. See `docs/hw/2026-10-30-f4-midi.md`.

## Removing it

Run `install.sh disable` and restart the Force. The `AddOns/mpcRemote/` folder stays, inactive.
