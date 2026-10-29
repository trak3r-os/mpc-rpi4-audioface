# Estado: 2026-10-29 (noche)

**Fase:** F1 cumplida con la Force a 26×26 S16: canales en orden, 30 minutos de ida y vuelta sin cortes y los dos órdenes de arranque probados, **siempre que la Pi esté reproduciendo** (`rpi-audio-keepalive`). Quedan pruebas opcionales: auriculares y S32.

## Hecho

- **Repo:** `git init` (rama `main`, **sin commits**), `LICENSE` (GPL-3.0-or-later), `CLAUDE.md`, `.gitignore` (`out/`), `.flake8`.
- **Documentación:** `docs/PLAN.md` v2, `docs/hosts/akai-force.md` y las sesiones `docs/hw/2026-10-29-force-baseline.md`, `docs/hw/2026-10-29-f1-laptop.md` y `docs/hw/2026-10-29-f1-force.md`.
- **La Pi:**
  - sudo sin contraseña para `no3z`;
  - alimentación por el splitter (fuente → POWER, DATA POWER → Pi, USB2 DATA → host), `throttled=0x0`;
  - red por Ethernet en 192.168.1.106. La Pi 4 no tiene Wi-Fi configurada. Ojo: 192.168.2.154 es **otra** placa, una Pi 2 (`raspberrypi2`).
- **Gadget:**
  - `rpi-audio-gadget` instalado con `tools/deploy.sh`. La unit está **activa pero no habilitada** al arranque (`deploy.sh --enable` cuando toque);
  - configuración actual: **26×26, 44100, S16, bint 2**, req 4, async.
- **Pruebas contra el portátil** (detalle en `docs/hw/2026-10-29-f1-laptop.md`), todas bit-transparentes:
  - **16×16 S32**: soak de 10 minutos en dúplex, OK;
  - **26×26 S16**: soak de 10 minutos en dúplex, OK, sin xruns;
  - **26×26 S32** (bint 1) solo aguanta con los procesos de la Pi en tiempo real, porque el buffer del gadget es de unos 14 ms.
- **Pruebas contra la Force** (detalle en `docs/hw/2026-10-29-f1-force.md`):
  - la enumera a High-Speed. MPC la abre a **26/26, S16, periodo 128**;
  - ida y vuelta a través de una pista de MPC con monitorización: orden de canales correcto en los dos sentidos y en los dos extremos (1–2 y 25–26); **10 y 30 minutos con 0 cortes (aceptación de F1 cumplida)**; ±1 LSB por la conversión de MPC;
  - 25 minutos de streaming sin errores de MPC mientras la Pi reproducía;
  - **arranque:** con la Pi encendida antes o a la vez, MPC abre rpi-audio solo al arrancar. Si la Pi desaparece con MPC en marcha (desconexión o reinicio de la Pi), MPC da error y hay que volver a elegirla en Preferences. La Pi está lista a los ~7 s de arrancar el kernel.
- **Investigación de la Force (MPC 3.9.1.2)** por otra sesión: ALSA, hilos, ADA2 y relojes, add-ons y proyectos, en `docs/hosts/akai-force.md`. Pendiente: medir la deriva entre ADA2 y el gadget.
- **Herramientas, todas usadas contra el hardware real:**
  - `pi-facts.sh`;
  - `deploy.sh`;
  - `soak.sh`: dúplex, `tonecheck` en los dos sentidos y tasa de interrupciones del dwc2;
  - `tonegen.py` y `tonecheck.py`: 12 tests con pytest, silencio inicial y final tolerado;
  - `hosts/akai-force-probe.sh`;
  - `gadget-watch.sh`: estado del UDC, ritmos, interrupciones y registros del dwc2 en la Pi. Con `PLAY=26:S16_LE`, reproduce en el gadget mientras el host transmite;
  - `hosts/akai-force-watch.sh`: estado y punteros de los streams de MPC, en solo lectura;
  - **`rpi-audio-keepalive.service`** (instalado, activo y habilitado al arranque, igual que `rpi-audio-gadget`): reproduce en el gadget mientras el host transmite, con FIFO 70 y un usuario dinámico. `KEEPALIVE_SOURCE=tones` durante F1, `silence` para el uso normal.

## Hechos que conviene recordar

- **No hay debug dinámico en el kernel:** los cortes se miden con `tonecheck`. [Pi]
- **La Pi solo puede reproducir cuando el host ya está transmitiendo**; si no, `aplay` falla con `Input/output error`. [Pi]
- **Con la Force, la Pi tiene que estar reproduciendo en el gadget siempre que el host transmite**, aunque sea silencio. Si no, el gadget envía 44.000 tramas/s en vez de 44.100, y MPC se reinicia o da "UNEXPECTED AUDIO ERROR" (`capture error -5`) y vuelve a su audio interno. Además, **MPC no tolera que el IN y el OUT vayan a ritmos distintos**: con −0,1 % en "Playback Pitch" reinicia cada ~3,6 s. Lo resuelve `rpi-audio-keepalive.service`. [Pi][Force]
- **Hay una actualización del bootloader disponible.** No se ha tocado: decisión del usuario. Leer la versión del VL805 necesita sudo (ya disponible). [Pi]
- **El splitter es el "USB-C/PWR Splitter" de 8086** (8086.net/p/usbcs). Según la tabla del fabricante [ext]:
  - **USB2 DATA** lleva D+, D−, masa y 5,1 kΩ en CC, pero **no VBUS**. Ni la Pi alimenta al host ni el host a la Pi.
  - **DATA POWER** lleva 5 V, D±, y 10 kΩ a 5 V en CC.
  - **POWER** lleva 5 V y 5,1 kΩ en CC.
  - **"5V"** es el jack de barril, que no se usa.

  Consecuencias:
  - el gadget debe declararse autoalimentado, y ya lo hace (`bmAttributes 0xC0`);
  - la Pi siempre ve VBUS (el de su fuente), así que **no puede detectar por VBUS que el host se ha ido**. El motor tiene que fiarse de "Capture/Playback Rate", no del estado del UDC;
  - Pi y host comparten masa, lo que puede dar lazos de masa en las salidas analógicas (el pHAT DAC).

## Siguiente

1. **Terminar F1 con la Force** (`docs/PLAN.md` F1, punto 3):
   - comprobar que los auriculares de la Force se apagan al elegir rpi-audio;
   - opcional: S32 con bint 1 (más bits para el GP-150), con la Pi en tiempo real.
2. Pasar `KEEPALIVE_SOURCE` a `silence` cuando acaben las pruebas con tonos, para no meter tonos en las entradas de la Force durante el uso normal.
3. F1b (32 canales y parche de `u_audio` para el IN en reposo) o F2 (motor), a decidir.

Durante las pruebas con la Force, `rpi-audio-keepalive` tiene que estar activo. Si se para, la Force acaba dando error y hay que volver a elegir rpi-audio en sus preferencias. `gadget-watch.sh` sin `PLAY` sirve para observar; con `PLAY` choca con el keepalive.

## Pruebas de tonos

- **En dúplex, lo normal:** `tools/soak.sh CANALES SEGUNDOS`.
- **Un solo sentido:** los comandos de abajo. El host (el portátil, tarjeta `rpiaudio`) abre primero; la tarjeta de la Pi es `UAC2Gadget`.

```sh
# Pi -> host
arecord -D hw:CARD=rpiaudio -t raw -f S32_LE -c C -r 44100 -d 40 | tools/tonecheck.py -c C --expect-order - &
sleep 1; ssh no3z@192.168.1.106 '/usr/local/lib/rpi-audio/tonegen.py -c C -s 30 | aplay -q -D hw:CARD=UAC2Gadget -t raw -f S32_LE -c C -r 44100'

# host -> Pi
tools/tonegen.py -c C -s 40 | aplay -q -D hw:CARD=rpiaudio -t raw -f S32_LE -c C -r 44100 &
sleep 2; ssh no3z@192.168.1.106 'arecord -q -D hw:CARD=UAC2Gadget -t raw -f S32_LE -c C -r 44100 -d 30' | tools/tonecheck.py -c C --expect-order -
```

`OK` significa orden correcto y 0 cortes. Nunca mezcles texto (por ejemplo, la salida de `amixer`) en la tubería de audio.
