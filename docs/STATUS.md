# Estado: 2026-10-30 (21:15)

**Fase:** F1 cumplida con la Force a 26×26 S16, **siempre que la Pi esté reproduciendo**. F2 en marcha:

- banco de JACK con dispositivos USB reales: `docs/hw/2026-10-29-f2-jack-bench.md` y `docs/hw/2026-10-29-f2-usb-devices.md`;
- **add-on de la Force** que le devuelve su audio interno junto a rpi-audio. Funciona e **instalado**: `docs/hw/2026-10-29-force-internal-io.md`;
- **`rpi-audiod` v1** (`bridge/rpi-audiod/`):
  - jackd ligado al stream del host, puentes zita por tarjeta USB y canales fijos por dispositivo;
  - presupuesto Full-Speed comprobado antes de abrir cada sentido, y perfiles opcionales en `config/devices.d/`;
  - **habilitado al arranque**: el gadget y `rpi-audiod` están arriba a los ~9 s;
  - **soak de 60 minutos con la Force: 0 xruns y 0 underflows**: `docs/hw/2026-10-30-rpi-audiod.md` y `docs/hw/2026-10-30-boot-soak.md`.

  Falta que el usuario lo confirme de oído, y probar el presupuesto con el Tracker.

F4 en marcha: **USB MIDI en el gadget** (4 puertos), MIDI de paso por dispositivo y mapa de control (SysEx de texto y CC), según `docs/MIDI.md`. Probado contra el portátil, y en la Force MPC abre el audio y se suscribe a los 4 puertos: `docs/hw/2026-10-30-f4-midi.md`.

## Estado ahora mismo

- **Causa de los paquetes vacíos encontrada y arreglada** (`docs/hw/2026-10-30-boot-soak.md`, sección 9): las respuestas SysEx de `rpi-audiod` salían de una vez y retrasaban el audio isócrono en el `dwc2`.
  - Ahora salen en trozos de 64 B cada 6 ms.
  - Con el panel abierto, 20 minutos sin un solo vacío de la Pi y un reinicio de MPC en 20 min, que no parece venir de la Pi.
  - `threadirqs` no hace falta.
- **Matriz de soaks acabada** (`docs/hw/2026-10-30-boot-soak.md`, sección 9):
  - el governor `performance` baja los paquetes IN vacíos de ~3–6 a ~1 por minuto, y los rearranques de MPC de uno cada pocos minutos a uno cada 10–20 minutos. Queda habilitado (`rpi-audio-cpu`);
  - `req_number` 8 no ayuda: vuelve a 4;
  - el `u_audio` parcheado no cambia los vacíos y está cargado hasta el próximo reinicio.
  - Lo siguiente serían `threadirqs` con afinidad de la IRQ del `dwc2`, o su DMA por descriptores. Tocan el arranque: necesitan el OK del usuario.
  - El incidente de los reenlaces del agente se arregló reiniciando la Pi (17:30). MPC refresca su lista de dispositivos al salir de Preferences y volver a entrar.
- **Reinicio de la Pi con la Force conectada:** el 2026-10-30 un reinicio con MPC transmitiendo tiró una vez todo el hub USB interno de la Force (`usb2-port1: disabled by hub (EMI?)`) y desmontó en sucio la SD de MockbaMod y AKAI_SSD. Con la mitigación de `rpi-audio-gadget down` (1f7a421), la parada del gadget y un reinicio completo con MPC transmitiendo salieron limpios (dos pruebas, con el SSD expulsado). La causa no está aislada; si vuelve a pasar, hay que reponer la regla. `docs/hw/2026-10-30-boot-soak.md`.
- **La Force:** `mpc_internal_io` está instalado en la SD de MockbaMod y se carga en cada arranque. La versión con el hilo de log (sin `fprintf` en el hilo de audio) se copió a la SD el 2026-10-31 (md5 26cc36ad): entra en el próximo reinicio de la Force. Hasta entonces sigue la anterior, que está en memoria. El `.conf` de la prueba de salidas se conservó.
  - **Ajustes temporales de la prueba de salidas:** MPC Out 1/2 → códec 1/2 y Out 3/4 → códec 3/4. Al acabar, volver a `mpc_internal_io.conf` del repo con `install.sh conf` y reiniciar la Force.
  - MPC arranca con su audio interno: hay que elegir rpi-audio tras cada arranque, a mano o con MPC Remote. MPC guarda "Internal" aunque se elija rpi-audio [Force] (`docs/hw/2026-10-30-boot-soak.md`, sección 5).
  - La carrera de `LD_PRELOAD` está arreglada en un arranque real: MidiLoop carga, 0 errores ACVX y el `midicheck` no reinicia MPC.
  - **Discos:** AKAI_SSD da limpio con `fsck.exfat -n`, pero sigue con la marca de sucio. La SD de MockbaMod dice 15,6 GB y el lector de la Force solo ve 4 GB: no hay que pasar de ~3,7 GB usados (ahora 1,1 GB).

  Para quitar el add-on: `install.sh disable` y reiniciar la Force.
- **La Pi:**
  - **gadget con MIDI:** `GADGET_MIDI_PORTS=4`. El puerto 1 es el de control y el GP-150 va al 2. Quitar el MIDI: `GADGET_MIDI_PORTS=0`, `deploy.sh` y un reinicio del gadget;
  - **`rpi-audiod` y el gadget están habilitados al arranque**; `rpi-audio-keepalive` está deshabilitado (`deploy.sh --enable --host akai-force`);
  - perfiles instalados en `/etc/rpi-audio/devices.d/`: el Tracker con track3r-os y el GP-150. Límite Full-Speed: 1099 B por bus;
  - el GP-150 tiene niveles guardados de la prueba de CC: captura 100 % y reproducción 80 %, los que ya tenía;
  - canales: mezclador (CODEC) a IN 1–2 y desde OUT 3–4; GP-150 (ahora 6/4 canales) a IN 3–8 y desde OUT 5–8. IN 25–26 están reservados para el add-on (`tools/hosts/akai-force.toml`);
  - volver al keepalive: `sudo systemctl start rpi-audio-keepalive` (para `rpi-audiod`). Para que dure tras reiniciar: `systemctl disable rpi-audiod` y `systemctl enable rpi-audio-keepalive`.
- **Pendiente del usuario:**
  - si quiere quitar la marca de sucio de AKAI_SSD y de la SD: `fsck.exfat -y` en un ordenador, con el volumen desmontado (la comprobación en solo lectura da AKAI_SSD limpio);
  - ¿suenan el mezclador y el GP-150 en MPC?
  - prueba de salidas: ¿por dónde salen en la Force Out 1/2 y Out 3/4?
  - ¿aparecen `rpi-audio MIDI 1–4` en Preferences → MIDI? Los pads, los botones y los Q-Links siguen respondiendo (confirmado);
  - el control desde MPC **ya está probado** de punta a punta con una pista MIDI y CC enviados por MPC Remote: silencio y nivel del GP-150 (`docs/hw/2026-10-30-boot-soak.md`, sección 7).
- **MPC Remote** está instalado en la Force y se maneja desde aquí por túnel (`docs/hosts/akai-force-remote.md`, `CLAUDE.md`, excepción 2).
- **Control desde el host (decidido con el usuario):** por USB y genérico, **no por red ni con un VST como base**. Hecho como función USB MIDI del gadget (`docs/MIDI.md`):
  - **órdenes de texto en SysEx:** `ping`, `status`, `assign`, `mute` y `volume`, con respuesta. Desde un host Linux: `tools/midictl.py`;
  - **CC en los canales 16 (IN) y 15 (OUT)** del puerto 1: nivel en 32+N y silencio en 64+N, siendo N el primer canal del dispositivo;
  - en MPC, el control irá por una pista MIDI o por Q-Links. Un VST instrumento sería solo una interfaz opcional, en `tools/hosts/`: MPC ignora el MIDI que sale de un plugin, pero el plugin puede abrir su propio puerto ALSA [ext] (sd88me, `docs/NOTES.md`). Lo instalaría el usuario.

## Hub autónomo con pantalla (2026-11-01, solo código y tests; nada desplegado ni probado en la Pi)

Idea del usuario: la Pi como hub sin host (Tracker en "2 OUT / 2 IN", mezclador, GP-150, MIDI), con salida por el Tracker y por el pHAT DAC, controlada desde un OLED con encoder, y **sin perder** el modo con la Force.

- **Hecho en el repo [repo]:**
  - **rutas dispositivo→dispositivo** (`bridge/rpi-audiod/routing.py`, comandos `route`/`unroute`, clave `routes` de `slots.json` y de los presets, campo `routes` del status, `docs/MIDI.md`). Son conexiones JACK entre los puentes, por pares estéreo, y no tocan las del gadget. Un dispositivo nunca se enruta a sí mismo. Sin nivel por ruta: JACK suma y los niveles son los del dispositivo (`volume`).
  - **modelo de la pantalla** (`bridge/rpi-audio-ui/ui.py`): 8 filas de 16 columnas, eventos `cw`/`ccw`/`push`/`confirm`/`back`, pantallas Presets, Routes (destino → fuentes), Devices (mutes y niveles). Solo emite los comandos de `docs/MIDI.md`; los presets ya existían (8 ranuras).
  - **simulador**: `tools/ui-sim.py`, en el terminal y contra un servicio de mentira.
  - `pytest -q tests`: 239 pasan, `flake8` limpio. El comportamiento con JACK real y con la Force **no está probado** (solo el `World` falso de `tests/test_supervisor.py`).
- **Falta:**
  - **modo `standalone`** de `rpi-audiod`: jackd con el pHAT como driver y sin esperar al host. Hoy el motor solo arranca jackd sobre el gadget (modo A). No es el "modo B" de PipeWire del plan. Con la Force no cambia nada.
  - **driver de la pantalla** (luma.oled o similar, GPIO del encoder), unit `rpi-audio-ui.service` opcional (el audio no depende de ella) y su instalación en `install.sh` (hoy `ui.py` no se instala).
  - **hardware:** OLED por I2C con encoder y dos botones (pines de 9: VCC, GND, BACK, TRB, TRA, PUSH, SCL, SDA, CONFIRM); controlador del OLED sin identificar [?]. Cableado propuesto en `docs/DISPLAY.md`. El pHAT DAC no está montado y no hay `/dev/i2c*` en la Pi [Pi]. Montarlo exige tocar `config.txt` y reiniciar: **con la Force parada y con permiso del usuario**.
  - **el Tracker en 2/2:** consumo desde la Pi 4 (1,2 A en total en los USB-A), enumeración, y si su Master de 2 canales incluye el retorno (posible bucle si se enruta de vuelta) [?]. El usuario no tiene acceso al Tracker ahora.
- `deploy.sh`/`install.sh` reinician `rpi-audiod` (la Force oye un corte): no se despliega esto con ella transmitiendo.

## Hecho

- **Repo:** rama `main` en `github.com/trak3r-os/mpc-rpi4-audioface` (alias SSH `github-trak3r`), autor `trak3r-os` con el correo oculto de GitHub. `LICENSE` (GPL-3.0-or-later), `CLAUDE.md`, `.gitignore` (`out/`), `.flake8`.
- **Documentación:** `docs/PLAN.md` v2, `docs/hosts/akai-force.md` y las sesiones `docs/hw/2026-10-29-force-baseline.md`, `docs/hw/2026-10-29-f1-laptop.md` y `docs/hw/2026-10-29-f1-force.md`.
- **La Pi:**
  - sudo sin contraseña para `no3z`;
  - alimentación por el splitter (fuente → POWER, DATA POWER → Pi, USB2 DATA → host), `throttled=0x0`;
  - red por Ethernet en 192.168.1.106. La Pi 4 no tiene Wi-Fi configurada. Ojo: 192.168.2.154 es **otra** placa, una Pi 2 (`raspberrypi2`).
- **Gadget:**
  - `rpi-audio-gadget` instalado con `tools/deploy.sh` y **habilitado al arranque**, junto a `rpi-audiod` (`deploy.sh --enable`);
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
  - **`rpi-audio-keepalive.service`** (instalado, pero deshabilitado desde que `rpi-audiod` va al arranque): reproduce en el gadget mientras el host transmite, con FIFO 70 y un usuario dinámico. Ahora con `KEEPALIVE_SOURCE=silence`; para las pruebas de ida y vuelta, `tones`.

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

- **Hechos de esta noche [Pi][Force]:**
  - `boot.sh` de MockbaMod lanza los add-ons en paralelo y se pisan la lista de `LD_PRELOAD`. El script del add-on espera 0,5 s y la reescribe limpia;
  - **jackd no sobrevive a que el host desaparezca**: el driver para, pero el proceso sigue vivo con el gadget abierto;
  - MPC arrancó dos veces con su audio interno, sin abrir rpi-audio. Está por ver si es porque la Pi no reproducía [?].

## Siguiente

Hecho el 2026-10-30 por la tarde, todo en `main` y en GitHub:
- **rpi-audio Panel** (VST2 para MPC, `tools/hosts/akai-force-panel/`): instalado en la Force con su instalador, en `/media/AKAI_SSD/Synths` (CLAUDE.md, excepción 3).
  - Se abre en MPC, conecta con la Pi y muestra dispositivos, nombres, niveles y presets.
  - MUTE, el selector de nombres, los presets y un fader llegan a `rpi-audiod`.
  - Detalle en `docs/hosts/akai-force-panel.md`.
- **`rpi-audiod`:**
  - nombres de dispositivo y de canal;
  - presets (8 huecos), con Program Change 0–7 en el canal 16;
  - los puentes paran con SIGINT: 0 xruns al desenchufar;
  - ya no anota cada `status`.
- **`install.sh`** en la raíz, para instalar desde un clon en la Pi; `tools/deploy.sh` lo usa por debajo (probado: despliega igual).
- **Docs en inglés para usuarios:** README con las líneas de instalación, `docs/MIDI.md` y las docs del panel y de MPC Remote.
- **La mitigación del incidente,** probada en la Force por `rpi-audio-7d`: limpia. Se quitó la regla.
- **La librería de sd88me, actualizada y sin tocar** (`adc48a3`, `tools/hosts/vendor/mpc-vst-plugins/`, `sync-mpc-vst-plugins.sh`), compartida por el panel y el add-on. El panel se reconstruyó sobre ella y se **reinstaló y probó en la Force**: pantalla, MUTE, presets, fader y cambios desde la Pi (`docs/hw/2026-10-30-boot-soak.md`, sección 8).
- **Zips al formato de sd88me, sin publicar:** `tools/hosts/akai-force-panel/package.sh` (catalog_check OK, 0 avisos) y `tools/hosts/akai-force-internal-io/package.sh VERSION` (addin; OK con 1 aviso, glibc 2.34). El zip del add-on solo se ha probado en simulación. README con las líneas para construirlos e instalarlos.

Datos de muestra en la Pi:
- nombres: CODEC = "Mixer", GP-150 = "Guitar Rig", con "Amp L" y "Amp R";
- presets 1 "Live" y 2 "Quiet" (GP-150 IN al 60 %).

MPC queda en rpi-audio, con un proyecto nuevo sin guardar: la pista Plugin 001 de la plantilla lleva el panel.

**En curso (17:00): matriz de soaks para el `-5`** (`docs/hw/2026-10-30-boot-soak.md`, sección 9). Capturas en `out/soak-*/` (usbmon de la Force por minuto, `minutes.txt` con el resumen de `tools/usbmon-check.py`):
- **A** (panel abierto, `aplaymidi` por respuesta, `ondemand`, req 4): ~6 paquetes IN vacíos por minuto y un rearranque de streams de MPC cada 2–5 min; ningún `-5` en 30 min.
- **B** (sin panel): **0 vacíos y 0 rearranques en 21 min**. El panel (o su tráfico MIDI) es el disparador.
- **C1** (panel, emisor MIDI persistente nuevo ya desplegado, 0.1.0): en marcha desde las 16:50.
- Faltan: **C2** (governor `performance`: `systemctl enable --now rpi-audio-cpu`), **D** (`GADGET_REQ_NUMBER=8`), **E** (parche de `u_audio`: `tools/kernel/u_audio/build.sh build` y `load`, hasta el siguiente reinicio; probar cambiando Internal → rpi-audio varias veces y reiniciando `rpi-audiod`).
- MPC queda en rpi-audio, proyecto nuevo sin guardar con la pista "Plugin 001" (panel) y "Audio 001".
- El add-on con el log en hilo propio está compilado pero **no instalado** en la Force (necesita reiniciar MPC).

Hecho también hoy por la tarde (todo en GitHub, CI verde): versión 0.1.0, `rpi-audiod doctor`, `rpi-audio-cpu.service`, `install.sh --tune-boot` (opt-in), parche de `u_audio` (sin cargar aún), 54 tests del supervisor y CI, emisor MIDI por raw MIDI (probado en la Force: el panel funciona), la reserva del presupuesto USB tras un crash.

Queda:
1. **Un `capture error -5` espontáneo** a los 20 minutos, con el panel abierto (`docs/hw/2026-10-30-boot-soak.md`, sección 8). Separar la causa: soak con el panel abierto y otro sin él.
2. **Catálogo de sd88me:** dos entradas (`kind: instrument` y `kind: addin`) con su `asset_pattern`. Necesitan zips publicados en una release, y el usuario no quiere release por ahora: no pedirla. El PR a sd88me es hacia fuera: preguntar antes.
3. **Panel, sin probar en la Force:** los Q-Links físicos, SAVE, "On project load", reabrir un proyecto guardado, y si los bloqueos de la restauración (3 s + 2 s) son adecuados.
4. **Proponer al usuario un `u_audio.ko` parcheado:** es la causa del `capture error -5` en la primera apertura y de los cortes al reiniciar `rpi-audiod`.
5. **MPC al arrancar** abre siempre su audio interno. Opción: elegir rpi-audio con MPC Remote al arrancar.
6. **Con el usuario:**
   - escuchar el mezclador y el GP-150;
   - por dónde salen Out 1/2 y 3/4, y después `install.sh conf` del add-on y reiniciar la Force;
   - con el Tracker, la aceptación de F4 y el presupuesto Full-Speed.
7. **Después:** F5, F1b, S32.

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
