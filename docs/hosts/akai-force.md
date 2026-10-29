# Host: Akai Force (y otros MPC de inMusic)

Ficha de un host concreto. El código de rpi-audio no depende de ella; aquí se recoge qué hay que configurar para que este host acepte el gadget y cómo trata el audio por dentro. La evidencia detallada está en `docs/PLAN.md` §1, en `docs/hw/2026-10-29-force-baseline.md` y en `docs/hw/2026-10-29-f1-force.md`. Lo marcado [Force] sin más es de la Force del usuario con **MPC 3.9.1.2** (probe del 2026-10-29).

## Requisitos

| Requisito | Valor en `gadget.env` | Fuente |
|---|---|---|
| Solo **44.100 Hz**. Con otra frecuencia, MPC se queda en 2-in/2-out | `GADGET_SRATE=44100` | [ext] log de un MPC One; notas de la Force 3.1.1: "sample rate is locked to 44.1 kHz" |
| Formato: MPC usa **S32_LE** con su códec interno; con el gadget acepta S16_LE | `GADGET_SSIZE` 2 o 4 | [Force] |
| Periodo de **128**, fijo: no hay ajuste de buffer en standalone. Buffers de 256 en captura y 384 en reproducción (el periodo de la Pi es independiente) | — | [Force] |
| **Entrada y salida al mismo ritmo.** MPC enlaza los dos streams (`snd_pcm_link`) y no tolera que el IN y el OUT del gadget vayan a ritmos distintos | Pitch igual en los dos sentidos | [Force], `docs/STATUS.md` |
| **Nunca "UAC2_Gadget"** en el nombre: MPC ignora esas tarjetas | `GADGET_PRODUCT`/`GADGET_MANUFACTURER` | [ext] mpc-addin-usb-audio |
| MPC abre primero la captura; hay que ofrecer los dos sentidos | Las dos máscaras de canales | [ext] |
| Hasta 32 IN / 32 OUT. "32 I/O" es una casilla de Preferencias; sin ella, MPC solo ofrece la entrada 1&2 | `GADGET_CHANNELS` ≤ 27 con el kernel de serie | [Force], [ext] |

## Comportamiento que hay que tener en cuenta

- **Solo usa un dispositivo de audio a la vez.** "Audio Device" es una única selección; ninguna versión hasta la MPC 3.10 (octubre de 2026) añade agregados ni "interno más externo". En los foros, la respuesta de siempre es "una interfaz a la vez", y para más canales, ADAT en la misma interfaz. [ext] notas de versión, KB de Akai, mpc-forums
- Al elegir una interfaz externa, **la Force apaga su audio interno**: entradas, salidas, auriculares y volumen. La escucha tiene que salir por la Pi. [ext]; [Force] ADA2 queda cerrada mientras MPC usa el gadget.
- **Cue:** Preferences > General > "Audition Outputs" puede mandarse a cualquier par de la interfaz. La mezcla principal/cue de los auriculares se pierde, porque ese control es del camino interno. [ext] foro (elektronauts, 2024)
- Cada pista, submezcla o pad puede salir por cualquier par de la interfaz, y cada pista de audio elige su entrada. [ext] KB de Akai, bonedo
- Abre las interfaces externas por índice (`hw:N`), y el índice cambia según lo que haya enchufado. [Force]
- Su USB host es un EHCI detrás de su hub interno (USB5537B), compartido con su SSD y su lector SD. Hay que conectar la Pi **directamente** a un USB-A de la Force, no a través de un hub externo. [Force]
- Las actualizaciones de firmware han roto interfaces que antes funcionaban (las notas de la 3.8, 3.9.1 y 3.10 citan modelos concretos): hay que repetir la prueba tras cada actualización. [ext]
- MIDI en el mismo dispositivo USB que el audio: hay un caso de chasquidos con una XR18 que se arreglaron quitando el envío de clock a ese puerto. A tener en cuenta en F4. [ext] mpc-forums, agosto de 2026

## Cómo usa ALSA MPC

- **ALSA directo** (`libasound`), sin JACK ni PulseAudio, sobre JUCE (hay hilos "JUCE Timer" y "JUCE MIDI Input"). No hay `/etc/asound.conf`. [Force]
- Funciones de PCM que importa: `writei`/`readi`/`writen`/`readn`, `snd_pcm_link`, `snd_pcm_start`, `snd_pcm_wait`, `poll_descriptors*`, `recover`, `rewind`/`forward`. **Ninguna de mmap.** Un shim con `LD_PRELOAD` tiene que interceptar las cuatro de lectura y escritura. [Force]
- `RW_INTERLEAVED`; `start_threshold` = boundary (arranca él mismo con `snd_pcm_start`); `stop_threshold` = el buffer. [Force]
- Trabaja por dentro con 32 canales por sentido: el aviso `inefficient … path: hardware=N filter=32` sale con cualquier tarjeta. [Force] el aviso; [est] la interpretación.
- Encuentra su códec por `/dev/snd/by-path/platform-sound`, que en la Force apunta a ADA2. [Force] el enlace; [ext] que MPC lo use así (mpc-addin-usb-audio, medido en una MPC Key 37).

### Hilos [Force]

| Hilo | Política | CPU |
|---|---|---|
| `AudioWorker0`…`AudioWorker3` | SCHED_RR 20 | uno fijado en cada núcleo (0–3) |
| `Audio Processing` | SCHED_RR 20 | 3 |
| MIDI (`MIDI`, `MIDI Out: …`, `JUCE MIDI Input`) | SCHED_RR 10 | — |
| `FileIO`, `JUCE Timer` | SCHED_RR 1 | — |
| `AudioWatchdog` | normal | 0 |

El kernel arranca con `isolcpus=2-3`. Es `PREEMPT_RT` con `HZ=1000`. [Force]

## Códec interno (ADA2) y relojes

- **Es una tarjeta de plataforma, no USB:** el I2S del RK3288 (`ff890000`) más un DAC sin interfaz de control. El device tree la declara `inmusic,ada2-audio` / `inmusic,ada2-audio-codec` (driver `SND_SOC_ROCKCHIP_INMUSIC_JP07`). [Force]
- 2 entradas y 4 salidas, solo 44,1 kHz, sin controles de mezclador en ALSA. Salidas 1/2 = main y 3/4 = Out 3/4; si los auriculares cuelgan de 3/4 está sin confirmar. [ext] `openAZ0x/meta-az0x` (driver reescrito a partir del del fabricante), force-shadow; [?] los auriculares
- **I2S con el DAC como maestro de BCLK/LRCLK** (`jp07_get_dai_fmt: … fmt=0x00001001`, `SND_SOC_DAIFMT_CBP_CFP`), pero el reloj maestro (MCLK) se lo da el SoC. [Force]
- **MCLK:** `i2s0_clkout` = **11.289.600 Hz** (256 × 44.100), sacado de `cpll` (400 MHz) con el divisor fraccionario. `cpll` y los PHY USB de 480 MHz salen del mismo cristal, `xin24m`. [Force] `clk_summary`
- **Consecuencia [est]:** ADA2 y una interfaz USB asíncrona que sigue los frames USB de la Force (el gadget con el pitch en 1,0) van con el mismo cristal: no derivarían entre sí. Si la Pi mueve el pitch (modo B de `docs/PLAN.md`), sí. **Sin medir:** exige tener las dos tarjetas abiertas a la vez en la Force.

## Add-ons de MockbaMod [Force]

- El sistema raíz se monta en solo lectura. `az01-launch-MPC` ejecuta `/media/662522/boot.sh` si existe; es la SD de MockbaMod, y desde ahí MPC arranca con `LD_PRELOAD` de `/media/662522/AddOns/`: `mockbaMagic.so`, `libforce_cursor.so` y `tkgl_anyctrl_lt.so`.
- MockbaMagic avisa de que no soporta la 3.9.1.2 ("currently not supported").
- El kernel no trae `snd-aloop`: en la Force no se puede crear una tarjeta virtual. Sí trae `USB_F_UAC2`, configfs y `DWC2` en modo dual, y MPC enlaza `libusbgx` (su gadget del Controller Mode [ext]).

## ¿Varias interfaces a la vez?

| Opción | Estado |
|---|---|
| Que MPC abra dos tarjetas | No existe [ext] |
| **Que la Pi agregue N dispositivos y la Force vea una sola interfaz** | Es rpi-audio. Límite: 32 canales por sentido |
| Dos funciones UAC2 en el gadget, o dos Pis | No aporta: MPC abre una sola tarjeta [est] |
| ADA2 + la Pi, con un shim `LD_PRELOAD` que reparta los canales de MPC entre las dos | Técnicamente viable: el patrón existe (abajo) y los relojes coinciden en modo A [est]. Exige código en la SD de MockbaMod y depende de la versión de MPC |

## Proyectos que tocan el audio de MPC

| Proyecto | Qué hace | Licencia |
|---|---|---|
| [macdigi/force-link-audio](https://github.com/macdigi/force-link-audio) | Shim en la Force: intercepta `hw_params` y `writei` y saca el master por Ableton Link Audio | GPL-2.0+ |
| [sd88me/force-shadow](https://github.com/sd88me/force-shadow) (`forceAudioJack.so`) | Shim en la Force: intercepta `readi`/`writei` y mezcla audio de procesos propios en la entrada o en Out 3/4 | MIT |
| [jacob-sabella/mpc-addin-usb-audio](https://github.com/jacob-sabella/mpc-addin-usb-audio) | MPC (no Force) como gadget UAC2; `docs/FEASIBILITY.md` mide cómo usa ALSA MPC | MIT |
| [WillCMcC/mpcaudio](https://github.com/WillCMcC/mpcaudio) (`addon/tee/mpc_uac2_tee.c`) | MPC One: mantiene el códec interno y copia salida y entrada a un gadget; corrige la deriva saltando o repitiendo un frame cada 100 ms (±226 ppm) | Sin licencia: solo leer |
| [openAZ0x/meta-az0x](https://github.com/openAZ0x/meta-az0x) | BSP abierto de las placas AZ0x de inMusic, con el driver del códec y de la placa | MIT |
| [sd88me/mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins) `docs/NOTES.md` | Notas sobre la Force: hilos de audio, trampas de `LD_PRELOAD` (un add-in que exporte `dlsym` rompe a los demás) | — |
| [TheKikGen/MPCLiveXplore-libs](https://github.com/TheKikGen/MPCLiveXplore-libs) | Solo MIDI (`tkgl_anyctrl`), no toca el PCM | CC BY-NC 4.0: no es compatible con GPL |

## Diagnóstico

Si tiene SSH (MockbaMod), `tools/hosts/akai-force-probe.sh` lee, sin escribir nada:
- las tarjetas ALSA y cómo ve los descriptores del gadget (`stream0`);
- los `hw_params` que elige MPC y su línea de log "Audio …; N-in; N-out";
- la versión de MPC, sus `LD_PRELOAD`, sus hilos de tiempo real y los símbolos de ALSA que usa;
- el device tree y el reloj del códec interno.

`tools/hosts/akai-force-watch.sh` sigue los punteros de los streams de MPC.

En la Force solo hay BusyBox: `head -n N`, nunca `head -N`.
