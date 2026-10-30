# rpi-audio: plan de implementación

Objetivo: **un hub de audio USB genérico sobre una Raspberry Pi 4.** La Pi se presenta ante un host USB como **una sola interfaz de audio class-compliant (UAC2)**: 16×16 para empezar, hasta 24–26 con el kernel de serie. Detrás, por sus USB-A, acepta **cualquier dispositivo de audio o MIDI USB que Linux reconozca**: lo detecta al enchufarlo, compensa su reloj frente al del host y permite enrutar cualquiera de sus canales a cualquier canal del host, en ambos sentidos.

El proyecto no está atado a ningún host. **El primero que probamos es la Akai Force**, y sus requisitos (solo 44,1 kHz, nada de "UAC2_Gadget" en el nombre) están documentados como los de un host más (`docs/hosts/`). Los segundos son los ordenadores con macOS, Windows y Linux. En el resto del plan, "Force" es ese primer host; lo que se dice de ella vale para cualquier host con requisitos parecidos.

Los dispositivos de prueba son el **Polyend Tracker original con tu firmware track3r-os** (en "10 OUT / 2 IN"), el **Valeton GP-150** y una **tarjeta de sonido USB genérica**. No son un caso especial: el código solo los conoce por un perfil opcional con nombres y preferencias.

Versión 2 (2026-10-29): revisada tras estudiar proyectos parecidos (§8) y las fuentes del kernel, de JACK y de PipeWire, y con tus respuestas a las preguntas (§5).

Licencia: **GPL-3.0-or-later** (`LICENSE`).

Marcas de evidencia:

- **[Pi]**: verificado en nuestra Pi.
- **[Force]**: verificado en tu Force con `tools/hosts/akai-force-probe.sh` (`docs/hw/`).
- **[repo]**: documentado y medido en `../track3r-os` u `../o3-sdk`.
- **[código]**: leído en el código fuente de un tercero (kernel rpi-6.18.y, JACK 1.9.22, PipeWire 1.4.2, MPC OS).
- **[ext]**: medido o afirmado por otro proyecto o en un foro, sin verificar aquí.
- **[est]**: estimación.
- **[?]**: pregunta abierta.

---

## 1. Lo que ya sabemos

### Raspberry Pi (192.168.1.106, usuario `no3z`, clave SSH instalada)

| Hecho | Fuente |
|---|---|
| Raspberry Pi 4 Model B Rev 1.5, **1 GB**, 4 × Cortex-A72; páginas de 4 KiB | [Pi] |
| Debian 13 trixie, kernel `6.18.50+rpt-rpi-v8`, `PREEMPT` (no RT). El RT está disponible en apt (`linux-image-rpi-v8-rt`) | [Pi] |
| `dtoverlay=dwc2,dr_mode=peripheral` está activo: el UDC `fe980000.usb` existe | [Pi] |
| Compilados `usb_f_uac2`, `usb_f_uac1`, `usb_f_midi` y `usb_f_midi2` | [Pi] |
| Los USB-A van al controlador VL805 por un hub interno VIA `2109:3431`, **Single TT** | [Pi] |
| **El VL805 admite unos 1023 B de datos periódicos Full-Speed por frame entre todos los USB-A**, una cifra que subió con el firmware 0138a1. Tres usuarios cuentan que un hub Multi-TT **no lo arregló** (el mismo hub sí funcionaba en dwc2 y en un portátil) | [ext] ingenieros de Raspberry Pi en `raspberrypi/linux#3962`, foros |
| En apt: `jackd2` 1.9.22, `jack-example-tools` (`zalsa_in`/`zalsa_out` internos), `zita-ajbridge` 0.8.4, `pipewire` 1.4.2, `wireplumber` 0.5.8, `python3-jack-client`, `python3-pyudev` | [Pi], [ext] |
| **El `libzita-resampler` de Debian arm64 está compilado sin NEON**; el de amd64 sí lleva SSE2 | [ext] `debian/rules` |
| Governor `ondemand`; hay que pasarlo a `performance` | [Pi] |
| Hardware que ya tienes: **splitter USB-C de datos y alimentación** y **Pimoroni pHAT DAC** (PCM5102A, I2S, solo salida, minijack de línea, overlay `hifiberry-dac`) | Tus respuestas; [doc] para el pHAT |

### El gadget UAC2 del kernel (rpi-6.18.y)

| Hecho | Fuente |
|---|---|
| **Máximo 27 canales por sentido**: `UAC2_CHANNEL_MASK 0x07FFFFFF`. Hay un parche (Farrell, julio de 2026, sin integrar) que añade `p_channels`/`c_channels` y llega hasta 96 | [código], [ext] LKML |
| **Periodo máximo = `PAGE_SIZE`**: 4096 B / (canales × bytes por muestra). Con 16 ch en S32 son 64 frames; 16 ch en S16, 128; 26 ch en S32, 39 (32 en la práctica). Mínimo de 4 periodos; buffer máximo de 16 páginas | [código] `u_audio.c` |
| Frames por paquete a 44,1 kHz: bint 1 → 6, bint 2 → 12, bint 3 → 23, bint 4 → 45. Con `*_hs_bint=0` (automático) se elige el mayor bint cuyo paquete quepa en 1024 B: con 16 ch en S32 sale bint 2 (768 B) | [código] `f_uac2.c` |
| Los FIFO del dwc2 de la Pi (TX 5×512 + 2×256 palabras, RX 558) admiten paquetes de hasta 1024 B. No se pueden cambiar con un dtparam | [código] `dwc2-overlay.dts` |
| `req_number` (2 por defecto) añade unos (req_number − 1) × intervalo de latencia **que ALSA y JACK no ven** | [código] |
| Los controles **"Capture Rate" y "Playback Rate"** valen 44100 mientras el host transmite y 0 si no, y notifican cada cambio. Un host Linux los cambia unos 25 ms durante la enumeración, así que hay que filtrar con al menos 50 ms | [código], [ext] gaudio_ctl |
| **"Playback Pitch"** existe siempre que hay reproducción. **"Capture Pitch"** solo existe con `c_sync=async` | [código] |
| El puntero del PCM del gadget **solo avanza cuando hay tráfico USB**: si la Force no transmite, se queda parado | [código] |
| **JACK 1.9.22 sobre el gadget parado:** el timeout de poll es 1,5 periodos y, tras 5 reintentos, el driver falla. `jackd` muere unos 8 periodos después de que la Force pare, y no puede arrancar antes de que transmita | [código] `alsa_driver.c` |
| **PipeWire (desde 0.3.72) detecta los controles de pitch del gadget** y, si el gadget es *follower*, los ajusta **en vez de remuestrear** | [código] `alsa-pcm.c` (`probe_pitch_ctl`) |
| Los `incomplete isoc` del dwc2 y los errores iso de u_audio solo salen con debug dinámico (`dev_dbg`/`pr_debug`), y **el kernel de la Pi no lo trae** (`# CONFIG_DYNAMIC_DEBUG is not set`). Los cortes se detectan de punta a punta con `tools/tonecheck.py` | [código], [Pi] |
| Reenlazar el UDC muchas veces seguidas puede bloquear el controlador | [ext] pi-gadget-kit |
| Muestras de 3 bytes de Windows a la Pi daban una discontinuidad en cada paquete | [ext] Tractus |

### Akai Force (host USB)

| Hecho | Fuente |
|---|---|
| Admite interfaces class-compliant, hasta 32 IN / 32 OUT. **"32 I/O" es una casilla opcional** en Preferencias | [doc] Akai, [ext] foros |
| Tu Force: kernel `6.18.26-az01-2026-04-30-rt4` PREEMPT_RT, armv7l, `az0x 5.0.17 (scarthgap)`, **MockbaMod activo**, SSH en `force.local` (192.168.2.31) | [Force] 2026-10-29 |
| El SoC es un RK3288; `CONFIG_SND_USB_AUDIO=y` | [ext] mpc-vst-plugins `NOTES.md` |
| Con su códec interno (ADA2), MPC abre **reproducción 4 ch y captura 2 ch, S32_LE, 44100, periodo de 128** (buffers de 384 y 256), RW_INTERLEAVED. Su log: "Audio 44100Hz; 2-in; 4-out; 128sample buffer … filter=32" | [Force] |
| Su USB host es un EHCI (`ff500000.usb`) detrás de su hub interno "Force Hub" (USB5537B). El gadget comparte ese bus con el SSD interno, el lector SD y la superficie de control. Los índices de las tarjetas ALSA cambian según lo que haya enchufado | [Force] |
| **Con una interfaz externa, MPC la abre por índice (`hw:N`), primero la captura, y exige 44,1 kHz nativos.** Si no los tiene, se queda en 2-in/2-out ("44100 may not be a supported sample rate… -22") | [ext] log de un MPC One mk2 (TheKikGen #14), no de la Force |
| **MPC ignora cualquier tarjeta cuyo nombre largo coincida con "UAC2_Gadget"** | [ext] desensamblado y prueba en un MPC Key 37 |
| **Al seleccionar una interfaz externa, la Force desactiva su audio interno**: entradas, salidas, auriculares y volumen. Ningún mod conocido lo mantiene | [ext] foros |
| La Force **no puede ser gadget USB en standalone**: su hub interno (USB5537B) solo cambia el puerto de subida en Computer Mode | [ext] macdigi |
| Funcionan, según foros: UMC1820 (18×20), XR18, Zen Tour (con "32 I/O"), RME en modo CC y EVO16. Fallan: PreSonus 1810c (salta a 192k), StudioLive III, MOTU M4 (artefactos) e iConnect 4+ (pops que se arreglan cambiando de puerto: el bus). Nadie cuenta haber usado una Pi como gadget | [ext] foros |
| Las actualizaciones de firmware han roto interfaces que antes funcionaban | [ext] foros |

### Tarjeta de sonido USB genérica (dispositivo de prueba "sin perfil")

| Hecho | Fuente |
|---|---|
| Modelo, chip, canales, frecuencias, UAC1 o UAC2 y velocidad | [?] Se verá en la Pi. Las típicas (C-Media y parecidas) son Full-Speed UAC1, estéreo de salida y mono o estéreo de entrada, a 48 kHz y a veces 44,1 kHz, y gastan unos 200–400 B/ms [est] |

### Polyend Tracker original con tu firmware track3r-os (dispositivo de prueba)

| Hecho | Fuente |
|---|---|
| **Full-Speed**, **UAC2**, 16 bits, un único reloj de 44.100 Hz, **asíncrono** (feedback explícito para el retorno). Desde OS-RATE el motor va a 44.100,00 Hz exactos con cristal propio | [repo] ADR 0012 |
| Se presenta como "Track3r Audio" con el VID/PID oficial; el modo AUDIO se distingue por `bcdDevice` | [repo] `usb/identity.h` |
| Disposiciones, con la carga periódica FS en bytes por frame (entrada + retorno + feedback): "2 OUT / 2 IN" 363; "8 OUT" 720; **"8 OUT / 2 IN" (por defecto) 903**; "10 OUT" 900; "10 OUT / 2 IN" 1083; "11 OUT" 990 | [repo] ADR 0012, enmienda 5 |
| **Tú lo usas en "10 OUT / 2 IN"**: 8 stems mono pre-pan + Master L/R hacia el host y retorno estéreo. Son **1083 B por frame** | Tu respuesta; [repo] |
| Detrás de un hub con TT, "10 OUT / 2 IN" no abre en dúplex en Linux | [repo] medido en 0.4.6 |
| El retorno suena por las salidas y los auriculares del Tracker, y la grabadora puede samplearlo | [repo] ADR 0012, enmienda 6 |
| o3-sdk (o3-303) manda 8 canales con el master en 7–8. Su MIDI USB está planificado | [repo] `FRAMEWORK.md` §10 |

### Valeton GP-150

| Hecho | Fuente |
|---|---|
| USB **6 in / 4 out**, 24 bit, **48 kHz**. MIDI por USB, BT y TRS. Batería de 3000 mAh que se carga por USB-C | [doc] Valeton |
| **Medido:** class-compliant UAC2, **High-Speed**, **2 in / 2 out** (no 6/4), 24 bit en S32_LE, **solo 48 kHz**, asíncrono, paquetes cada 125 µs (`docs/hw/2026-10-29-f2-usb-devices.md`) | [Pi] |

---

## 2. Arquitectura

```
                USB-C · gadget UAC2 (+MIDI en F4) · High-Speed · 44,1 kHz · dwc2
 Akai Force  <=========================================>  Raspberry Pi 4
 (host USB)    N IN (Pi→Force) / N OUT (Force→Pi), N = 16 → 24/26
                                                             │
                                          motor de audio: JACK2 (modo A) o PipeWire (modo B),
                                          se decide en F2 midiendo
                                                             │
                     ┌─ por cada tarjeta USB que aparece (sea cual sea), por el VL805:
                     │    puente con compensación de deriva (zita en A, adaptativo en B)
                     │    p. ej. Tracker (FS, 10 OUT / 2 IN), GP-150 (48 kHz), tarjeta USB genérica (FS)
                     └─ monitorización: pHAT DAC por I2S (no gasta USB)

                     rpi-audiod (Python): detección, presupuesto USB, asignación de canales,
                     rutas, estado.  rpi-audio (CLI): enrutado a mano
```

### Relojes: los dos modos que se comparan en F2

**Modo A: JACK2, con el gadget como driver.**
- El grafo sigue el reloj USB de la Force, y el camino Force ↔ Pi es bit-transparente.
- Cada dispositivo entra por `zita-a2j`/`zita-j2a`, o por `zalsa_in`/`zalsa_out` como clientes internos.
- `jackd` solo vive mientras la Force transmite. `rpi-audiod` lo arranca cuando "Capture Rate" y "Playback Rate" valen 44100 (con 50 ms de filtro), y su salida cuando la Force para es **normal**.
- Con 16 ch en S32 el periodo máximo es de 64 frames (`-p 64`), o 128 en S16.
- En este modo no puede haber PipeWire instalado: se quedaría con el gadget y tocaría su pitch.

**Modo B: PipeWire, con un driver local estable.**
- El driver es el pHAT DAC (su reloj es el de la Pi) o el reloj del sistema.
- El gadget es *follower* y PipeWire **ajusta su pitch** (feedback y tamaño de paquete) en lugar de remuestrear, así que el camino de la Force sigue siendo bit-transparente. La Force pasa a seguir el reloj de la Pi, que es lo normal en cualquier interfaz UAC2 asíncrona.
- Los dispositivos USB son *followers* con remuestreo adaptativo (NEON, unos 48 muestras de latencia [ext]).
- El grafo sigue funcionando sin la Force, así que se puede enrutar entre dispositivos.
- Hotplug de nodos integrado.

**Restricción medida con la Force (`docs/hw/2026-10-29-f1-force.md`) [Pi][Force]:** MPC trata la entrada y la salida del gadget como **un solo reloj**.
- **Lo medido:**
  - Si el ritmo del IN (Pi → Force, "Playback Pitch") difiere del que pide el feedback del OUT ("Capture Pitch"), MPC entra en xrun y reinicia el stream.
  - Con un 0,1 % de diferencia, reinicia cada ~3,6 s (holgura de unas 160 tramas).
  - Si la Pi deja de reproducir en el gadget, `u_audio` envía 11 tramas cada 250 µs, es decir 44.000/s. MPC entonces se reinicia o acaba con `capture error -5`.
- **Consecuencias:**
  - **El motor tiene que reproducir en el gadget siempre que "Playback Rate" ≠ 0**, aunque sea silencio, y relanzarse en menos de ~1 s si cae.
  - **Los dos pitch tienen que valer lo mismo en todo momento.** El modo A no los toca, así que cumple. En el modo B, PipeWire ve la reproducción y la captura del gadget como dos nodos, cada uno con su propio lazo de pitch, y eso puede desincronizarlos [est]. Hay que verificarlo en F2: se cumple si los dos pitch son iguales y MPC no registra xruns en 30 minutos. Si no, el modo B necesita un ajuste de pitch propio que mueva los dos juntos (el `drift.c` de mpc-addin).

Las dos opciones dejan igual lo que escribimos nosotros: identidad, ranuras, rutas persistentes y presupuesto USB. Ninguna de las dos persiste enlaces por dispositivo. Por eso **la capa de enrutado se escribe sobre la API de JACK** (`python3-jack-client`), que funciona igual sobre `jackd` y sobre `pipewire-jack`. El ciclo de vida de los puentes va en un módulo aparte (zita en A; nada en B).

### Dispositivos genéricos

**Identidad estable** (como `device_id.py` de raspimidihub):
- `usb-VID:PID-serie`; si no hay serie, `usb-<ruta de puerto>-VID:PID`.
- Se descartan las series de relleno: menos de 3 caracteres, un solo carácter repetido o `0+1?` (el Digitone II manda "000000000001"). Se limpian los espacios de relleno (Roland).
- Los duplicados llevan `#N`.
- "Emparejamiento suave": si una identidad guardada y un único dispositivo nuevo comparten VID:PID, se reasigna.
- **`bcdDevice` no entra en la identidad**, porque una actualización de firmware perdería las ranuras. Se usa como "forma" del dispositivo en el perfil (p. ej. el Tracker en modo STANDARD o AUDIO).

**Detección:**
- udev (`subsystem=sound`) para las tarjetas; consulta de capacidades por ALSA (PCM, canales, formatos y frecuencias).
- Abrir a 44.100 Hz si el dispositivo lo admite; si no, a su frecuencia preferida, y que el puente convierta.
- **Antes de abrir, calcular su carga periódica FS** con los descriptores (`wMaxPacketSize` de sus endpoints isócronos). Si no cabe en lo que queda del presupuesto del VL805, se aparca y se dice por qué, en vez de esperar a un `ENOSPC`. Puede que el ancho de banda no se libere tras un fallo [ext], y entonces habría que reenchufar.
- Modo A: zita no sale cuando se desenchufa el dispositivo (reintenta cada 10 ms) y **sí sale si cambia el buffer de JACK**. `rpi-audiod` lo mata cuando udev quita la tarjeta y lo relanza si muere.
- Los clientes JACK llevan el nombre de la identidad estable.

**Ranuras pegajosas:**
- La Force ve IN 1..N y OUT 1..N.
- A un dispositivo nuevo se le asigna el **primer bloque libre contiguo**, con los estéreo empezando en canal impar, y la asignación **se guarda por identidad**: al reenchufarlo recupera sus canales.
- Si no hay sitio, queda **aparcado**: tiene puente y aparece en el estado, pero no está conectado.
- Las rutas no tienen por qué ser 1:1: cualquier canal puede ir a cualquier ranura, y varias fuentes pueden ir a la misma (se suman).
- Los dispositivos desconectados siguen visibles con sus rutas guardadas.

**Enrutado:**
- CLI `rpi-audio` (F2): `status`, `route`, `unroute`, `assign`, `park`.
- Matriz web (F5) sobre la misma API, con Server-Sent Events.

**Perfiles opcionales** (`config/devices.d/*.toml`): nombres de canal, PCM o frecuencia preferidos, bloque preferido, canales a ignorar y forma según `bcdDevice`.

### Presupuesto USB Full-Speed en la Pi 4 (medido: el xHCI acepta 1099 B y rechaza ~1270 B por frame)

| Combinación | Carga FS | ¿Cabe? |
|---|---|---|
| Tracker "8 OUT / 2 IN" | 903 | Sí. **Medido [Pi]:** a su lado cabe un sentido del mezclador PCM2902 (grabación a 48 kHz, 196 B, o reproducción, 192 B), pero no los dos. La grabación del PCM2902 a 44,1 kHz falla con EIO aunque cabría [?] |
| Tracker "8 OUT" (sin retorno) | 720 | Sí; quedan unos 300 B |
| Tracker "2 OUT / 2 IN" | 363 | Sí; quedan unos 660 B: un estéreo FS de 16 bit a 48 kHz cabe (unos 400 B dúplex [est]) |
| Tracker "10 OUT" (sin retorno) | 900 | Sí, pero solo; quedan unos 120 B |
| **Tracker "10 OUT / 2 IN" (tu disposición)** | 1083 | **No**: pasa del límite él solo. Detrás de un TT ya no abría en dúplex [repo] |
| Tarjeta USB genérica (FS, estéreo) | unos 200–400 [est] | Sí, sola o con el Tracker en "2 OUT / 2 IN" |
| Tracker "10 OUT / 2 IN" + tarjeta USB genérica | unos 1300–1500 [est] | **No** |
| Dispositivos High-Speed (GP-150 [Pi] y casi todas las interfaces modernas) | 0 | No cuentan. Medido: Tracker 8/2 + GP-150 + grabación del mezclador, a la vez y con los bytes exactos |

Consecuencias:
- En la Pi 4 cabe **un solo** dispositivo de audio FS mediano.
- **Con tu equipo no cabe todo en la Pi 4.** Tu Tracker en "10 OUT / 2 IN" ya pasa del límite él solo, y la tarjeta USB es otro FS. El GP-150 es HS y no cuenta [Pi].
- Mientras tanto, en la Pi 4 solo hay opciones con recortes: el Tracker en "10 OUT" sin retorno o en "8 OUT / 2 IN", sin la tarjeta USB; o el Tracker en "2 OUT / 2 IN" con la tarjeta. F2 mide cuál abre de verdad.
- La monitorización va por el **pHAT DAC (I2S)**, nunca por un DAC USB FS.
- Un hub Multi-TT **se prueba antes de comprarlo** (si ya tienes uno, mejor); con los informes que hay, no se espera que ayude.
- **Por eso es probable que haga falta una Pi 5** [?]: es la salida para tener a la vez el Tracker en "10 OUT / 2 IN" y la tarjeta USB. F2 lo confirma antes de comprar nada. Ventajas:
  - RP1 tiene **dos controladores xHCI**, con dos puertos USB 2.0 cada uno y sin hub interno compartido;
  - páginas de 16 KiB: el periodo del gadget es 4 veces mayor (16 ch en S32 → 256 frames; 26 ch → 128);
  - una CPU unas 2–3 veces más rápida para los remuestreadores.

  Hay que verificarlo en F2b: el modo gadget en su USB-C, el presupuesto FS de cada controlador y la alimentación (con una fuente que no sea de 5 A, la Pi 5 limita los USB a 600 mA salvo con `usb_max_current_enable=1`; el hub alimentado lo resuelve). **El código no depende del modelo**: F1 y F2 siguen en la Pi 4.

### Ejemplo de reparto con tus dispositivos

| Force IN (Pi → Force) | Origen |
|---|---|
| 1–8 | Tracker: stems S1–S8 (pistas 1–8, mono, pre-pan) |
| 9–10 | Tracker: Master L/R |
| 11–12 | GP-150 USB 1–2 |
| 13–14 | Tarjeta USB genérica: entrada |

| Force OUT (Force → Pi) | Destino |
|---|---|
| 1–2 | **Monitorización** (reservada: la Force apaga la suya): pHAT DAC |
| 3–4 | Retorno USB del Tracker (suena por sus salidas y se puede samplear) |
| 5–6 | GP-150 USB 1–2 |
| 7–8 | Tarjeta USB genérica: salida (segunda escucha, auriculares o cue) |
| 11–… | Libres |

Son 14 entradas (eran 18 con el GP-150 supuesto a 6/4), así que 16×16 se queda justo: el objetivo de F1 es **24×24** (o 26×26), con 16×16 solo como primer escalón. El resto queda libre para más dispositivos.

### Decisiones

| Decisión | Por qué | Alternativa |
|---|---|---|
| **UAC2, High-Speed, 44,1 kHz, 16×16 → 26 → 32** | Quieres el máximo. El kernel de serie corta en 27 canales; la Force admite 32 | 32 (F1b, planificado): recompilar `u_audio`/`usb_f_uac2`/`usb_f_uac1` fuera del árbol con DKMS, el parche Farrell y un `PRD_SIZE_MAX` mayor (son módulos, no hace falta compilar el kernel). Fallbacks: 8×8 y 2×2, S16, UAC1 |
| **Muestras S32 (`ssize=4`)** primero | Es lo que usa MPC internamente | S16: duplica el periodo máximo y cuadra con el Tracker. Evitar S24_3LE hasta probarlo |
| **Motor: se decide en F2 midiendo** | Las dos opciones tienen ventajas reales (§2, Relojes) | Regla de F2 |
| **Capa de enrutado sobre la API de JACK** | Funciona con los dos motores | — |
| **MIDI por suscripciones de ALSA seq en el kernel** | Unos 0 ms y sin JACK | a2jmidid: no hace falta |
| **Monitorización con el pHAT DAC** (ya lo tienes) | No gasta presupuesto USB, y en el modo B sirve de driver estable | La salida de la tarjeta USB genérica |
| **Perfiles que pueden elegir canales** | Un dispositivo puede tener más canales que ranuras libres | Sumar canales en una ranura |
| **Python con stdlib + pyudev + jack-client** | `tomllib` en 3.13; lógica pura probada con pytest | — |

---

## 3. Fases

Cada fase tiene entregables, criterio de aceptación y una nota de sesión en `docs/hw/AAAA-MM-DD-*.md` con las salidas reales. Nada se da por terminado sin el comando que lo demuestra (la regla de tus repos).

### F0: Base

**Repo**
- `git init`.
- **Licencia: GPL-3.0-or-later** (decidido; `LICENSE` ya está en el repo). Permite reutilizar código de raspimidihub (GPL-3), gaudio_ctl (GPL-3), Tractus (Apache-2.0) y `drift.c` de mpc-addin (MIT), conservando sus avisos en `THIRD_PARTY.md`.
- `CLAUDE.md` con las reglas:
  - marcas de evidencia;
  - no editar `../track3r-os` ni `../o3-sdk`;
  - acceso a la Pi por SSH;
  - nada destructivo en la Pi sin preguntar;
  - no reenlazar el UDC en bucle;
  - **en la Force, solo lectura**: nunca escribir, instalar ni reiniciar servicios.
- `docs/STATUS.md`.

**Pi**
- `tools/pi-facts.sh`: modelo, kernel, **versión de firmware del VL805**, `lsusb -t`, TT de cada hub, tarjetas ALSA, governor, `get_throttled`, si hay debug dinámico.
- Paquetes base: `alsa-utils`, `python3-pyudev`, `python3-jack-client`, `rsync`. Los de cada motor se instalan en F2 y nunca los dos a la vez.
- Ajustes:
  - governor `performance`;
  - `dtparam=audio=off`, sin audio HDMI;
  - `threadirqs`;
  - `rtprio`/`memlock` para `audio`;
  - sin ahorro de energía en Wi-Fi.
- `tools/deploy.sh`: rsync e instalación, idempotente.

**Hardware**
1. **Alimentación con tu splitter USB-C:** comprobar con un multímetro que el VBUS del lado de la Force **no recibe 5 V** de la Pi, y que la fuente da 5 V/3 A.
2. **pHAT DAC:** `dtoverlay=hifiberry-dac` y `dtparam=audio=off`. Prueba con `speaker-test -D hw:sndrpihifiberry -c 2 -r 44100` (comprobar el nombre real de la tarjeta). Usa los GPIO 18, 19 y 21, sin conflicto con el gadget.
3. **Hub USB alimentado**, por corriente (los USB-A de la Pi 4 dan 1,2 A en total), no por ancho de banda.
4. **GP-150 con su fuente de 9 V.**

**Aceptación:** `pi-facts` y `deploy` dos veces seguidas sin cambios, con la salida en `docs/hw/`.

### F1: El gadget frente a la Force (go/no-go)

Entregables:
- `gadget/rpi-audio-gadget`: configfs `up`/`down`, que se ejecuta **una sola vez** al arrancar.
- `rpi-audio-gadget.service`: arranca pronto. El gadget enumera aunque no haya motor de audio.

Valores iniciales de configfs:

| Atributo | Valor |
|---|---|
| `p_chmask`, `c_chmask` | `0xFFFF` |
| `p_srate`, `c_srate` | `44100` (solo esa) |
| `p_ssize`, `c_ssize` | `4` |
| `c_sync` | `async` |
| `p_hs_bint`, `c_hs_bint` | `2` |
| `req_number` | `4` (unos 0,75 ms), luego afinar entre 2 y 8 |
| `*_volume_present`, `*_mute_present` | `0` |
| iProduct, iManufacturer y `function_name` | Nombres claros, p. ej. "rpi-audio 16x16". **Nunca "UAC2_Gadget"** |
| `bDeviceClass` | EF/02/01, cuando haya composite (F4) |

1. **Detección de cortes.** El kernel de la Pi no trae debug dinámico [Pi], así que los `incomplete isoc` del dwc2 no se pueden ver. Los cortes se miden de punta a punta:
   - `tools/tonegen.py` genera un tono por canal (canal n = n × 110 Hz);
   - `tools/tonecheck.py` comprueba el orden de canales y detecta cada muestra perdida, repetida o puesta a cero (residuo de x[n+1] = 2·cos(ω)·x[n] − x[n−1]). Admite capturas por tubería desde `arecord`, así que vale para soaks largos;
   - además, los xruns de `aplay`/`arecord` y la tasa de IRQ (`/proc/interrupts`).

   Un kernel con debug dinámico solo si hace falta localizar un fallo concreto.
2. **Contra el portátil Linux:**
   - 2×2 y luego 16×16;
   - Pi → portátil: `tonegen.py | aplay` en la Pi y `arecord | tonecheck.py --expect-order` en el portátil;
   - portátil → Pi: al revés, analizando en el portátil la captura copiada de la Pi;
   - comprobar que "Capture Rate" y "Playback Rate" pasan a 44100 y vuelven a 0 (`alsactl monitor`);
   - 10 minutos con `tonecheck` en OK en los dos sentidos.
3. **En la Force**, conectada **directamente** a un USB-A de la Force (sin hub):
   - ¿aparece en Preferencias > Audio Device?;
   - seleccionarla a 44,1 kHz / 128, con y sin "32 I/O";
   - **comprobar que los auriculares de la Force se apagan**;
   - grabar los 16 tonos;
   - reproducir hacia la Pi;
   - **soak de 30 minutos**;
   - desconectar y reconectar, y probar los dos órdenes de arranque (la Pi tiene que enumerar antes de que la Force busque interfaces: medir los tiempos de los dos lados).
4. **Matriz de fallback**, con cada intento anotado:
   - `ssize` 4 → 2;
   - canales 16 → 8 → 2;
   - `c_sync` async → adaptive;
   - bint 2 → 1;
   - UAC1.
5. **Subir a 24 y 26 canales** y repetir el soak. Hay dos límites:
   - con S32, el paquete a bint 2 solo cabe hasta 21 canales (22 × 4 B × 12 = 1056 B > 1024). Por encima hace falta **bint 1**, con el doble de interrupciones (unas 20.000/s en dúplex, frente a las ~10.650/s medidas a 16 ch [Pi]), o **S16 con bint 2**. `rpi-audio-gadget check` lo calcula y `deploy.sh` rechaza la configuración antes de instalarla;
   - el periodo máximo baja a 32 frames con S32.

   Se prueban las dos variantes y se elige con el soak (y con lo que acepte la Force).
6. **F1b, 32×32:** paquete DKMS con `u_audio`, `usb_f_uac2` y `usb_f_uac1` parcheados (Farrell + `PRD_SIZE_MAX` mayor), compilado contra las cabeceras del kernel fijado. Soak de 30 minutos a 32 ch, con y sin "32 I/O" en la Force. Si el parche se integra en el kernel de Raspberry Pi, el DKMS desaparece.
   - En el mismo paquete, otro parche de `u_audio`: cuando la reproducción ALSA no está en marcha, calcular el tamaño de cada paquete IN con su residuo y mandar silencio, en vez de reencolar el tamaño fijo con datos viejos. Así el gadget aguantaría con la Force aunque el motor caiga. Es candidato a enviarse al kernel.

**Aceptación:** la Force graba N canales en el orden correcto y reproduce hacia la Pi durante 30 minutos, con `tonecheck` en OK (0 cortes) en los dos sentidos. **Si ninguna fila de la matriz funciona, se para el proyecto** y se replantea (F6a, o la Force como host directo del Tracker).

**Diagnóstico desde la Force (tiene SSH).** `tools/hosts/akai-force-probe.sh` se ejecuta por SSH, **solo lee** y guarda la salida en `docs/hw/`:
- `uname -a`;
- `cat /proc/asound/cards`;
- `/proc/asound/cardN/stream0`: cómo ve la Force nuestros descriptores (formatos, canales, endpoints, sincronía);
- `pcm0{p,c}/sub0/hw_params` y `status`: el formato, los canales, el periodo y el buffer que elige MPC de verdad;
- `journalctl -t az01-launch-MPC | grep '\*\*\*\*'`: la línea "Audio 44100Hz; N-in; N-out";
- `lsusb -v` del gadget;
- `dmesg` de snd-usb-audio.

Así se resuelven sin adivinar el formato que pide MPC, si abre en dúplex, cuántos canales abre con y sin "32 I/O", y qué pasa en el arranque y en el hotplug. Se ejecuta en cada paso de la matriz de fallback.

### F2: Elegir el motor y hacer el núcleo genérico

**1. Banco de pruebas, el mismo para los dos motores:**
- gadget 16×16 con la Force;
- el Tracker;
- 2–4 dispositivos simulados con `snd-aloop` y "PCM Rate Shift" (deriva sin gastar USB [est], por verificar).

Medir:
- CPU por canal remuestreado: zita de Debian, **zita recompilado con NEON** y el remuestreador de PipeWire;
- xruns en 30 minutos;
- latencia en la Pi (`jack_iodelay`) y latencia total sobre un WAV grabado en la Force (incluye la cola `req_number`, que la Pi no ve);
- qué pasa cuando la Force para y arranca;
- hotplug.

**Regla de decisión:** se elige **PipeWire** si da 0 xruns y su latencia total no supera a la de JACK en más de 5 ms. Si no, **JACK**. Las medidas fijan también el **tope de canales puenteados** de la Pi 4.

**2. `rpi-audiod` v1**, independiente del motor salvo el ciclo de vida de los puentes:
- identidad estable;
- ranuras pegajosas;
- presupuesto FS previo;
- rutas y estado persistente;
- arranque y parada del motor según los controles Rate (modo A);
- **reproducción continua en el gadget** mientras "Playback Rate" ≠ 0, aunque sea silencio, y relanzamiento en menos de 1 s si cae (§2, restricción de la Force).

También la CLI `rpi-audio`, `config/rpi-audio.toml` y `config/devices.d/` (perfiles del Tracker y del GP-150), con pytest de:
- capacidades → plan de puente;
- identidad (series de relleno, sin serie, duplicados, emparejamiento suave);
- bloques (pares alineados, aparcado);
- presupuesto FS;
- rutas.

**3. Tus dispositivos en el VL805:**
- **Tracker con track3r-os**:
  - **"10 OUT / 2 IN"** solo: se espera que no abra en dúplex (1083 B). Confirmarlo, y que `rpi-audiod` **avise antes de abrir**;
  - "10 OUT", "8 OUT / 2 IN", "8 OUT" y "2 OUT / 2 IN": cuál abre en dúplex y con 0 xruns;
  - desenchufarlo y cambiar USB AUDIO o USB RETURN en marcha: recuperación en 5 s o menos.
- **Tarjeta USB genérica**: su carga FS medida con `lsusb -v`, sola y junto al Tracker en cada disposición.
- **Si tienes un hub Multi-TT**: repetir "10 OUT / 2 IN" + tarjeta detrás de él. Es barato de probar, aunque no se espera que ayude.
- El resultado decide F2b.

**Aceptación:**
- motor elegido, con las medidas en `docs/hw/`;
- 0 xruns en 30 minutos;
- tope de canales fijado;
- recuperación del hotplug sin tocar nada;
- latencia total anotada (estimación: 8–14 ms del Tracker a la grabación en la Force [est]).

### F3: Más dispositivos y monitorización

- **Enumerar el GP-150**: HS o FS, UAC1 o UAC2, frecuencias, sincronía y canales. Guardar el `lsusb -v`. Si es FS, decidir junto al Tracker con la tabla de presupuesto.
- **Monitorización por el pHAT DAC**: Force OUT 1–2 → pHAT. La salida es de línea; para auriculares exigentes, un amplificador detrás.
- La guitarra se monitoriza **en el propio GP-150**. La vuelta Force → Pi → GP-150 → Pi → Force rondará los 20–30 ms [est].
- **Generalidad:**
  - la **tarjeta USB genérica, sin perfil**: tiene que aparecer, recibir ranuras y sonar sin tocar código;
  - llenar todas las ranuras (el siguiente se aparca y se avisa);
  - provocar que se pase el presupuesto FS (se avisa antes de abrir).

**Aceptación:** soak de 60 minutos con todo conectado y 0 xruns; el mapa de canales verificado con tonos; el dispositivo sin perfil vuelve a sus mismas ranuras al reenchufarlo.

### F4: MIDI

- `f_midi` en el gadget compuesto (`bDeviceClass` EF/02/01). Comprobar que la Force sigue viendo el audio y qué hace con varios cables MIDI [?]. Si solo usa uno, todos los dispositivos van por ese cable y se distinguen por canal.
- Cualquier dispositivo MIDI USB se detecta por los eventos *announce* de ALSA seq (udev como respaldo), siempre vuelve a suscribirse y reutiliza la identidad estable.
- Se enruta a `f_midi` solo cuando `/sys/class/udc/*/state` es `configured` (como Zynthian).
- Las rutas son suscripciones de seq en el kernel. Los filtros o mapeos, si llegan, en userspace.
- Ejemplos:
  - Force → Tracker: clock y transporte (o3-303 sigue el clock; MIDI USB de o3-sdk planificado [repo]);
  - Force → GP-150: program change y CC.

**Aceptación:** la Force arranca y para el Tracker y le marca el tempo 10 minutos sin derivar, con 0 xruns de audio.

### F5: Convertirlo en un aparato

- Desde que llega la alimentación hasta que el gadget enumera: 15 s o menos. El gadget sale antes que el motor.
- **Root de solo lectura**. La config y el estado van en `/boot/firmware/rpi-audio/`, con el patrón de raspimidihub: remontar en escritura con `flock` y `sync`, dos ranuras gzip alternas (el CRC detecta escrituras cortadas) y copias de seguridad.
- `WatchdogSec` y el watchdog hardware. **Nunca reenlazar el UDC en bucle.**
- **Matriz web**: SSE, dispositivos desconectados visibles, la misma API que la CLI. No hay ninguna madura que reutilizar.
- `apt-mark hold` del kernel validado. Kernel RT solo si lo piden las medidas.

**Aceptación:** 20 cortes de corriente sin corrupción, y la Force la encuentra en todos.

### F2b: Evaluar la Pi 5

Probable: con el Tracker en "10 OUT / 2 IN" y la tarjeta USB, el presupuesto FS de la Pi 4 no llega (§2). Se hace si F2 lo confirma, o si falta CPU. Ahora solo tienes la Pi 4 (con su fuente oficial), así que habría que comprarla; con 4 GB basta.

- Con la misma tarjeta SD (o una imagen nueva) y el mismo `deploy`, comprobar:
  - el gadget en su USB-C con la Force;
  - el presupuesto FS: el Tracker y otro dispositivo FS en controladores distintos, y luego en el mismo;
  - la CPU por canal remuestreado;
  - el periodo máximo del gadget con páginas de 16 KiB.
- **Criterio:** si caben al menos dos dispositivos FS medianos y el gadget va tan bien como en la Pi 4, la Pi 5 pasa a ser la plataforma de F3 en adelante.

### F6: Ordenadores (macOS, Windows y Linux)

- **6a. Modo alterno:** el mismo gadget conectado al ordenador en vez de a la Force. Matriz de pruebas en los tres sistemas: enumeración, canales, dúplex, 10 minutos sin clics y reconexión.
  - **macOS:** UAC2 nativo; no se esperan límites.
  - **Linux:** `snd-usb-audio`; no se esperan límites.
  - **Windows:** `usbaudio2.sys` **no admite más de 8 canales en modo compartido** [repo, ADR 0012]. Hay que probar el modo exclusivo y el ASIO de cada DAW. Si da problemas, un perfil "ordenador ≤ 8 canales" que el gadget elige por configuración. Cambiar de perfil exige re-enumerar, una vez y nunca en bucle.
- **6b. Simultáneo por red:** `zita-njbridge` (Linux y macOS) o RTP/AES67 (PipeWire). En Windows no es práctico.
- **6c. Simultáneo como tarjeta USB:** una segunda Pi como gadget del ordenador, unida por Ethernet directa. Es la opción que funciona igual en los tres sistemas.

Orden recomendado: 6a en los tres sistemas, y después 6c.

---

## 4. Riesgos

| Riesgo | Probabilidad / impacto | Mitigación |
|---|---|---|
| La Force rechaza el gadget o da clics | Media / **bloqueante** | Matriz de F1; probar primero con el portátil; nombre sin "UAC2_Gadget"; solo 44,1; dúplex; conexión directa |
| **Presupuesto FS del VL805 (unos 1023 B en total)** | **Alta** con dos FS / alto | Avisar antes de abrir; perfiles del Tracker más ligeros; I2S para monitorizar; probar un MTT antes de comprarlo; Pi 5 como salida |
| **CPU de los remuestreadores en la Pi 4** (zita sin NEON; Zynthian dice que la Pi 4 se queda corta) | Media / alto | Medir en F2; zita con NEON o PipeWire; tope de canales; Pi 5 |
| Periodo máximo del gadget (64 frames con 16 ch S32; 32 con 24–26 ch) | Segura / medio | S16, `-p 64`, o módulos con `PRD_SIZE_MAX` mayor |
| `jackd` muere cuando la Force para (modo A) | Segura / bajo | Supervisor con los controles Rate, o el modo B |
| Isócrono inestable en el dwc2 | Media / alto | bint 2, `req_number`, `threadirqs`; medir con `tonecheck` (no hay debug dinámico) |
| Deriva entre relojes | Segura / medio | Puentes adaptativos; pitch del gadget en el modo B |
| **La Force exige que el IN y el OUT del gadget vayan al mismo ritmo, y que la Pi esté reproduciendo** | **Medido** / alto | Reproducción continua en el motor; los dos pitch siempre iguales (riesgo en el modo B); parche de `u_audio` en F1b |
| Latencia para tocar en directo | Segura / medio | Monitorizar en el dispositivo; compensar en la Force |
| Backfeed de VBUS o falta de corriente | Media / alto | Splitter, hub alimentado, GP-150 con su fuente, `get_throttled` |
| Orden de arranque o hotplug con la Force | Media / medio | Enumeración temprana; probar los dos órdenes |
| Actualizaciones de firmware de la Force o del kernel | Media / alto | Volver a probar tras cada actualización; `apt-mark hold` |
| Series USB de relleno o dispositivos idénticos sin serie | Media / bajo | El algoritmo de identidad (§2) |
| El UDC se bloquea tras reenlazarlo | Baja / alto | Montar el gadget una sola vez al arrancar |
| Windows y más de 8 canales en modo compartido | Alta / medio | Modo exclusivo o ASIO del DAW; perfil "ordenador ≤ 8 canales" |
| Tu Tracker en "10 OUT / 2 IN" (1083 B) pasa del presupuesto FS del VL805 él solo | **Alta** / alto | Confirmar en F2; recortar la disposición en la Pi 4; Pi 5 (F2b); a largo plazo, una disposición más ligera o High-Speed en track3r-os (§7) |
| Los módulos DKMS parcheados (32 ch) se rompen con un kernel nuevo | Media / medio | Fijar el kernel; volver a 26 ch con los módulos de serie es inmediato |
| Tocar la Force por SSH | Baja / alto | Solo lectura (regla de `CLAUDE.md`) |

---

## 5. Decisiones tomadas y preguntas pendientes

Tus respuestas del 2026-10-29:

| Pregunta | Respuesta | Efecto en el plan |
|---|---|---|
| Monitorización | Tienes un **pHAT DAC** | Force OUT 1–2 → pHAT por I2S; driver del modo B |
| Alimentación | Tienes un **splitter USB-C** | F0: comprobar con multímetro que no hay backfeed |
| Cuántos dispositivos | **El máximo posible** | Canales 16 → 26 → 32 (F1b planificado); Pi 5 evaluada en F2b |
| Licencia | **GPL-3.0-or-later** | `LICENSE` añadido; se puede reutilizar código GPL-3, Apache-2.0 y MIT |
| Ordenador | **macOS, Windows y Linux** | F6a con una matriz en los tres; perfil ≤ 8 canales para Windows si hace falta |
| SSH en la Force | **Sí**: `root@192.168.2.81`, por la Wi-Fi, con contraseña. La contraseña no se guarda en el repo | `tools/hosts/akai-force-probe.sh` (solo lectura) en cada paso de F1, con `FORCE_PASS` en el entorno |
| Pi 5 | **No**: solo la Pi 4 con su fuente oficial | F1 y F2 en la Pi 4; F2b (comprar una Pi 5) es probable por el presupuesto FS |
| Dispositivos de prueba | **Tarjeta de sonido USB, GP-150 y Tracker original con track3r-os en "10 OUT / 2 IN"** (no hay Tracker+) | Reparto de ejemplo de 18 entradas (objetivo 24×24); la tarjeta USB es la prueba sin perfil |

Pendiente:
1. **La Force no estaba en la red** el 2026-10-29 a las 15:50: en 192.168.2.0/24 solo respondían el router y el portátil. Cuando esté encendida y en la Wi-Fi, se ejecuta el primer `force-probe` (sin el gadget todavía, como línea base).
2. **¿Tienes algún hub USB, mejor Multi-TT** (`lsusb -v` dice "TT per port")? Sirve para la prueba barata de F2 antes de pensar en la Pi 5.

---

## 6. Estructura del repo

```
rpi-audio/
  CLAUDE.md                      reglas para agentes (F0)
  LICENSE                        GPL-3.0-or-later
  THIRD_PARTY.md                 avisos del código reutilizado (raspimidihub, Tractus, gaudio_ctl, drift.c)
  docs/PLAN.md                   este documento
  docs/STATUS.md                 traspaso entre sesiones
  docs/hw/AAAA-MM-DD-*.md        sesiones con la Pi y la Force, con salidas reales
  config/rpi-audio.toml        canales del gadget, motor, latencias, políticas
  config/devices.d/*.toml        perfiles opcionales (Tracker con track3r-os, GP-150, …)
  gadget/rpi-audio-gadget      configfs up/down (UAC2, +MIDI en F4)
  bridge/rpi-audiod/           supervisor: udev, identidad, presupuesto USB, puentes, ranuras, rutas, estado
  bridge/rpi-audio             CLI (status, route, unroute, assign, park)
  systemd/                       rpi-audio-gadget, el motor, rpi-audiod
  tools/pi-facts.sh, tools/deploy.sh, tools/soak.sh, tools/latency.sh
  tools/hosts/akai-force-probe.sh           diagnóstico de la Force por SSH, solo lectura
  dkms/                          módulos u_audio/f_uac2 parcheados para 32 ch (F1b)
  tests/                         pytest de la lógica pura
```

---

## 7. Para track3r-os y o3-sdk (se anota allí, no se toca desde aquí)

- **Datos que F2 les aporta:** disposiciones de "Track3r Audio" en el VL805 de la Pi 4, que tiene un presupuesto FS global. Cubre los "Hardware checks (not done)" de la enmienda 5 del ADR 0012.
- **Posibles peticiones**, según lo que salga:
  - (a) MIDI clock entrante por USB en track3r-os;
  - (b) MIDI USB en o3-sdk (M2b);
  - (c) como el presupuesto FS aprieta en la Pi 4, una disposición intermedia: "6 OUT / 2 IN" (unos 723 B) o "4 OUT / 2 IN" (unos 543 B) dejan sitio para la tarjeta USB [est];
  - (d) a largo plazo, High-Speed en el USBHS del MK66 (opción C y slice S6 del ADR 0012). Quitaría el problema de raíz, pero depende de un rutado de pines desconocido.

---

## 8. Proyectos de referencia y qué tomamos

Revisados el 2026-10-29. Ninguno hace lo que buscamos: el que más canales mueve en un gadget de Pi llega a 4 por sentido, y ninguno agrega dispositivos arbitrarios.

| Proyecto | Qué es de verdad | Qué tomamos |
|---|---|---|
| [tractusevents/tractus.piaudiointerface](https://github.com/tractusevents/tractus.piaudiointerface) (Apache-2.0) | 4 funciones UAC2 (1 in mono + 1 out estéreo cada una) + CDC en una Pi 4, con PipeWire y routers en C/C#. Probado con Windows y macOS | Su script del gadget (orden de desmontaje, serie) y su diagnóstico; la regla de WirePlumber (`priority.driver`, `pause-on-idle=false`, headroom) como plantilla del modo B; sus avisos sobre S24_3LE y el coste en endpoints |
| [lockekk/pi-gadgets](https://github.com/lockekk/pi-gadgets) (sin licencia) | UAC2 estéreo + ECM; `pw-link` desde udev con nombres fijos | Solo la idea; los nombres fijos son lo que queremos evitar |
| [AlexanderPavlenko/pi-audio-duplex](https://github.com/AlexanderPavlenko/pi-audio-duplex) (sin licencia) | UAC2 4×2 + ECM con `jackd` directamente sobre el gadget | La prueba de que `jackd` sobre el gadget funciona (`-p256 -n4`, 48k) |
| [xxie24/camilladsp-usb-dac-crossover](https://github.com/xxie24/camilladsp-usb-dac-crossover) (sin licencia) | Gadget de captura → CamillaDSP → 2 DAC USB unidos con ALSA `multi` | **Lo que no hay que hacer**: dos relojes sin compensar |
| [pavhofman/gaudio_ctl](https://github.com/pavhofman/gaudio_ctl) (GPL-3) | Vigila los controles Rate del gadget y arranca o para comandos (con filtro de 50 ms) | El patrón de arranque y parada del modo A |
| [jacob-sabella/mpc-addin-usb-audio](https://github.com/jacob-sabella/mpc-addin-usb-audio) (MIT) | Convierte un **MPC** (no la Force) en gadget UAC2 en standalone | `docs/FEASIBILITY.md` (parámetros ALSA de MPC, el filtro "UAC2_Gadget"); `src/drift.c` (control PI del pitch) |
| [macdigi/force-link-audio](https://github.com/macdigi/force-link-audio) (GPL-2) | LD_PRELOAD en la Force: saca el master estéreo por Ableton Link Audio. Probado en 3.9.1.2 | Su hook de `hw_params` para registrar qué abre MPC (solo para depurar) |
| [sd88me/force-shadow](https://github.com/sd88me/force-shadow) (MIT, archivado) | Superficie de control en pantalla para la Force. Su `forceAudioJack.so` mezcla audio de **procesos de la propia Force** en Audio-In o Out 3/4 | Contexto; nada aplicable directamente |
| [WillCMcC/mpcaudio](https://github.com/WillCMcC/mpcaudio) (sin licencia) | Firmware reempaquetado para MPC One/One+ con gadget UAC2 + MIDI | Contexto (no es la Force) |
| [MockbaTheBorg/MockbaMod](https://github.com/MockbaTheBorg/MockbaMod), [TheKikGen/MPC-LiveXplore](https://github.com/TheKikGen/MPC-LiveXplore) | SSH, imágenes y herramientas para Force y MPC | Solo si quieres SSH en la Force para depurar (riesgos: actualizaciones, eMMC) |
| [sd88me/mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins) | Catálogo e instalador "OpenMPC" | `docs/NOTES.md` y `MPC_OS_REFERENCE.md`: las mejores notas sobre el interior de la Force |
| [wamdam/raspimidihub](https://github.com/wamdam/raspimidihub) (GPL-3) | Hub MIDI USB/BT/RTP para Pi, con matriz web | `device_id.py` (identidad), la persistencia en solo lectura, el hotplug MIDI por *announce* y la UX de la matriz. No instalarlo: quiere controlar la Pi entera (isolcpus, hostapd, hostname) |
| Zynthian (GPL-3) | `alsa_in`/`alsa_out` por tarjeta con sondeo cada 2 s; gadget `f_midi` | Comprobar el estado del UDC antes de enrutar a `f_midi`. Su aviso de que la Pi 4 se queda corta remuestreando varias tarjetas |
| [falkTX/audio-bridge](https://codeberg.org/falkTX/audio-bridge) (GPL-3) | Puente JACK con VResampler, pensado para el gadget de MOD | Referencia; su modo rápido necesita un parche del kernel de MOD |
| jack-matchmaker, aj-snapshot, amidiauto | Autoconexión por nombre o regex | No: nuestras ranuras tienen que controlar las conexiones. (amidiminder: su autor prohíbe usarlo para trabajo derivado con IA) |
| Parche Farrell (LKML, julio de 2026) | `p_channels`/`c_channels` para pasar de 27 canales | Solo si hacen falta más de 26 (F1b) |
