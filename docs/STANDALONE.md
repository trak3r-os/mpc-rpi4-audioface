# Standalone: rpi-audio with no USB host

With no host on the Pi's USB-C port, rpi-audio can still be a hub: the USB audio devices on its USB-A ports (a mixer, a guitar processor, a tracker...) are bridged to JACK, and a local card, such as a pHAT DAC, is one more destination. What goes where is the same device-to-device routing as in host mode (`route SRC DST`, `docs/MIDI.md`), set from the command line or the display (`docs/DISPLAY.md`).

Host mode is the default and is unchanged. Standalone is chosen in the settings, not switched while running.

## Turning it on

```sh
tools/deploy.sh --enable --hat --host standalone     # or, on the Pi: sudo ./install.sh --hat --host standalone
```

`--hat` sets up the pHAT DAC and the display (`dtoverlay=hifiberry-dac`, I2C; they take effect after a reboot). `--host standalone` installs `/etc/rpi-audio/rpi-audio.d/standalone.toml`, which holds one line, `mode = "standalone"` under `[engine]`. To go back to a host, remove that file and restart `rpi-audiod`. Both modes can use the same Pi: the saved gadget channels (`slots.json`) are never touched in standalone.

The `[standalone]` table of `rpi-audio.toml` names the card and its format (`card`, `channels`, `rate`, `period`, `periods`) and what the card is called in routes (`identity = "local-dac"`, `name = "pHAT DAC"`).

## What it does

- `jackd` starts at once on the card, playback only, at `rate`. There is no host to wait for and no silence to play.
- Every USB audio device gets its zita bridges, as in host mode, but nothing is connected until you ask: no routes, no sound.
- The card appears in `rpi-audiod status` and on the display as a device with an output only. `route usb-mixer local-dac` plays the mixer's capture into it. A route may end in several places at once (the card and another device), and JACK adds what arrives at the same input.
- `mute local-dac out on` cuts what goes into the card. The card has no volume of its own: use each source device's level. (A PCM5102A board has no mixer controls.)
- MIDI: the gadget's MIDI ports do not exist without a host, so the control port and the MIDI mapping are off. Commands come from the command line and the display.
- If `jackd` keeps failing (for example the card is not there yet because the overlay needs a reboot), `rpi-audiod` waits 10 s and tries again.
- `rpi-audiod doctor` skips the USB device controller check and treats the gadget service as optional.

## Power

The Pi's USB-C port is then its power input. The USB-A ports share what the supply gives them (1.2 A in total on a Pi 4 unless the supply is rated for more and `usb_max_current_enable` is set): a device that takes power from the Pi counts against that.
