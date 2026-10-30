# 2026-10-29: F2, primer banco de JACK (modo A) con los tres dispositivos

Montaje: la Pi 4 conectada a la Force como gadget (26×26, S16, 44,1 kHz) y, en sus USB-A, el Tracker (8/2, FS), el GP-150 (2/2, HS, 48 kHz) y el mezclador PCM2902 (FS). Detalles en `docs/hw/2026-10-29-f2-usb-devices.md`.

## Instalación [Pi]

- `tools/deploy.sh` instala `jackd2` 1.9.22, `jack-example-tools` y `zita-ajbridge` 0.8.4 si faltan, y se niega a seguir si hay PipeWire instalado.
- **jackd2** hace una pregunta de debconf, `jackd/tweak_rt_limits`, que se escribe con guion bajo; con guion no surte efecto. Respondida con sí, activa `/etc/security/limits.d/audio.conf`: rtprio 95 y memlock ilimitado para el grupo `audio`.
- **Desde JACK 1.9.22**, Debian separa las utilidades (`jack_lsp`, `jack_connect`…) en el paquete `jack-example-tools`.

## Arranque a mano

1. `rpi-audio-keepalive` parado.
2. Luego, con la Force transmitiendo: `jackd -R -P 70 -d alsa -d hw:UAC2Gadget -r 44100 -p 64 -n 3 -S -i 26 -o 26`. ALSA acaba usando 4 periodos.
   - **MPC no notó el cambio** de reproductor (keepalive → jackd): su puntero siguió avanzando sin reiniciarse. [Force]
3. Los puentes, con `-p 128 -n 2`:

| Puente | Dispositivo | Conexiones |
|---|---|---|
| `tracker_in` (zita-a2j, 8 ch, 44,1 kHz) | Tracker | → `system:playback_1..8` (Force IN 1–8) |
| `tracker_out` (zita-j2a, 2 ch) | Tracker | ← `system:capture_3..4` (Force OUT 3/4) |
| `gp150_in` (zita-a2j, 2 ch, 48 kHz) | GP-150 | → `system:playback_9..10` (Force IN 9–10) |
| `gp150_out` (zita-j2a, 2 ch, 48 kHz) | GP-150 | ← `system:capture_5..6` (Force OUT 5/6) y `capture_1..2` (master), para escuchar mientras no esté el pHAT |
| `mixer_in` (zita-a2j, 2 ch, 48 kHz) | Mezclador | → `system:playback_11..12` (Force IN 11–12). Solo en un sentido, por el presupuesto FS |

## Resultados

- **Comprobado de oído por el usuario:** Tracker → Force, guitarra (GP-150) → Force, mezclador → Force y Force → Tracker. [Force]
- **10 minutos con 0 xruns** (de 22:30 a 22:39), con los cinco puentes, aunque el GP-150 se reconectó en medio. [Pi]
- **Carga de JACK, ~18 %** (`jack_cpu_load`) con un periodo de 64 (1,5 ms). [Pi]
- **CPU por proceso** (`ps`), con el zita de Debian, que no usa NEON [Pi]:

  | Proceso | CPU |
  |---|---|
  | jackd | ~6 % |
  | `tracker_in`, 8 canales | ~15 % (unos 2 % por canal remuestreado) |
  | Cada puente de 2 canales | 5–7 % |
  | **Total** | Unos 0,45 núcleos de 4 |

- **Cuando el dispositivo se reconecta, el puente muere [Pi].** El GP-150 se reconectó dos veces en 2 s (al cambiar el usuario su modo USB; por un momento enumeró con MIDI). Después de eso:
  - el proceso zita sigue vivo, pero con el PCM cerrado, y escribe "Starting synchronisation." sin parar;
  - no reabre el dispositivo nuevo;
  - hay que matarlo y relanzarlo, que es justo lo que tiene que hacer el supervisor (`rpi-audiod`).
- **Si se mata un cliente en mitad de un ciclo**, jackd registra xruns ("client was not finished") y una ráfaga de "Process error" hasta que lo da de baja. El supervisor tiene que desconectar el cliente antes de matarlo.
- **El volumen de reproducción USB del GP-150 arranca a 0** (`PCM Playback Volume`, de 0 a 99, con un rango de dB incoherente: de 0 a 0,39 dB). Se puso a 80. Que suene en sus auriculares en el modo "USB legacy" está por confirmar.
- `jackd` y los puentes llevaban `timeout 3600`. A las 23:25 hora local, un trabajo en la Pi pasa la reproducción de vuelta al keepalive.

## Lo que esto le pide a `rpi-audiod` (F2)

- **Arrancar jackd** cuando "Playback Rate" ≠ 0, sustituyendo al keepalive sin hueco apreciable, y devolverle el gadget cuando jackd muera.
- **Vigilar el driver de jackd, no el proceso [Pi][Force].** Al reiniciarse la Force (22:55:59 UTC), el driver ALSA de jackd dio 5 "poll time out" de 2,2 s y paró ("read error, stopping…", 22:56:13), pero **el proceso siguió vivo**, con el gadget abierto y sin reproducir. SIGTERM no lo cerró; SIGKILL sí. Mientras tanto, MPC dio dos veces `capture error -5` (`docs/hw/2026-10-29-force-internal-io.md`). El supervisor tiene que parar jackd cuando "Playback Rate" pase a 0 y volver a lanzarlo cuando el host transmita.
- **Por dispositivo:** lanzar los puentes al aparecer la tarjeta y relanzarlos cuando se reconecte (udev, o comprobar `/proc/asound/<id>/pcm*/sub0/status`). Desconectar los puertos antes de matar un puente.
- **Restaurar las rutas** por identidad estable, no por número de tarjeta: los números cambian al reconectar.
- **Fijar los volúmenes** de cada dispositivo al conectarlo (el GP-150 arranca a 0).
