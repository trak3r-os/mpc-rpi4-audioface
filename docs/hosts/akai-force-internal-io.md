# Akai Force: keeping its own audio I/O next to rpi-audio

MPC uses a single audio device at a time. When that device is the Pi, the Force switches off its inputs, outputs and headphones (`docs/hosts/akai-force.md`). **mpc_internal_io** is a MockbaMod add-on that MPC loads with `LD_PRELOAD`. While MPC uses the rpi-audio gadget, the add-on:

- **copies** some of MPC's outputs to the Force's own codec, ADA2. By default the master (1/2) goes to the codec's outputs 1/2 and 3/4;
- **replaces** some of MPC's inputs with the codec's inputs. By default MPC inputs 25/26 are the Force's two inputs. On the Pi those two channels are left free.

MPC goes on seeing a single 26-channel interface: its channels are not touched, and neither are its hw_params.

The code is in `tools/hosts/akai-force-internal-io/`.

## How it works

- **Interception:** it intercepts `snd_pcm_open`, `close`, `hw_params`, `prepare`, `recover`, `readi` and `writei`, and exports nothing else.
  - It recognises the gadget by its card id (`rpiaudio`), never by the name MPC uses to open it.
  - When MPC configures the gadget, the add-on opens ADA2 non-blocking: S32_LE, 44.1 kHz, period 64, buffer 1024.
- **Inside MPC's audio thread:** all the work happens in MPC's own `readi`/`writei` calls on the gadget, and nothing blocks.
  - **Playback:** after each write, it keeps ADA2's queue at `queue` frames.
  - **Capture:** after each read, it takes everything ADA2 has captured and fills the mapped channels.
- **Two clocks [Force]:** ADA2 runs 31.7 ppm slower than the gadget, roughly 1.4 frames per second.
  - Each direction goes through `mio_core`: an elastic buffer with a 16-tap polyphase windowed-sinc resampler.
  - A loop steers the ratio from the buffer fill plus ADA2's queue.
- **Simulation results (`make test`) [est]** (on the Force, see "First test" below):
  - ratio within 0.1–0.2 ppm of the true value;
  - smoothed fill within 12 frames of its target;
  - noise plus distortion at −101 dB;
  - flutter of ~27 ppm (0.003 %, inaudible);
  - no underflows or overflows, including a 164-frame jump of the gadget.
- **Resynchronisation:** every `prepare`/`recover` of MPC on the gadget, and every ADA2 xrun, restart ADA2 with silence. The ratio is kept.
- **Releasing ADA2:** it is released when MPC closes the gadget. That way MPC can go back to its internal audio, which is otherwise exclusive (`hw`, no dmix).
- **Failures:** if ADA2 can't be opened or configured, that direction passes MPC's audio through untouched.
- **Log:** to stderr, which ends up in MPC's journal (`[mpc_internal_io] …`), with a status line every ~30 s. It writes no files. The lines go through a small queue to a thread of its own at normal priority, so MPC's audio thread never writes to the journal (that write can block); a line that finds the queue busy or full is dropped and counted. What is queued when MPC exits is written then. Checked on the laptop, natively in Docker, with `aplay` on an internal card as the gadget and the `null` PCM as the codec [repo]; not yet on the Force.
- **Codec restarts** (`drop`, `prepare`, a write of silence, `start`) still run in MPC's audio thread: they are ioctls on a non-blocking PCM and happen only after an xrun or MPC's own `prepare`.

## Settings

The settings live in `mpc_internal_io.conf`, next to the `.so`: `/data/mpc-addins/rpi-audio-internal-io/` when it is installed from the addin zip, `AddOns/mpcInternalIO/` on MockbaMod's card with the script. Each one can be overridden with `MIO_<KEY>`. The defaults:

| Key | Default | What it does |
|---|---|---|
| `playback` | `1:1, 2:2, 1:3, 2:4` | MPC output → codec output (1-based) |
| `capture` | `25:1, 26:2` | MPC input ← codec input |
| `gain_db` | `-12` | Gain on the way to the codec: the Force's volume knob does nothing while MPC is on an external device |
| `period`, `buffer`, `queue`, `ring` | 64, 1024, 256, 256 | Codec periods and frames in flight (latency of roughly 6–12 ms per direction) |
| `off` | 0 | 1 = loads, but touches nothing |

## Build

```sh
make -C tools/hosts/akai-force-internal-io test        # core test, on the laptop
tools/hosts/akai-force-internal-io/build.sh            # armhf .so in Docker (Debian bookworm), with ABI checks
tools/hosts/akai-force-internal-io/package.sh 1.0.0    # dist/rpi-audio-Internal-IO-1.0.0-mpc-armv7.zip
```

`package.sh` packages it as an addin in sd88me's format, with sd88me's `release_addin.py` and shared addin installer
(vendored unmodified in `tools/hosts/vendor/mpc-vst-plugins/`, see `docs/ADDINS.md` in sd88me/mpc-vst-plugins), and checks
the zip with their `catalog_check.py`. The build is reproducible: the `.so` built on 2026-10-30 is byte for byte the one
running on the Force since 2026-10-29.

## Install from the addin zip

```sh
scp -r rpi-audio-Internal-IO-1.0.0 root@force.local:/tmp/                # the unzipped folder
ssh root@force.local sh /tmp/rpi-audio-Internal-IO-1.0.0/install.sh      # copies it, adds it to LD_PRELOAD, restarts MPC
ssh root@force.local sh /data/mpc-addins/rpi-audio-internal-io/uninstall.sh   # to remove it
```

The installer puts the add-on in `/data/mpc-addins/rpi-audio-internal-io/` and adds the `.so` to MPC's `LD_PRELOAD`
without dropping what is already there. On a MockbaMod card it also writes `AddOns/run_rpi-audio-internal-io.sh`, so
MockbaMod's own list gets it too. Your `mpc_internal_io.conf` is kept on upgrade and deleted on uninstall.

- **If you used the MockbaMod script below before,** run its `install.sh disable` first and restart the Force.
  Otherwise MPC loads the library twice.
- **Tested in a simulation only [repo]:** install and uninstall against a scratch systemd tree and a fake MockbaMod card
  with sd88me's test setup (BusyBox). The hook armed the list and kept the other entries; uninstall left it as it was.
  It has not been installed this way on the Force. sd88me's MockbaMod hook adds the library once, under a lock file;
  the races described below were seen with MockbaMod's own scripts, which take no lock. If MPC starts without its
  control surface after a boot, go back to the script.

## Install with the MockbaMod script (Force only)

```sh
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-internal-io/install.sh enable    # then restart the Force
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-internal-io/install.sh status
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-internal-io/install.sh conf FILE # replace the settings; MPC reads them at start
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-internal-io/install.sh disable   # then restart the Force
```

- `install.sh` writes only under `/media/662522`, MockbaMod's SD card. That is the single exception to "read-only on the host" in `CLAUDE.md`, and it is never used while a test is running.
- MockbaMod rebuilds the `LD_PRELOAD` list in RAM (`/dev/shm/.LD_PRELOAD`) at every boot. So `disable` plus a restart leaves MPC as it was.
- **MockbaMod's add-on scripts race [Force].** `boot.sh` starts every `AddOns/*.sh` in the background, and each one rewrites the list without a lock.
  - Run in parallel, they can garble it. On the first test boot, MidiLoop's library got a broken path and MPC lost its control surface.
  - A fixed delay didn't work either: on one boot the script started late and MPC read the list without it.
  - So `run_mpcInternalIO.sh` writes as soon as it starts, then checks the list every 0.1 s for 5 s. It rewrites the list only when it's missing something or has a broken path, keeping only paths that exist, every library it has seen in the list, and no duplicates.
  - In a local BusyBox test with random start delays: 0 broken paths in 100 races, the add-on always present, and an entry the others dropped among themselves still missing in 6. That race is MockbaMod's and predates this add-on.
  - **Our own rewrites can drop another script's entry too.** On 2026-10-30, after a second script of ours was added (MPC Remote, `docs/hosts/akai-force-remote.md`), MPC first started without MidiLoop's library [Force]. MockbaMod's `midicheck` restarted it 15 s later, and the second start was fine.
    - So, from 0.3 s on, both scripts also put back the library of every enabled add-on, read from the `LD_LIB=` line of each `AddOns/run_*.sh`, at the end of the list.
    - BusyBox test with MockbaMod's three scripts plus our two, 150 boots: a library was missing at 1 s in 7 boots before the change (MidiLoop's in 3), and in 0 after it [est].
- The build:
  - is a 32-bit ARM `.so`, EABI5 hard-float;
  - needs only `libasound.so.2`, `libm` and `libc`;
  - uses glibc symbols up to 2.34 (the Force has 2.39).

## First test on the Force (2026-10-29)

Session log: `docs/hw/2026-10-29-force-internal-io.md`.

- **It works [Force]:**
  - MPC opens rpi-audio at 26×26, S16, period 128;
  - the add-on opens ADA2 in both directions;
  - the user hears MPC's master on the main outputs and on the headphones;
  - a source on the Force's inputs arrives on MPC input 25&26.
- **Drift [Force]:** the ratios settle within ~90 s, at +30 to +35 ppm for playback and −31 to −32 ppm for capture.
  - The buffers stay on target, with no codec xruns, underflows or overflows.
  - This holds only while the Pi plays into the gadget. When it didn't, MPC kept restarting the stream, the ratios ran to ±1000 ppm and MPC ended with `capture error -5`.
- **Releasing the codec [Force]:** when MPC dropped the gadget after an error, the add-on closed ADA2 and MPC took its internal audio back without trouble.
- **Settled:** ADA2 does make sound while MPC is on an external device, and the hooks work with the `libasound` MPC loads.

## Still unknown

- [?] **Which codec outputs are which:** main outputs and headphones. The master goes to both pairs.
- [?] Whether −12 dB is a good level.
- [?] Long-run behaviour: no soak yet.
- [?] Why MPC no longer opens rpi-audio by itself at boot. It didn't in four boots, one of them without the add-on loaded and with the keepalive ready, so the add-on isn't the cause. MPC doesn't keep the device in `MPC.settings`. For now, select rpi-audio by hand after each boot.

## Test plan

1. Do it with no test running and with rpi-audio working (keepalive or JACK on the Pi).
2. `install.sh enable`, then restart the Force.
3. Check with `install.sh status`:
   - the `.so` appears in MPC's memory map;
   - the log shows "loaded", "MPC opened the gadget" and "codec … open".
4. Check the following:
   - MPC keeps streaming to the Pi without errors (`akai-force-watch.sh`, `gadget-watch.sh`);
   - MPC's master is heard on the Force's outputs and headphones, at −12 dB;
   - a source on the Force's inputs shows up in an MPC track with input 25&26;
   - after one minute, the status lines show a ratio of about +31.7 ppm (playback) and −31.7 ppm (capture), with no xruns or underflows.
5. If anything goes wrong: `install.sh disable` and restart.
