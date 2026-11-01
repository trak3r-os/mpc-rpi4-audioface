# Display: a small screen and an encoder for rpi-audio

A 128×64 OLED, a rotary encoder with a push button, and two more buttons control rpi-audio without a host: pick a preset, choose which device feeds which, mute, set levels. The display is one more client of the service. It sends the same commands as the command line and the MIDI control port (`docs/MIDI.md`), so the audio never depends on it, and everything keeps working with no display attached.

**Status:** built and running on a Pi 4 with the wiring below (`rpi-audio-ui.service`; lab notes in `docs/hw/2026-11-01-hat-oled.md`). The encoder, PUSH and BACK work. CONFIRM does not reach the Pi yet (a wiring problem on one board, not a software one), and PUSH does its job meanwhile. The terminal simulator `tools/ui-sim.py` needs no hardware.

## Controls

| Input | Does |
|---|---|
| Encoder turn | Moves through a list, or changes a level while editing |
| CONFIRM | Opens a row, toggles a route or a mute, starts a level edit, sets it, loads a preset |
| Encoder push | The same as CONFIRM, except in Presets, where it saves the current routing into the slot (it asks first) |
| BACK | Goes back, drops an edit, answers "no" |

## Screens

Eight rows of 21 characters (a 5×7 font in 6×8-pixel cells), the first row a title. The display goes dark after `idle_s` seconds without input, and the first touch only wakes it.

- **Presets:** the eight slots. CONFIRM loads one; push saves into it.
- **Routes:** first a destination (every stereo pair of every device with a playback), then the sources that can feed it, as `[ ]` and `[x]`. `[~]` is a route that waits for a device or for USB bandwidth. A device is never offered to itself.
- **Devices:** each device's `In` (what it sends) and `Out` (what it receives) mute and level. A `~` marks a device waiting for USB bandwidth.

A change shows as made at once and is confirmed when the service's status catches up (within a couple of seconds).

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
| CONFIRM | 16 (GPIO 23) | `ButtonPinSelect` |
| BACK | 18 (GPIO 24) | `ButtonPinBack` |

The OLED is an **SH1106**, 128×64, at I2C address **0x3C** (`SH1106LCDI2CAddress=0x3C` in the same file), not an SSD1306. The pHAT DAC is on I2S (`SoundDevice=i2s`) and uses GPIO 18, 19 and 21, so there is no conflict. Its header is soldered from below: the wires go to the pads on top. Enabling I2C and the pHAT needs `dtparam=i2c_arm=on` and `dtoverlay=hifiberry-dac` in the boot config and a reboot.

## The service

`rpi-audio-ui.service` reads `/run/rpi-audio/status.json` twice a second (a file older than ten seconds counts as no service: the last row then says so) and runs each command through `rpi-audiod cmd TEXT`. With no display or no GPIO it waits and tries again every five seconds, and the audio is untouched. `install.sh --hat` (or `tools/deploy.sh --enable --hat`) enables it and installs `python3-smbus2` and `python3-libgpiod`; without `--hat` its files are installed but it does not run.

Settings go in the `[ui]` table of `/etc/rpi-audio/rpi-audio.toml` or a file in `rpi-audio.d/` (all optional):

| Key | Default | |
|---|---|---|
| `bus` | 1 | I2C bus of the OLED |
| `address` | 0x3C | 0x3D on some boards |
| `flip` | false | turns the picture 180° |
| `contrast` | 127 | 0 to 255 |
| `idle_s` | 60 | seconds before the display goes dark; 0 never |
| `invert_encoder` | false | for a knob that turns the wrong way |
| `pins` | the table above | BCM numbers, only the ones that differ: `pins = { confirm = 5 }` |

A key that is unknown or has a wrong value is logged and ignored. Clockwise is the encoder's A line (TRA) changing before B, as on a KY-040; swap with `invert_encoder` if yours is wired the other way.
