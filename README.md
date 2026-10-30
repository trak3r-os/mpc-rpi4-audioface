# rpi-audio

A Raspberry Pi 4 that works as a USB audio hub.

To the computer or sampler it is plugged into (the host), the Pi looks like one USB audio interface: **26 in × 26 out at 44.1 kHz, 16-bit by default**, plus **4 USB MIDI ports**. Behind it, the Pi takes the USB audio and MIDI devices you plug into its USB-A ports and bridges them into that one interface.

- Each device gets its own block of channels, and keeps it. A device that comes back after a reboot or a re-plug gets the same slot.
- You can name devices and channels, set each device's level, mute it, and save routing presets.
- The host can control all of this over USB MIDI, so nothing needs a network.

rpi-audio is generic. It has been tested with a Linux laptop and an Akai Force as hosts. The Force is the first host we tried, not a requirement. Anything specific to one host lives in `docs/hosts/` and `tools/hosts/`.

## What you need

- A **Raspberry Pi 4** with its official power supply.
- A **USB-C data/power splitter**. We use the "USB-C/PWR Splitter" from 8086 (8086.net/p/usbcs). The Pi 4 has only one USB-C port, and it is both its power input and its gadget (device-mode) port. The splitter lets you feed power from the supply and send data to the host over separate connectors. Wiring we used: supply to POWER, DATA POWER to the Pi, USB2 DATA to the host.
- The USB audio and MIDI devices, on the Pi's **USB-A** ports.
- A host with a USB port. Connect the Pi directly, not through a hub.

### The full-speed USB budget

The Pi 4's USB-A ports share one controller with a limited budget for periodic (isochronous) traffic from **full-speed** devices. We measured the controller accepting 1099 bytes per frame and refusing about 1270 [Pi].

| Device type | Cost | In practice |
|---|---|---|
| High-speed (most modern interfaces, e.g. the Valeton GP-150) | 0 | Does not count against the budget |
| Full-speed, stereo (cheap USB sound cards, mixers with a PCM2902) | about 200–400 bytes per frame | About one medium device fits on a Pi 4 |
| Full-speed with many channels (e.g. a Tracker in "10 OUT / 2 IN") | over 1000 bytes | Does not fit next to anything else |

`rpi-audiod` works out each full-speed device's load before opening it. If it does not fit, the device waits and `rpi-audiod status` says why. Details are in `docs/PLAN.md`.

## Install on the Pi

Use Raspberry Pi OS, 64-bit. The tested system is Debian 13 (trixie) with kernel 6.18. The Pi does not need PipeWire: rpi-audio uses JACK.

```sh
git clone https://github.com/trak3r-os/mpc-rpi4-audioface.git
cd mpc-rpi4-audioface
sudo ./install.sh                  # gadget + rpi-audiod, started at boot
sudo ./install.sh --host akai-force   # the same, with the Akai Force profile
sudo reboot                        # only if the installer enabled the USB gadget overlay
```

Run only one of the two `install.sh` lines. Use `--host akai-force` if the host is an Akai Force, and the plain line otherwise.

| Option | What it does |
|---|---|
| `--host NAME` | Also installs the profile for that host from `tools/hosts/` |
| `--no-enable` | Does not change what starts at boot |
| `--force-config` | Overwrites `/etc/rpi-audio/*`. By default existing files are kept, and the new versions are written next to them as `*.new` |
| `--no-boot-config` | Does not add `dtoverlay=dwc2,dr_mode=peripheral` to the boot configuration |
| `-y` | Does not ask for confirmation |

To update, run `git pull && sudo ./install.sh`. To remove it, run `sudo ./install.sh --uninstall`. Add `--purge` to also delete the settings and the saved state.

The gadget is created once at boot by `rpi-audio-gadget.service`. Do not unbind and rebind it in a loop: repeated rebinds can lock up the Pi's USB controller.

### Gadget settings

`/etc/rpi-audio/gadget.env` sets the interface the host sees. After changing it, run `sudo systemctl restart rpi-audio-gadget` once.

| Setting | Default | Meaning |
|---|---|---|
| `GADGET_CHANNELS` | 26 | Channels in each direction |
| `GADGET_SRATE` | 44100 | Sample rate. The Akai Force only accepts 44100 |
| `GADGET_SSIZE` | 2 | Bytes per sample (2 = 16-bit) |
| `GADGET_MIDI_PORTS` | 4 | USB MIDI ports per direction. 0 turns MIDI off |
| `GADGET_PRODUCT` | `rpi-audio` | Name the host shows |

Never put "UAC2_Gadget" in the product name: MPC ignores cards with that name.

## Connect a host and check

1. Plug the splitter's data side into the host.
2. On the Pi, run:

   ```sh
   rpi-audiod status
   ```

   It shows the gadget, the connected devices, their channel blocks, levels, names and presets.
3. On the host, look for an audio interface and MIDI ports called **rpi-audio**.

What has been tested:

| Host | Result |
|---|---|
| Linux laptop | 26×26 at 16-bit: bit-exact tones in both directions; 10-minute duplex soak with no xruns; USB MIDI, SysEx and CC control |
| Akai Force | MPC opens it at 26×26, 16-bit. 60-minute duplex soak with 0 xruns and 0 underflows, and MIDI control from an MPC track |
| macOS | Not tested |
| Windows | Not tested. Windows' class driver (`usbaudio2.sys`) is documented to limit shared mode to 8 channels, so expect to need exclusive mode or ASIO, or a lower channel count |

The Akai Force needs the Pi to be playing into the gadget whenever the host streams, even silence. Otherwise MPC resets or drops back to its internal audio. `rpi-audiod` does this for you, so run it (it starts at boot).

## Everyday use

### Command line

Run these on the Pi as root, or as the service user (`sudo -u rpi-audio rpi-audiod ...`).

```sh
rpi-audiod status                              # what the service is doing
rpi-audiod assign IDENTITY --in 3 --out 5      # pin a device's first gadget channels
rpi-audiod mute IDENTITY in on                 # cut a device's audio routes (in|out, on|off)
rpi-audiod volume IDENTITY out 80              # a device's own playback level (in|out, 0-100)
rpi-audiod name IDENTITY Guitar                # name a device
rpi-audiod name IDENTITY in 1 Voice            # name its input channel 1
rpi-audiod preset save 1 Live                  # save the routing as preset 1 (1 to 8)
rpi-audiod preset load 1                       # restore it (also: preset clear N)
```

`IDENTITY` is the device identity shown by `rpi-audiod status`. `IN` is Pi to host, and `OUT` is host to Pi. Channel blocks are sticky: they are kept in `/var/lib/rpi-audio/slots.json`. Presets are in `presets.json` next to it. A preset stores routing (channels, MIDI cables, mutes, levels), not names.

### Device profiles

A profile gives a known device a display name, a preferred sample rate or channel position, and channel names. Put one device per file in `/etc/rpi-audio/devices.d/*.toml`. Examples are in `config/devices.d/`, and the format is described at the end of `config/rpi-audio.toml`.

Global settings are in `/etc/rpi-audio/rpi-audio.toml`. Files in `/etc/rpi-audio/rpi-audio.d/*.toml` override it, table by table.

### Control from the host over USB MIDI

One of the gadget's MIDI cables (cable 1 by default) is the control port. From any host you can:

- send **SysEx text commands** (`ping`, `status`, `assign`, `mute`, `volume`, `name`, `preset ...`) and read the replies;
- send **CCs** on channels 16 (what goes to the host) and 15 (what comes from it) to set levels (CC 32 + N) and mutes (CC 64 + N);
- send a **Program Change** 0–7 on channel 16 to load presets 1–8.

On a Linux host, `tools/midictl.py status` sends a command and prints the reply. The other cables carry the MIDI of the devices plugged into the Pi, in both directions. The full protocol is in [docs/MIDI.md](docs/MIDI.md).

Tested: SysEx and CCs from a Linux laptop, and CCs from an MPC track. Not tested: SysEx from MPC, and the Force's physical Q-Links.

## Akai Force and MPC (optional extras)

These need a modded Force with root SSH access (tested with MockbaMod: a community modification of the Force's system that loads add-ons into MPC). The Pi side works without them. Everything below is installed by you, and not by the Pi installer. Each one is a zip in the format of sd88me's [mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins) catalog, with sd88me's installer, built from this repository. No zips are published yet: build them from source (Docker, g++ and Python 3 with Pillow).

Host notes are in [docs/hosts/akai-force.md](docs/hosts/akai-force.md).

### rpi-audio Panel (control panel for the touchscreen)

A VST2 plugin for MPC that shows the hub on the Force's screen: each device with its channel range, name, level and mute, the 8 presets, and the link state. It makes no sound. The Q-Links control levels. Details: [docs/hosts/akai-force-panel.md](docs/hosts/akai-force-panel.md).

**Status: tested on an Akai Force (MPC 3.9.1.2, MockbaMod) on 2026-10-30.** It installs with its installer, loads in MPC, connects to the Pi and shows the devices, names, channel names, levels and presets. MUTE, the name picker, presets and a fader drag all reached `rpi-audiod`, and it was retested the same day on sd88me's current wrapper. Not tested yet: the physical Q-Links, SAVE, "On project load", reopening a saved project, and a long run: once, after 20 minutes with the panel open, MPC dropped rpi-audio with `capture error -5`, cause not known yet.

Build it, copy the folder to the Force and run its installer as root. Save your MPC project first, because the installer restarts MPC.

```sh
cd tools/hosts/akai-force-panel
./build.sh all && ./package.sh     # tests, armhf build, then dist/rpi-audio-Panel-1.0.0/ and its zip
scp -r dist/rpi-audio-Panel-1.0.0 root@force.local:/tmp/
ssh root@force.local sh /tmp/rpi-audio-Panel-1.0.0/install.sh -y -t /media/AKAI_SSD/Synths
```

Then add **rpi-audio Panel** to a track from the instrument browser.

### mpc_internal_io (keep the Force's own inputs and outputs)

MPC uses one audio device at a time. When it uses the Pi, the Force switches off its own inputs, outputs and headphones. This add-on gives them back: while MPC uses rpi-audio, it copies MPC's master to the Force's own outputs and headphones, and feeds the Force's two inputs to MPC inputs 25 and 26. Details: [docs/hosts/akai-force-internal-io.md](docs/hosts/akai-force-internal-io.md).

**Status:** installed and working on one Force, with the output routing still to be confirmed by ear. No long soak yet.

Use `--host akai-force` when installing on the Pi. That reserves gadget channels IN 25–26 for the add-on. Save your MPC project first, because the installer restarts MPC.

```sh
cd tools/hosts/akai-force-internal-io
./build.sh && ./package.sh 1.0.0    # armhf .so in Docker, then dist/rpi-audio-Internal-IO-1.0.0-mpc-armv7.zip
cd dist && unzip rpi-audio-Internal-IO-1.0.0-mpc-armv7.zip
scp -r rpi-audio-Internal-IO-1.0.0 root@force.local:/tmp/
ssh root@force.local sh /tmp/rpi-audio-Internal-IO-1.0.0/install.sh
```

To remove it: `ssh root@force.local sh /data/mpc-addins/rpi-audio-internal-io/uninstall.sh`. This installer has only been tried in a simulation so far; on the test Force the add-on was installed with a MockbaMod-only script, described with the settings in the add-on's doc.

### Known MPC behaviour

- **MPC does not remember the USB audio device across reboots.** It saves "Internal" even when you pick rpi-audio. After each boot, reselect it in **Preferences > Audio Device**.
- **On the very first open after plugging in, MPC may fall back to internal audio once** (it logs `capture error -5`). Select rpi-audio again. The cause is in the kernel's gadget driver: it does not keep the 44,100 frames per second pace until something plays into the gadget, and jackd takes about half a second to start. It is documented in `docs/hw/2026-10-30-boot-soak.md`.
- **Do not restart the Pi while MPC is streaming.** Once, a restart took down the Force's whole internal USB hub. Later tests with a gadget shutdown step were clean, but the cause is not isolated. Quit MPC first or stop the gadget first.
- MPC Remote, a tool for driving MPC from a laptop, is described in `docs/hosts/akai-force-remote.md`. It is test tooling, and you do not need it.

## Development

Deploy to a Pi from another machine (the Pi needs SSH and passwordless sudo):

```sh
PI_HOST=user@pi-address tools/deploy.sh
```

Run the tests:

```sh
python3 -m pytest -q tests
```

| Path | What is there |
|---|---|
| `gadget/` | The USB gadget, built through configfs |
| `bridge/rpi-audiod/` | The service: devices, channel slots, routing, USB budget, MIDI |
| `systemd/` | Service units |
| `config/` | Settings installed to `/etc/rpi-audio/`, and device profiles |
| `tools/` | Inventory, deployment, test tones, MIDI client |
| `tools/hosts/`, `docs/hosts/` | Everything specific to one host |
| `tests/` | pytest for the pure logic |
| `docs/` | Notes: `PLAN.md`, `STATUS.md` and `hw/` (hardware sessions). These lab notes are in Spanish |

Every claim in the docs is tagged with where it comes from: [Pi], [Force], [repo], [code], [ext] (other people's reports), [est] (estimate) or [?] (unknown).

## License

GPL-3.0-or-later (see `LICENSE`). Reused code keeps its own licence, listed in [THIRD_PARTY.md](THIRD_PARTY.md): sd88me's `mpc-vst-plugins` wrapper (MIT) and the Titillium Web font (SIL Open Font License 1.1).
