# Display: a small screen and an encoder for rpi-audio

A 128×64 OLED, a rotary encoder with a push button, and two more buttons control rpi-audio without a host: pick a preset, choose which device feeds which, mute, set levels. The display is one more client of the service. It sends the same commands as the command line and the MIDI control port (`docs/MIDI.md`), so the audio never depends on it, and everything keeps working with no display attached.

For a new assembly, start with the [bill of materials and illustrated build steps](MANUAL.md#16-build-your-own-device). They cover the complete Pi/DAC/panel, power/data splitter, GPIO wiring and first-start checks. This page documents the display implementation and configurable pins.

**Status:** running on a Pi 4 with the wiring below (`rpi-audio-ui.service`). The encoder, PUSH and BACK were checked physically. The earlier GPIO 23 CONFIRM wiring did not deliver a reliable press; the default is now GPIO 5, with physical confirmation still pending. PUSH and CONFIRM now perform the same action throughout, including scene saving and loading. See the [illustrated user guide](MANUAL.md) for step-by-step use and [current session notes](hw/2026-11-03-oled-wifi.md) for validation. The terminal simulator `tools/ui-sim.py` needs no hardware.

## Controls

The service opens on **Overview**. Press or turn the encoder to open the menu; BACK from that menu returns to Overview.

| Input | Does |
|---|---|
| Encoder turn | Moves through a list, or changes a level while editing |
| CONFIRM | Opens a row, toggles a route or a mute, starts a level edit, sets it, loads a preset |
| Encoder push | The same as CONFIRM throughout the interface |
| BACK | Goes back, drops an edit, answers "no" |

Brief notices announce device, WiFi and USB-host connections and disconnections. They last three seconds, keep the connection bar visible, and disappear on input. They wake the display, with no phantom notices for devices already present at startup. A device held back by USB bandwidth or channel allocation gets a notice; its Connections details explain the reason.

The last main-menu item, **Power**, offers **Shut down** and **Restart**. Each opens a confirmation with **Cancel** selected: turn to the requested action and press PUSH or CONFIRM. BACK cancels. Once accepted, repeated input cannot queue another action. If the request fails, the error remains visible and BACK returns to the confirmation. These are local panel actions, separate from the USB/MIDI daemon commands; the terminal simulator does not execute them.

Shut down stops the system cleanly; wait for the Pi to finish halting before unplugging. The OLED going dark alone is not proof of completion: the UI stops before all shutdown work ends, and normal sleep also blanks it. Restart reboots Linux with the saved configuration intact; keep the supply connected.

## Screens

Eight rows of 21 characters (a 5×7 font in 6×8-pixel cells): a title, six content rows, and connection indicators. The home menu has no title, so its list starts on the top row and shows seven items; other screens use white titles on black. A small arrow marks the selection without flashing a whole white row, and long lists show their position beside the title. Messages use the row above the connection indicators, with the list adjusting to keep the selected item visible. The display goes dark after `idle_s` seconds without input, and the first touch only wakes it.

The bottom bar updates every two seconds, with three icons:

| Icon | Meaning |
|---|---|
| WiFi | Signal percentage when connected; `OFF` when disabled, `--` when disconnected, `N/A` when absent, `?` when unknown |
| Device | Number of physical audio/MIDI devices, including the local pHAT DAC; multiple MIDI ports count as one device. The Pi's HDMI, headphones and USB gadget are excluded |
| USB | `OFF`: disconnected; `IDLE`: host connected, no audio stream; `LIVE`: audio bridge running; `WAIT`: connecting or waiting for audio; `SIL`: sending silence; `SUSP`: host suspended; `LOC`: standalone mode; `?`: unknown |

These indicators are hidden while the screensaver runs, so they do not leave fixed pixels lit on an idle OLED. A connected USB cable alone does not produce `LIVE`.

- **Overview:** USB-bridge or standalone mode, sample rate, physical-device count, active audio-route groups and MIDI routes/ports, and two compact peak meters. In host mode, IN measures what goes to the host and OUT what comes from it, taking the highest peak across the gadget channels. In Hub/Standalone, IN measures capture bridges and OUT the local mix plus enabled Hub outputs. `--` means unavailable, `-inf` means digital silence, and `CLIP` means a peak at or above 0 dBFS. The bars cover -60 to 0 dBFS.

  Meters read real JACK samples through passive input taps, without opening ALSA devices or changing existing routes. A native C callback collects peaks; Python reads its output without blocking and draws at most five frames per second. The helper never starts JACK and runs only while Overview is visible and awake. Closing the view, entering the screensaver, or losing JACK stops the helper; stale samples become unavailable. The UI unit permits realtime scheduling and memory locking for the native JACK thread; the Python/GPIO loop keeps normal priority. `install.sh --hat` installs the compiler and JACK headers and builds `rpi-audio-meter`. Later updates rebuild an already installed helper as well.

- **Send audio:** first the source stereo pair, then destinations as `[ ]`, `[x]` or waiting `[~]`. **More output pairs...** offers individual destination pairs. A device is not offered to itself.
- **Outputs:** pHAT DAC, USB host, Network RTP and Link Audio, each with a state, enable switch, independent output Level and details. Host offers reservations-only profiles, full setup copies and scene links; Save current as generates a free host-N name. Use this profile, scene changes, overwrites and deletion have explicit actions and confirmations. Audio mode selects Hub, USB host clock or Standalone DAC and confirms the interruption.
- **Scenes:** eight slots, each with visible Load and Save here actions; saving asks before replacing the slot.
- **MIDI:** choose a sender, then select receivers. The local list is available in Hub/Standalone; original host mode continues using gadget MIDI cable mapping.
- **Levels & mute:** physical devices' In/Out mute and available hardware levels. `~` marks a bridge waiting for USB bandwidth.

- **Connections:** USB-host and WiFi details, then a list of the physical audio/MIDI devices, available even when audio is idle. Select a device to see its mode, bus, bridge state, input/output channels, active rates, MIDI capability, assigned USB channel ranges and MIDI cables. Saved assignments are explicitly marked `saved` while idle; standalone mode uses local routing instead. Scroll to the lower rows for mappings and failure reasons. Prefixes: `A+M` audio and MIDI, `I/O` full-duplex audio, `IN` capture only, `OUT` playback only, `MID` MIDI only, `LOC` local DAC. In Hub, To USB and From USB show explicit selected routes instead of claiming the old reservations are connected. USB details show the engine mode (USB bridge, Hub or Standalone), connection state, sample rate and gadget channels. WiFi details show the connection, network name, IP and signal. These screens are read-only; use Levels & mute, Send audio or MIDI to change routing and levels.

- **Status:** Machine & buffers shows CPU/RAM bars, temperature, rate, buffers and DSP data. All inputs and All outputs show separate real peak bars and endpoint details. Profile readiness reports Ready/Partial/Error with reasons. Session counters and Recent events use the independent always-on JACK observer and retain history through service restarts during this boot.

- **Settings:** the display's own settings. CONFIRM steps a row to its next value and wraps round. A change applies at once and is kept across restarts.

  | Row | Values |
  |---|---|
  | Sleep | never, 15 s, 30 s, 1, 2, 5 or 10 min without input before the display goes dark (`idle_s`) |
  | Saver | off, 10, 20, 30 or 60 s, 2 or 5 min without input before the screensaver (`saver_s`) |
  | Style | `bounce` (moving name), `clock` (moving time) or `status` (machine and buffer panels) (`saver_style`) |
  | Bright | 10, 25, 50, 75 or 100 % (`contrast`) |
  | Flip | turns the picture 180° (`flip`) |
  | Encoder | normal or reversed (`invert_encoder`) |

  The screensaver dims the display and moves its picture one cell every 3 s, so no pixel stays lit. The first touch only ends it, like waking a dark display. If Sleep is shorter than Saver, the display goes dark first. The clock is the Pi's own (set the time zone with `timedatectl`).

A change to a level, a mute or a route shows as made at once and is confirmed when the service's status catches up (within a couple of seconds). A button that runs a command shows `working...` above the connection bar until it is done. Commands run in order in a worker. A separate worker owns all OLED I²C operations, including wake, settings and recovery. It keeps only the latest frame, so slow transfers cannot queue old screens or block the encoder. Only the changed columns of changed OLED pages are transferred; moving between short menu labels normally changes just two four-byte arrow spans. Input decoding uses the kernel's edge times so queued button releases are not mistaken for bounce. Failed transfers retry after 10 ms, increasing to a 50 ms cap, without switching the OLED off/on. A failed page is fully resent to repair partial writes; a removed adapter or invalid descriptor is reopened. Recovery times, slow transfers and input-loop stalls are logged separately in `journalctl -u rpi-audio-ui`.

Output and endpoint lists put names first and align states on the right. Host-profile type, selection (`*`) and availability marks also sit on the right. Long selected names and titles pause for about 1.4 seconds, then scroll within their own space; state labels and the connection bar stay fixed. Short names remain static. Detail headers use shorter labels such as Session, Machine and Profile state when space is limited.

The main output-level editor uses a double-size percentage above its bar. Turn to adjust, press to save, or BACK to cancel. The destination name remains visible above the value.

Overview's last line identifies the active scene, or the host profile when no scene has been selected. After a scene is loaded or saved, its selection survives restarts. A leading `*` before its name means the saved setup fields have changed since that operation; reverting those changes clears the mark. The Scenes list marks the active slot `live` or `*edit`. Existing setups gain a scene identity the next time you load or save one; they are not guessed from similar settings.

Audio meters attack immediately, release at 18 dB/s, retain the peak marker for 0.8 s and latch CLIP for 1.5 s. Missing/stale data still becomes `--` immediately. Editing uses a pencil icon; command progress, success and failure use hourglass, tick and cross icons. Successful save messages clear after two seconds, while failures remain until input. A success means the command was stored; the actual adapter state remains visible separately.

The source-first workflow is implemented: Send audio and MIDI choose a sender, then destinations. Outputs controls each adapter and Audio mode. Scenes offers explicit Load and Save here actions; PUSH and CONFIRM do the same thing. See the [illustrated manual](MANUAL.md) and [output implementation](OUTPUTS.md).

## Wiring (a 9-pin encoder board with an I2C OLED, and a Pimoroni pHAT DAC)

The pins are the ones the same board used with MiniDexed on a Raspberry Pi 3B, read from the `minidexed.ini` on its SD card (`EncoderPin*`, `ButtonPin*`; BCM numbers). The 3B and the 4B share the 40-pin header.

| Board pin | Raspberry Pi pin | MiniDexed setting |
|---|---|---|
| VCC | 1 (3.3 V; not 5 V: the buttons may be pulled up to VCC) | |
| GND | 6 | |
| SDA | 3 (GPIO 2) | I2C bus 1 |
| SCL | 5 (GPIO 3) | I2C bus 1 |
| TRA | 11 (GPIO 17) | `EncoderPinClock` (the board's TRA/TRB order is a guess: swapping them only reverses the turning direction) |
| TRB | 13 (GPIO 27) | `EncoderPinData` |
| PUSH | 15 (GPIO 22) | `EncoderPinButton` |
| CONFIRM | 29 (GPIO 5) | `ButtonPinSelect` (MiniDexed used GPIO 23, pin 16) |
| BACK | 31 (GPIO 6) | `ButtonPinBack` (MiniDexed used GPIO 24, pin 18) |

The OLED is an **SH1106**, 128×64, at I2C address **0x3C** (`SH1106LCDI2CAddress=0x3C` in the same file), not an SSD1306. The pHAT DAC is on I2S (`SoundDevice=i2s`) and uses GPIO 18, 19 and 21, so there is no conflict. Its header is soldered from below: the wires go to the pads on top. Enabling I2C and the pHAT needs `dtparam=i2c_arm=on` and `dtoverlay=hifiberry-dac` in the boot config and a reboot.

## The service

`rpi-audio-ui.service` reads `/run/rpi-audio/status.json` twice a second (a file older than ten seconds counts as no service: the row above the connection bar then says so) and runs each command through `rpi-audiod cmd TEXT`. A separate background worker reads NetworkManager's connection information (`nmcli`, without rescanning), the USB controller state in sysfs and physical audio/MIDI cards in `/proc/asound` every two seconds. These reads do not block the encoder or depend on commands finishing. Missing GPIO is retried every five seconds; the display worker retries I²C independently. `install.sh --hat` (or `tools/deploy.sh --enable --hat`) enables it and installs `python3-smbus2` and `python3-libgpiod`; without `--hat` its files are installed but it does not run. For Python-only UI updates on an installed Pi, `tools/deploy.sh --ui-only` backs up and updates the display service and restarts it if running, preserving the audio service, configuration and boot settings.

Settings go in the `[ui]` table of `/etc/rpi-audio/rpi-audio.toml` or a file in `rpi-audio.d/` (all optional):

| Key | Default | |
|---|---|---|
| `bus` | 1 | I2C bus of the OLED |
| `address` | 0x3C | 0x3D on some boards |
| `flip` | false | turns the picture 180° |
| `contrast` | 127 | 0 to 255 |
| `idle_s` | 60 | seconds before the display goes dark; 0 never |
| `saver_s` | 30 | seconds before the screensaver; 0 never |
| `saver_style` | `"bounce"` | `"bounce"`, `"clock"` or `"status"` |
| `invert_encoder` | false | for a knob that turns the wrong way |
| `pins` | the table above | BCM numbers, only the ones that differ: `pins = { confirm = 23 }` |

What the Settings screen keeps goes in `/var/lib/rpi-audio-ui/settings.json` and wins over the file; delete it to go back to the file's values. A key that is unknown or has a wrong value is logged and ignored. Clockwise is the encoder's A line (TRA) changing before B, as on a KY-040; swap with `invert_encoder` if yours is wired the other way.

The `status` screensaver rotates machine, buffer and audio-summary panels every six seconds and moves them on both axes, without a fixed footer. Metrics come from the background `/proc`/sysfs snapshot and passive JACK helper. Active Status views also report JACK rate, period, DSP load while the separate session observer collects xrun notifications even with the OLED asleep. Separate endpoint meters are bounded to 64 groups and 128 taps; unavailable measurements show `--`. The first touch wakes the display; Sleep still applies.
