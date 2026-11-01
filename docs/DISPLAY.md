# Display: a small screen and an encoder for rpi-audio

A 128×64 OLED, a rotary encoder with a push button, and two more buttons control rpi-audio without a host: pick a preset, choose which device feeds which, mute, set levels. The display is one more client of the service. It sends the same commands as the command line and the MIDI control port (`docs/MIDI.md`), so the audio never depends on it, and everything keeps working with no display attached.

**Status:** the interface logic and a terminal simulator exist (`bridge/rpi-audio-ui/ui.py`, `tools/ui-sim.py`, `tests/test_ui.py`). The display driver, the service unit and the wiring below are not built or tried on hardware yet.

## Controls

| Input | Does |
|---|---|
| Encoder turn | Moves through a list, or changes a level while editing |
| CONFIRM | Opens a row, toggles a route or a mute, starts a level edit, sets it, loads a preset |
| Encoder push | In Presets: saves the current routing into the slot (it asks first). In a level edit: sets it |
| BACK | Goes back, drops an edit, answers "no" |

## Screens

Eight rows of sixteen characters, the first one a title.

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
