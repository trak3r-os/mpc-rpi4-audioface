# 2026-11-01: modo standalone en la Pi 4 (jackd sobre el pHAT, sin host)

Host: ninguno (la Force parada, el gadget en `not attached`). Pi 4 con el pHAT y el OLED de `2026-11-01-hat-oled.md`. Código en `eb62546` (motor) y `fd5fc20` (rutas MIDI).

## Cómo se probó

Prueba temporal, no instalada: `systemctl stop rpi-audiod` y una unit transitoria (`systemd-run --unit=sa-try`, usuario `rpi-audio`, `LimitRTPRIO=95`, `LimitMEMLOCK=infinity`, `RuntimeDirectory`/`StateDirectory=rpi-audio`) con `RPI_AUDIO_CONFIG=/tmp/sa/rpi-audio.toml`, que es la configuración de `/etc/rpi-audio` más `rpi-audio.d/standalone.toml` (`[engine] mode = "standalone"`). `rpi-audiod.service` sigue en modo host y vuelve solo al reiniciar la Pi. No se ha ejecutado `deploy.sh --host standalone`.

## Resultados

- **jackd [Pi]:** `jackd -R -P 70 -t 2000 -d alsa -d hw:sndrpihifiberry -P -r 48000 -p 256 -n 3 -o 2` arranca sin errores. Formato elegido por ALSA: 32 bit entero. Expone solo `system:playback_1` y `system:playback_2`. `rpi-audiod status` dice `standalone: sndrpihifiberry, 2 ch at 48000 Hz; jackd up`, y el pHAT sale como dispositivo `local-dac` con salida.
- **Mezclador PCM2902 [Pi]:** sus puentes zita arrancan (`codec_in`, `codec_out`, 48 kHz, 256×2) y `jack_lsp -c` muestra `codec_in:capture_N -> system:playback_N`.
- **Ruta mezclador → pHAT [usuario]:** hecha desde la pantalla (`route usb-mixer local-dac`); el usuario dice "funciona", es decir, el mezclador suena por la salida de línea del pHAT. Es también el tono pendiente del pHAT. Nivel, ruido y latencia: no medidos [?].
- **MIDI entre dispositivos:** sin dispositivos MIDI USB enchufados (solo el PCM2902, que no tiene MIDI), `midi_ports` sale `[]` y el bucle de rutas MIDI no da errores (0 en el journal) con la salida real de `aconnect -l`. **Sin probar con dos dispositivos MIDI reales [?].**

## Pendiente

- Enchufar dos dispositivos MIDI USB (por ejemplo un teclado y el Tracker) y probar `midiroute` desde la pantalla.
- Decidir si el modo standalone pasa a ser permanente (`deploy.sh --host standalone`): la Pi dejaría de servir a la Force hasta quitar `/etc/rpi-audio/rpi-audio.d/standalone.toml`.
- El Tracker en "2 OUT / 2 IN": consumo desde la Pi 4, enumeración y si su Master incluye el retorno [?].
