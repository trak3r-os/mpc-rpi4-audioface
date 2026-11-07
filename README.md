# rpi-audio

[![rpi-audio: a Raspberry Pi 4 routes USB audio and MIDI gear to a pHAT DAC, a 26×26 USB host interface, and stereo RTP or Link Audio network sends](docs/img/rpi-audio-banner.svg)](docs/MANUAL.md)

[![Release CI](https://img.shields.io/github/actions/workflow/status/trak3r-os/mpc-rpi4-audioface/ci.yml?event=release&style=flat-square&logo=github&label=release%20CI)](https://github.com/trak3r-os/mpc-rpi4-audioface/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-60cbb3?style=flat-square)](LICENSE)
[![Last commit](https://img.shields.io/github/last-commit/trak3r-os/mpc-rpi4-audioface?style=flat-square&logo=github)](https://github.com/trak3r-os/mpc-rpi4-audioface/commits/main/)
[![GitHub issues](https://img.shields.io/github/issues/trak3r-os/mpc-rpi4-audioface?style=flat-square&logo=github)](https://github.com/trak3r-os/mpc-rpi4-audioface/issues)
[![GitHub stars](https://img.shields.io/github/stars/trak3r-os/mpc-rpi4-audioface?style=flat-square&logo=github)](https://github.com/trak3r-os/mpc-rpi4-audioface/stargazers)

[![Raspberry Pi 5](https://img.shields.io/badge/Raspberry_Pi-5-C51A4A?style=flat-square&logo=raspberrypi&logoColor=white)](docs/MANUAL.md#16-build-your-own-device)
[![USB Audio Class 2](https://img.shields.io/badge/USB_Audio_Class_2-26_in_%C3%97_26_out-267d9c?style=flat-square)](docs/MANUAL.md#6-record-over-usb)
[![USB MIDI](https://img.shields.io/badge/USB_MIDI-4_virtual_cables-7660ac?style=flat-square)](docs/MIDI.md)
[![RTP / PCM](https://img.shields.io/badge/Network-RTP%2FPCM-087d76?style=flat-square)](docs/MANUAL.md#12-network-audio)
[![Link Audio](https://img.shields.io/badge/Network-Link_Audio-087d76?style=flat-square)](docs/MANUAL.md#ableton-link-audio)
[![English illustrated manual](https://img.shields.io/badge/Guide-English_%C2%B7_illustrated-2563ad?style=flat-square)](docs/MANUAL.md)

**Topics:** [raspberry-pi](https://github.com/topics/raspberry-pi) · [usb-audio](https://github.com/topics/usb-audio) · [midi](https://github.com/topics/midi) · [jack-audio](https://github.com/topics/jack-audio) · [network-audio](https://github.com/topics/network-audio) · [rtp](https://github.com/topics/rtp) · [ableton-link](https://github.com/topics/ableton-link) · [diy](https://github.com/topics/diy)

CI runs only when a GitHub release is published. Pushes, pull requests and draft-release edits do not start it. The Release CI badge tracks release runs.

**A Raspberry Pi 4 that works as a USB audio hub.** Plug your USB sound cards, guitar processors, mixers and MIDI gear into the Pi, and plug the Pi into a computer or a standalone sampler. The host sees one class-compliant USB audio interface, **26 in × 26 out at 44.1 kHz, 16-bit by default**, plus **4 USB MIDI ports**. Each device gets its own channels.

**New to the box?** Start with the [illustrated English user guide](docs/MANUAL.md), readable directly on GitHub. An [HTML edition](docs/manual/index.html) with the same illustrated steps is included for a browser or GitHub Pages; GitHub's file viewer displays HTML source. The guide covers USB recording, standalone pHAT listening, controls, meters, simultaneous outputs, network audio and scenes.

**Building your own?** The [build guide and bill of materials](docs/MANUAL.md#16-build-your-own-device) lists quantities, required and optional parts, power/data connections, GPIO wiring, assembly, installation and first checks. It distinguishes the tested hardware from untested substitutes.

The OLED now opens on Overview and includes connection notices, live peak meters and channel/MIDI mappings. **Hub mode combines pHAT, USB host and network outputs** with a continuous local clock. Install network adapters with `sudo ./install.sh --network`, then select Outputs → Audio mode → Hub. RTP/PCM offers an SDP download at `http://PI-IP:8080/network-rtp.sdp`; Link Audio uses Ableton’s official SDK. Both network outputs start disabled. See [implementation and test limits](docs/OUTPUTS.md) and [project research](docs/NETWORK_RESEARCH.md). Network input and full AES67 are not implemented.

Host profiles can save reservations only, an independent full setup including names, or a link to one of the eight scenes. Use Outputs → Host → Save current as..., or `rpi-audiod host save NAME full`. User profiles survive deployments in hosts.json and local audio-group users can save them without sudo. See the [host-profile steps](docs/MANUAL.md#save-and-choose-a-host-profile).

Profiles now report Ready/Partial/Error with missing-resource details. Outputs offers independent software levels for pHAT, USB-host send, RTP and Link Audio. Status includes session-wide counters and a bounded event history collected while the OLED sleeps, retained across service restarts during the same boot.

![USB audio and MIDI devices connect to a Pi 4, which presents one 26×26 audio interface and four MIDI cables to the host](docs/img/readme-overview.png)

It was built for the Akai Force, which can use only one USB audio interface at a time. Nothing in it is tied to the Force: any host that supports USB Audio Class 2 should work. It has been tested with a Linux laptop and an Akai Force. Anything specific to one host lives in `docs/hosts/` and `tools/hosts/`.

![The rpi-audio Panel inside MPC on an Akai Force: two devices with their channels, levels and mutes, and the 8 routing presets](docs/img/panel-on-force.png)

*The optional rpi-audio Panel inside MPC on an Akai Force. It shows each device plugged into the Pi, its channels on the interface, its levels and mutes, and the 8 routing presets.*

## What it does

- **One interface for many devices.** Every USB audio device on the Pi shows up as a block of channels on the one interface the host sees.
- **Sticky channels.** Each device keeps its block of channels. A device that comes back after a reboot or a re-plug gets the same slot, so your host project keeps working.
- **Names, levels, mutes and presets.** You can name devices and channels, set each device's level, mute it, and save up to 8 routing presets.
- **MIDI goes through too.** The MIDI ports of the devices on the Pi reach the host over the gadget's MIDI cables, in both directions.
- **Control from the host over USB.** One MIDI cable is a control port that takes SysEx text commands, CCs and Program Changes. No network and no app needed.
- **USB budget check.** The Pi's USB-A ports can carry only a few full-speed audio devices at once. `rpi-audiod` works out each device's load before opening it and tells you when one does not fit.
- **Runs without a screen.** Everything starts at boot, and `rpi-audiod doctor` checks the installation.

## How it works

The diagram and clock description below show the original **USB host clock** mode. In **Hub**, JACK instead runs continuously on the local DAC at 48 kHz; separate USB bridges follow the host's rates, and local, USB and network destinations can run together. **Standalone** uses the local clock without the USB audio bridge. See the [mode comparison](docs/MANUAL.md#1-what-the-box-does).

![In host-clock mode, the USB gadget feeds JACK and separate resampling bridges for each audio device; MIDI control reaches rpi-audiod separately](docs/img/readme-architecture.png)

1. **The USB gadget.** The Pi 4's USB-C port can act as a USB *device*. `gadget/` sets up a standard USB Audio Class 2 function and a USB MIDI function through configfs, so the host uses its built-in drivers.
2. **One clock.** JACK runs on the gadget, so the Pi follows the host's sample clock. Each USB device has its own clock, and often its own rate (48 kHz is common). For each device, `rpi-audiod` starts a pair of zita-ajbridge bridges that resample on the fly to keep it in step.
3. **rpi-audiod** watches devices come and go and gives each one its block of gadget channels. It starts and stops the bridges, applies levels and mutes, and saves and loads presets. It also keeps the host fed, with silence if nothing else, because some hosts (the Akai Force) reset when the interface goes quiet while they stream.
4. **MIDI.** Each MIDI port of a device gets a gadget cable of its own, through kernel sequencer connections. Cable 1 goes to `rpi-audiod` as the control port.

The control port is how a host, or the panel shown above, talks to the Pi:

![USB MIDI control sequence: request status, receive devices and levels, mute a device, set its level by CC, and load scene 2 with Program Change 1](docs/img/readme-midi-control.png)

The full protocol is in [docs/MIDI.md](docs/MIDI.md).

## What you need

For the complete DAC/OLED/encoder build, use the [parts list with quantities and assembly instructions](docs/MANUAL.md#16-build-your-own-device). The short list below covers the USB hub itself.

- A **Raspberry Pi 4** with its official power supply. A **Raspberry Pi 5** takes the same SD card and install: the gadget, the pHAT DAC and the OLED come up on it [Pi], but audio with a host and with USB devices has not been measured on a Pi 5 yet.
  - On a Pi 5 whose supply does not negotiate 5 A over USB-PD (a 3 A supply, or any supply behind the splitter), the firmware limits the USB-A ports to 600 mA in total. Power hungry devices then need their own supply or a powered hub.
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

The same controller (a VIA VL805) also **drops packets from full-speed multichannel inputs**. It happens whenever a packet exactly fills the buffer the controller was given for it: a Tracker sending 8 channels lost about one packet in 150. On a Pi 4, `install.sh` therefore installs a small kernel module, `fs_isoc_pad` (`tools/kernel/fs-isoc-pad/`). It adds one byte to the maximum packet size the host uses for those inputs.
- **What changes:** each card behind the VL805 disappears and comes back once when it is plugged in.
- **Install:** the module is built with DKMS, which installs `dkms` and the kernel headers when they are missing and rebuilds it after kernel updates.
- **Measured** [Pi]: 0 lost packets in 10 minutes at 8 and at 10 channels.

Details are in `docs/hw/2026-11-04-pi-usb-host.md`.

The **Pi 5** has no VL805: its USB-A ports hang off two USB host controllers in its RP1 chip, and `rpi-audiod` counts the budget separately for each. The 1099-byte figure was measured on the Pi 4 and has not been checked on a Pi 5. `install.sh` does not install `fs_isoc_pad` there.

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
| `--tune-boot` | Also tunes the boot for audio: `threadirqs` in `cmdline.txt` and `dtparam=audio=off` (the Pi's own analogue audio) in `config.txt`, each with a backup. Only with this option; it takes effect after a reboot |
| `-y` | Does not ask before adding the gadget overlay |

The installer also enables `rpi-audio-cpu.service`, which keeps the CPU governor at `performance` so the audio threads do not wake up on a slowed clock. `sudo systemctl disable --now rpi-audio-cpu` goes back to `ondemand`.

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
   rpi-audiod doctor     # the installation and the Pi: controller, services, governor, power, PipeWire
   rpi-audiod status
   ```

   `doctor` prints one line per check and exits with an error if something is broken. `status` shows the gadget, the connected devices, their channel blocks, levels, names and presets.
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
rpi-audiod doctor                              # check the installation
rpi-audiod --version
rpi-audiod assign IDENTITY --in 3 --out 5      # pin a device's first gadget channels
rpi-audiod mute IDENTITY in on                 # cut a device's audio routes (in|out, on|off)
rpi-audiod volume IDENTITY out 80              # a device's own playback level (in|out, 0-100)
rpi-audiod name IDENTITY Guitar                # name a device
rpi-audiod name IDENTITY in 1 Voice            # name its input channel 1
rpi-audiod preset save 1 Live                  # save the routing as preset 1 (1 to 8)
rpi-audiod preset load 1                       # restore it (also: preset clear N)
```

`IDENTITY` is the device identity shown by `rpi-audiod status`. `IN` is Pi to host, and `OUT` is host to Pi. Channel blocks are sticky: they are kept in `/var/lib/rpi-audio/slots.json`. Presets are in `presets.json` next to it. New presets store routing, channel assignments, MIDI cables, mutes, device/output levels, output switches and custom names. The USB interface stays at 26 channels per direction when scenes change; engine mode and network transport settings remain separate.

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

## Without a host (optional)

The Pi can also run with no host on its USB-C port: the USB devices are bridged to JACK and routed to each other and to a local DAC (a pHAT), set from the command line or from a small OLED with a rotary encoder. It is a setting, not a different program, and host mode stays the default. See [docs/STANDALONE.md](docs/STANDALONE.md) and [docs/DISPLAY.md](docs/DISPLAY.md).

## Akai Force and MPC (optional extras)

These need a modded Force with root SSH access (tested with MockbaMod: a community modification of the Force's system that loads add-ons into MPC). The Pi side works without them. Everything below is installed by you, and not by the Pi installer. Each one is a zip in the format of sd88me's [mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins) catalog, with sd88me's installer, built from this repository. No zips are published yet: build them from source (Docker, g++ and Python 3 with Pillow).

Host notes are in [docs/hosts/akai-force.md](docs/hosts/akai-force.md).

### rpi-audio Panel (control panel for the touchscreen)

A VST2 plugin for MPC that shows the hub on the Force's screen: each device with its channel range, name, level and mute, the 8 presets, and the link state. It makes no sound. The Q-Links control levels. Details: [docs/hosts/akai-force-panel.md](docs/hosts/akai-force-panel.md).

![The panel's name picker: tap a device name and pick a label such as Guitar, Synth, Keys or Mixer](docs/img/panel-name-picker.png)

**Status: tested on an Akai Force (MPC 3.9.1.2, MockbaMod) on 2026-10-30.**
- **What works:** it installs with its installer, loads in MPC, connects to the Pi and shows the devices, names, channel names, levels and presets. MUTE, the name picker, presets and a fader drag all reached `rpi-audiod`.
- **Long runs:** with the panel open, MPC used to restart its streams every few minutes. The panel's status replies went out as 1.5 KB bursts that delayed the gadget's audio on the Pi's USB controller. `rpi-audiod` now sends them in small pieces. In a 20-minute run with the panel open, the Pi did not miss a single audio packet, and MPC restarted its streams once, for a reason not known yet.
- **Not tested yet:** the physical Q-Links, SAVE, "On project load" and reopening a saved project.

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
- **On the very first open after plugging in, MPC may fall back to internal audio once** (it logs `capture error -5`). Select rpi-audio again. The cause is in the kernel's gadget driver: it does not keep the 44,100 frames per second pace until something plays into the gadget, and jackd takes about half a second to start. It is documented in `docs/hw/2026-10-30-boot-soak.md`. An experimental kernel fix is in `tools/kernel/u_audio/`; it is not installed by default.
- **MPC refreshes its list of audio devices only when you open Preferences.** If rpi-audio is missing after a re-plug, leave Preferences and open it again.
- **Do not restart the Pi while MPC is streaming.** Once, a restart took down the Force's whole internal USB hub. Later tests with a gadget shutdown step were clean, but the cause is not isolated. Quit MPC first or stop the gadget first.
- MPC Remote, a tool for driving MPC from a laptop, is described in `docs/hosts/akai-force-remote.md`. It is test tooling, and you do not need it.

## Development

README diagrams are checked-in PNG images so they display without Mermaid support. Regenerate them with `python3 tools/build-readme-diagrams.py` (Pillow and DejaVu Sans fonts; no Pi or network access needed).

Rebuild the guide's HTML and example images with `python3 tools/build-manual.py` (development dependencies: Pillow and Markdown, plus DejaVu Sans fonts). It uses the current OLED renderer and needs no Pi or network access. The generated files in `docs/manual/` are included so readers do not need those packages. HTML embeds its images for a single-file offline guide; Markdown uses the checked-in PNGs. To serve this on GitHub Pages, use `docs` as the published directory and open `/manual/`; Pages hosting is not enabled by this repository change.

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
| `bridge/rpi-audio-ui/` | The OLED and rotary-encoder service: interface, SH1106 driver, input decoding (`docs/DISPLAY.md`) |
| `systemd/` | Service units |
| `config/` | Settings installed to `/etc/rpi-audio/`, and device profiles |
| `tools/` | Inventory, deployment, test tones, MIDI client |
| `tools/hosts/`, `docs/hosts/` | Everything specific to one host |
| `tests/` | pytest for the pure logic |
| `docs/` | Notes: `PLAN.md`, `STATUS.md` and `hw/` (hardware sessions). These lab notes are in Spanish |

Every claim in the docs is tagged with where it comes from: [Pi], [Force], [repo], [code], [ext] (other people's reports), [est] (estimate) or [?] (unknown).

## License

GPL-3.0-or-later (see `LICENSE`). Reused code keeps its own licence, listed in [THIRD_PARTY.md](THIRD_PARTY.md): sd88me's `mpc-vst-plugins` wrapper (MIT) and the Titillium Web font (SIL Open Font License 1.1).
