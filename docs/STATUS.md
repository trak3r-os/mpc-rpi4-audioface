# Estado: 2026-11-11

## Actualización del 11 de noviembre (tarde): puente nativo medido con el portátil, y F5

- [Pi] **Puente nativo frente a zita, con el portátil como host:** con el margen por defecto (1,5 ms), la parte de la Pi en el viaje de ida y vuelta queda en una mediana de **6,5 ms frente a 11,7 ms de zita** (aperturas; 8,6 frente a 14,8 por el otro método). Es decir, **5–6 ms menos**, y unos 1,5–3 ms por encima del modo host. Deriva dentro de una medida: 3 tramas, frente a 84 de zita. CPU: **5,8 % de un núcleo frente a 22,4 %**. Integridad: los 26 canales a −12,0/−12,1 dBFS, en orden y sin glitches; 0 resyncs en 5 min. Con márgenes por debajo de 1,5 ms hay resyncs, de causa desconocida. Valores absolutos ±2 ms (portátil sin tiempo real). [Sesión](hw/2026-11-11-native-bridge.md).
- [ext, Pi] **Hallazgo:** sin un PCM de reproducción abierto en la Pi, el IN del gadget va a 44 000 tramas/s, no a 44 100. Por eso el viaje de ida y vuelta varía en cada apertura, con zita y con cualquier puente. No son los remuestreadores de zita, como se dijo el 2026-11-08. Está en `PLAN.md` §1.
- [Pi] Corregido y desplegado: el puente anuncia su latencia a JACK (107/104 tramas) desde la callback de latencia, y ya no se pierde al cambiar el grafo.
- [Pi] **F5, la parte que va por defecto, desplegada:** `rpi-audiod.service` con `Type=notify` y `WatchdogSec=30s`. Sigue en marcha pasados 30 s, sin reinicios, y con el proceso congelado (`kill -STOP`) systemd lo reinicia a los 30 s sin tocar el gadget. El watchdog hardware ya lo arma Raspberry Pi OS (`RuntimeWatchdogSec=1min`). La raíz de solo lectura (`--read-only`) y `--hw-watchdog` están implementados y probados en tests, pero **no se han aplicado**: cambian el arranque. [F5](hw/2026-11-11-f5-appliance.md).
- La Pi queda en Hub con zita, su configuración por defecto, sin el fichero de banco.
- **Falta:** todo con la Force; un soak de 60 min con el puente nativo, con ventilador (sin él, 72–76 °C sin la Force, y la Pi 5 recorta a 80 °C); la lista de comprobación en hardware de `--read-only`.

## Actualización del 11 de noviembre: puente nativo del gadget (sin medir con un host)

- [código] **`rpi-audio-hostbridge`** (`bridge/audio/hostbridge.c` y `hostbridge_core.h`): puente propio entre el gadget y JACK para el modo Hub, en lugar de los dos zita. Trabaja dentro de la callback de JACK sobre el buffer ALSA del gadget (mmap), sin hilo ni cola propios. Se activa con `[usb] host_bridge = "native"`; **por defecto sigue zita**. Ajustes `host_margin_ms` (1,5) y `host_quality` (32). Descripción en [OUTPUTS.md](OUTPUTS.md#puente-nativo-del-gadget-opcional).
- [repo] Núcleo comprobado en el portátil con un banco fuera del repo: senoide remuestreada 44,1 ↔ 48 kHz con la relación variando, 85–100 dB de SNR con calidad 32; el lazo simulado con ±300 ppm, paquetes de 250 µs y 300 µs de retraso aleatorio mantiene el buffer en 60–72 tramas sobre 66. Suite: los mismos resultados antes y después del cambio.
- [Pi] Compilado en la Pi 5 en un directorio temporal (con las cabeceras de ALSA copiadas: **falta `libasound2-dev`**, que `install.sh` instala ahora). 26 canales con calidad 32: ~2 % de un núcleo por sentido. **Arranque contra el gadget real sin host transmitiendo**, con un jackd `dummy` privado: abre S16_LE, buffer 1024, acepta los umbrales y el silencio automático, registra los 26 puertos, espera (captura) o recorta (reproducción) y sale limpio con SIGINT. `rpi-audiod` no se tocó.
- **Sin probar:** nada con un host transmitiendo. Falta desplegar, activar `native`, y medir con el portátil (latencia con `jack_iodelay`, integridad con `tonecheck`) y con la Force (soak, resyncs, si MPC tolera la corrección de ritmo). No hay pruebas automáticas del puente todavía.

## Actualización del 7 de noviembre: Pi 5

- [Pi, repo] **La Pi 4 se ha cambiado por una Pi 5 (1 GB) con la misma SD.** Acceso: `no3z@raspberrypi.local` (Ethernet 192.168.1.109, Wi-Fi 192.168.2.34). Las IP de la Pi 4 ya no valen.
  - Al arrancar fallaba el gadget: el overlay `dwc2` estaba bajo `[pi4]`. Movido a `[all]` (copia `config.txt.rpi-audio-20261107-154340`) y reinicio. `install.sh` ahora mira solo las secciones de `config.txt` que aplican a la placa. `fs_isoc_pad` (solo VL805) sale de modules-load.
  - Tras reiniciar: UDC `1000480000.usb`, gadget, `rpi-audiod` (Hub sobre el pHAT), UI y CPU activos; `rpi-audiod doctor` correcto salvo «UDC not attached» (no hay host conectado).
  - **Sin probar en la Pi 5:** host (portátil, Force), dispositivos USB (Tracker, GP-150, mezclador), OLED/encoder a mano y el pHAT de oído. Los dispositivos sin serie cambian de clave de slot por la nueva topología USB.
  - **Alimentación:** la fuente se ve como 3 A, así que la Pi 5 limita los USB-A a 600 mA en total. No se ha tocado `usb_max_current_enable`.

  [Sesión](hw/2026-11-07-pi5-migration.md).
- [Pi, código] **Primera prueba con la Force en la Pi 5:** enumera y MPC abre a 44,1 kHz. Los puentes del gadget no abrían en modo Hub (`u_audio` exige ≥ 4 periodos y se pedían 3): arreglado a `-n 4` y desplegado. Rutas rehechas para la nueva clave del mezclador y para el Tracker (IN 15–22, OUT 11–12). **Tracker a 8 canales reproduciendo en el RP1: 0 errores en 60 s de usbmon** (en el VL805 perdía). El mezclador, movido al bus 1 (con la GP-150 en HS), ya va en los dos sentidos (IN 1–2, OUT 3–4); sin número de serie, su clave cambia con cada puerto y hay que rehacer sus rutas. I²C de la pantalla con timeouts y `eth0` sin portadora desde que se enchufó el Tracker. Falta confirmar de oído en MPC. [Sesión](hw/2026-11-07-pi5-migration.md#primera-sesión-con-la-force-21022115).

## Actualización del 4 de noviembre

- [Pi, código] **Pérdidas multicanal por el VL805: disparador encontrado.** Se pierde el TD siguiente cuando un paquete FS isócrono llena exactamente su TRB.
  - Con un snd-usb-audio de prueba que sube `wMaxPacketSize` del Tracker (+5 % a +50 %), y con él el TRB, las pérdidas pasan a **0** a 4, 6 y 8 canales. Los controles intercalados pierden 263–351 en ~20 s.
  - Un flujo vecino en el mismo TT (mezclador Burr-Brown o el retorno del Tracker) no cambia nada.
  - Cada caso se midió una vez, ~20 s. Falta una prueba larga y comprobar la integridad del audio.
  - **Basta con +1 byte**, y en 10 min a 8 y 10 canales: 0 pérdidas (control: 811 en 2 min).
  - **Arreglo solo en la Pi:** `tools/kernel/fs-isoc-pad/`, un módulo pequeño (GPL-2.0-or-later). Para dispositivos FS tras el VL805, suma 1 byte a `wMaxPacketSize` de los endpoints isócronos IN y reconfigura una vez.
    - Probado con `insmod` y el snd-usb-audio de serie: 0 pérdidas a 4, 8 y 10 canales. Tras `rmmod` vuelven.
    - **Instalado** por `tools/deploy.sh`: DKMS más `modules-load`, solo con VL805; idempotente.
    - En uso real con rpi-audiod, Tracker a 8 canales, paquete de 721: 0 malos en 20 s.
    - Falta un arranque en frío, una prueba con el Force y comprobar la integridad con una señal conocida.
  - Restaurado: el snd-usb-audio de serie, sin módulos de prueba.
  - Incidencia: un cambio directo 8 duplex → 4 out dejó el USB del Tracker colgado hasta apagarlo.
  - El Tracker está ahora directamente en el hub VIA, y la Pi en Wi-Fi (192.168.2.229).

  [Detalle](hw/2026-11-04-pi-usb-host.md#flujo-vecino-en-el-mismo-tt-y-trb-más-largo-que-el-paquete-noche).
- [Pi, usuario, repo] **Parámetros xHCI de prueba en el VL805: descartados.** Revisión de Fable y comprobación propia sobre las capturas: **cada pérdida sigue a un paquete de tamaño máximo (45 tramas)**, y solo con datos reales (parado = ceros = 0 pérdidas). Hay además completados retrasados un microframe, casi siempre en esos paquetes. Kernel 6.18.50 parcheado (tryboot, una vez) que declara al VL805 maxp/ESIT/avg mayores para FS isócrono IN tras TT. El controlador acepta los valores (comprobado en debugfs), pero **las pérdidas no cambian** (4 canales: 1014 → 1042/1034 con +17/+50 %). A 8 canales el VL805 no admite más de ~756 B. TTT no se probó. El prearmado en el Tracker ya había fallado en otra sesión, así que no es que el Tracker rearme tarde. Restaurado y verificado; Tracker en perfil 2, reproduciendo. [Detalle](hw/2026-11-04-pi-usb-host.md#patrón-de-pérdidas-y-parámetros-xhci-de-prueba-61850-parcheado).
- [Pi, usuario, repo] **Kernel 7.3.1 (tryboot) y A/B parado/reproduciendo:** 7.3.1 compilado y arrancado una vez en la Pi, sin tocar `config.txt`; no arregla nada (39 pérdidas a 8 canales reproduciendo, y rechaza 10). **Hallazgo: en el VL805 las pérdidas solo aparecen con el Tracker reproduciendo** (6.18, mismo hub: parado 0, reproduciendo 67). Por el xHCI interno reproduciendo hay 0. Hacen falta las dos condiciones a la vez; que parado signifique datos a cero se vio después (véase la línea anterior). Restaurado y verificado, sin ficheros de prueba. [Detalle](hw/2026-11-04-pi-usb-host.md#kernel-731-de-prueba-tryboot-y-ab-tracker-paradoen-reproducción).
- [Pi, código, ext] **Causa de las pérdidas en el VL805 identificada:** la traza xHCI (`tools/xhci-error-trace.sh`) muestra que cada paquete `-18`/0 B del Tracker a 8 canales es un **Missed Service Error del VL805**, uno a uno (148/148; 136/136 con y sin carga de memoria). No es un error de bus, de CPU, de memoria ni de cola. No hay firmware VL805 posterior a 138C0 ni quirk o parámetro que lo corrija. El USB-C de la Pi 4 no puede ser gadget y host a la vez. Por el xHCI interno, 8/10/11 canales van limpios. **A/B con el mismo hub Fresco: en el VL805, 40 pérdidas a 8 canales y 4 a 10; en el interno, 0.** El hub no lo arregla. Opciones: estéreo FS en el VL805, dispositivo HS (sin medir) o Pi 5/CM5 (sin probar). [Traza y conclusión](hw/2026-11-04-pi-usb-host.md#traza-en-el-vl805-el-controlador-declara-missed-service).
- [Pi, usuario, repo] **xHCI interno comprobado con otro hub:** Fresco Logic 1d5c:5012 Multi-TT por USB-C sí enumera el Tracker, firmware original y kernel sin cambiar. **8/10 canales: 59 978/59 999 paquetes sin errores en 3 × 20 s por perfil. Once canales: 60 004 paquetes sin errores en un minuto continuo**, sin descartes ni `missed` durante el flujo. **8 OUT / 2 IN dúplex con retorno de silencio**, ~20 s sin errores en captura/reproducción/feedback. Cambian controlador y hub; falta A/B con el mismo hub. **Restaurado arranque original**, usuario devuelve Tracker directo al USB-A azul; Master estéreo → DAC 100 %, servicios activos, **19 992 paquetes finales sin errores, descartes, missed ni xruns**. [Resultados y límite de usar USB-C como host/gadget](hw/2026-11-04-internal-xhci-tracker.md).
- [Pi, usuario, repo] **Ensayo USB-C autorizado, sin enumeración:** activado `otg_mode=1` por nueva opción de deploy con copia de reversión; tras reiniciar aparece xHCI interno `fe9c0000.xhci`, pero ningún Ugreen 20265 ni Tracker por splitter 8086 + adaptador USB-C/USB-A. No hay captura de audio del controlador interno. **Restaurado arranque idéntico y segundo reinicio**, gadget/audio/UI activos. De vuelta al USB-A azul, el Genesys/ASIX negocia también USB3: 8/10 canales siguen con **42/3 errores en ~20 s**. Final estéreo: **19 994 paquetes sin errores, descartes, missed ni xruns**, Master → DAC 100 %, v1.1.0 original. Suite **458 correctos, 13 omitidos**. [Ensayo y límites](hw/2026-11-04-pi-usb-host.md#ensayo-autorizado-con-el-xhci-interno-sin-enumeración).
- [Pi, ext, usuario, repo] **Alternativa USB-C contrastada:** `otg_mode=1` permite probar el xHCI interno, pero ocuparía el puerto actualmente usado por el gadget UAC2/MIDI hacia la Force. Preparado borrador local, sin aplicarlo ni reiniciar. **El splitter 8086 ya documentado no lleva VBUS en USB2 DATA; el Tracker no se enciende ahí y el modo host no lo remedia.** Hace falta resolver la conexión/alimentación física antes. Tracker anuncia solo 44,1 kHz. Reanálisis usbmon: errores individuales `-18`/0 B y URB global 0; la incidencia bulk #7737 no demuestra la misma causa. [Contraste y límites](hw/2026-11-04-pi-usb-host.md#contraste-de-la-propuesta-usb-c-con-xhci-interno).
- [Pi, usuario, repo] **Contraste con portátil y Genesys Multi-TT:** revisadas capturas ALSA de 60 s/perfil 2–10 OUT limpias en Intel xHCI (sin usbmon host; el contador de paquetes del informe es de preparados en el Tracker). En la Pi, con Genesys 05e3:0610 Multi-TT activo, siguen **54/5 pérdidas en ~20 s a 8/10 canales**. ALSA directa con las condiciones del portátil: **32/14997** en ~15 s; USB directo con libusb, sin ALSA/JACK y colas de 1/8/32 paquetes por transferencia: **29/25/32 errores** en ~15 s. VL805 000138c0 actualizado, ASPM desactivado, AER y throttling 0. No hay arreglo probado en el puente de audio; foco USB core/xHCI/VL805 e interoperabilidad. Estado final estéreo: **19996 paquetes sin errores, descartes ni xruns**. [Método, límites y corrección del supuesto límite de once canales](hw/2026-11-04-pi-usb-host.md).
- [Pi, unidad, repo] **Prototipo USB IN instalado y descartado como solución.** Imagen reproducible y revisada, 13 pruebas host dirigidas, 150 USB con sanitizadores, 20 target y 3 QEMU correctas; SRAM_U +1024 B dentro del presupuesto. En la unidad, doble prearmado sigue perdiendo **203/448/161/12 paquetes en ~20 s con 4/6/8/10 canales**. No demuestra mejora útil ni resuelve la causa. **Restaurada v1.1.0 (a3fe987526ec)** y Master estéreo → DAC al 100 %; comprobados **19 995 paquetes sin errores, descartes ni xruns adicionales** tras restaurar. Tracker 44,1 kHz, DAC Pi 48 kHz. [Prueba y límites](hw/2026-11-04-tracker-prearm-hardware.md).
- [Pi, repo] [Investigado el código USB del Tracker](hw/2026-11-04-tracker-usb-code.md). La causa sigue sin aislar entre host/hub/dispositivo; la nueva medida en cuatro canales pierde 139 intervalos en ~12 s, sin aumento de errores del controlador del Tracker y con ISR máximo 64,4 µs. Preparado [prototipo de dos paquetes IN prearmados](../tools/hosts/tracker-usb-prearm/README.md), 13 pruebas host correctas; el original falla el escenario nuevo de interrupción diferida. **No probado ni instalado en la unidad**: requiere gate de memoria/target y A/B real. La Pi vuelve al Master estéreo limpio.
- [Pi] **Matriz del Tracker completada:** 2 canales sin pérdidas; 4/6/8/10 dan 233/433/195/23 paquetes erróneos respectivamente en ~20 s; 11 se enumera pero el controlador rechaza abrirlo por ancho de banda (`-28`). Captura ALSA directa y buffer mayor tampoco limpian cuatro canales. Estéreo con retorno de silencio abierto: ~20 s sin errores en captura/reproducción/feedback. Confirmación final solo captura estéreo: **59 990 paquetes en ~60 s, cero errores USB, cero bloques descartados y cero xruns adicionales**. Queda Master estéreo → DAC, retorno cerrado sin rutas. Este es el máximo limpio comprobado hoy, no un límite teórico de dos canales. [Matriz y límites](hw/2026-11-04-tracker-matrix.md).
- [Pi, repo] Añadido **Status → WiFi** en el OLED, con conexión, red, IP y señal. Reutiliza la consulta en segundo plano de Connections. Instalado y comprobado en la Pi. **453 pruebas correctas, 13 omitidas**; flake8 y espacios correctos. [Sesión](hw/2026-11-04-tracker-lineout.md).
- [Pi, usuario] Tracker → LineOut del pHAT: faltaba la ruta del Master al DAC. Con ocho canales USB seguían los artefactos: 30 paquetes de captura erróneos en 3 s en dúplex y 55 en 6 s sin retorno. El tono directo por el DAC suena bien. **Estado final: Tracker en 2 OUT / 2 IN, captura estéreo → local-dac, retorno cerrado porque no tiene rutas; el usuario confirma «Suena limpio» y usbmon registra 0 errores en 4997 paquetes (~5 s).** El cambio de perfil es de ejecución, sin guardar el proyecto del Tracker; una carga de proyecto o reinicio puede reponer ocho canales. Sigue pendiente resolver el flujo de ocho canales; no se atribuye todavía al host o firmware. En Hub, los puentes de reproducción USB físicos se abren solo si alguna ruta los tiene como destino. [Pruebas y límites](hw/2026-11-04-tracker-lineout.md).
- [Pi, repo] Menú **Power → Shut down / Restart**, con confirmación que selecciona Cancel por defecto y bloqueo de órdenes repetidas mientras se tramita. Reiniciar conserva los ajustes. Privilegio limitado a los dos comandos exactos de systemctl, verificado con `sudo -l` sin ejecutarlos. **451 pruebas correctas, 13 omitidas**; instalado solo UI/permisos y manual actualizado. Audio conserva PID 305906. No se ha apagado ni reiniciado la Pi para probarlo; falta comprobar el ciclo completo. [Sesión](hw/2026-11-04-power-menu.md).
- [Pi, código, usuario] El usuario seguía viendo pausas durante el giro continuo. Capturadas ráfagas de errores I²C incluso en comandos de cuatro bytes mientras GPIO seguía leyendo. Con el encoder quieto, 450 cambios de prueba sin errores ni eventos GPIO. La selección pasa a flecha sobre negro y el driver transmite solo columnas modificadas: mover el cursor entre nombres cortos cambia dos bloques de cuatro bytes en vez de dos páginas de 128. Reintentos de 10–50 ms sin apagar/reinicializar el OLED ante errores de transferencia; invalidación de páginas parcialmente escritas. Tras instalar la última versión, el usuario confirma **«Smooth now»** girando con placa/cables quietos. No se da por resuelto el origen eléctrico/de driver de los fallos. [Sesión y límites](hw/2026-11-04-encoder-bus.md).
- [repo, Pi] **437 pruebas correctas, 13 omitidas**; 91 dirigidas UI/render/servicio, flake8 y espacios correctos. UI actualizada por `tools/deploy.sh --ui-only`, copia `/var/backups/rpi-audio-ui.twWwZ3/ui`. Audio conserva PID 305906; servicios activos y sin reinicios automáticos. Las notas siguientes conservan los resultados de sus revisiones originales.

## Conexión wifi actual (4 de noviembre)

- [Pi] Red `bender_5G`, IP **`192.168.2.229`**, nombre `raspberrypi.local`, usuario SSH `no3z`. Verificada la clave del host conocida por Ethernet. Ethernet está sin enlace en esta sesión.
- [Pi, código] En pantalla: **Status → WiFi** o **Connections → WiFi**. Muestra la dirección que tenga actualmente la Pi; DHCP puede cambiarla. Última lectura: conectada, señal 100 %.

## Actualización del 3 de noviembre

- OLED/encoder: errores I²C recientes en el journal (22:54:55 y 22:55:32), sin reinicios automáticos ni throttling. Todo el I²C pasa ahora a un trabajador con un único frame reemplazable y reconexión cada segundo; el bucle GPIO no espera al bus. Menú principal con primera fila negra, cabeceras oscuras y menos líneas decorativas/estado repetido. Instalado con `tools/deploy.sh --ui-only`, conservando el PID 305906 del audio. Prueba sintética en la Pi con OLED real bloqueado a propósito: 101 detents, mediana 1,990 ms/máximo 2,708 ms por iteración, solo dos frames enviados y último estado correcto. Falta valoración del encoder físico y confirmar el origen eléctrico/de driver de los errores. Detalle al final de [la sesión](hw/2026-11-03-oled-wifi.md).
- Pi 4 accesible por Ethernet `192.168.1.106` y wifi `192.168.2.229`, conectado a `bender_5G`. Zona `Europe/Madrid` y reloj sincronizado por NTP.
- OLED con Overview, indicadores, conexiones/mapas, medidores y salvapantallas Status. Perfiles de host con reservas, copia completa o enlace a escena; estado Ready/Partial/Error con motivos. Cuatro niveles independientes para DAC/envío USB/RTP/Link. Contadores e historial recogidos aunque el OLED duerma y conservados durante el mismo arranque. Sesión y copias previas: [2026-11-03-oled-wifi.md](hw/2026-11-03-oled-wifi.md).
- Verificación actual: 433 pruebas locales correctas, 13 omitidas por dependencias/entorno; flake8 de UI/pruebas modificadas, sintaxis de deploy.sh y espacios correctos. Las seis pruebas nativas de ganancia/observador/medidor y las cinco de red se ejecutaron en revisiones anteriores, sin cambios posteriores en su código nativo. Pruebas físicas Hub USB, Ableton Live y valoración del encoder pendientes.
- Última consulta: Hub con pHAT activo a 48 kHz, periodo 256 y buffer ALSA 768 frames; sin host USB ni fuentes USB físicas. Red de audio desactivada. Servicios de audio/UI activos, sin rearranques automáticos. Verificada conservación de sesión durante un reinicio controlado de rpi-audiod.
- [Manual ilustrado en inglés](MANUAL.md), [HTML](manual/index.html), [salidas y menús implementados](OUTPUTS.md) e [investigación de proyectos de red](NETWORK_RESEARCH.md). Modo Hub con DAC+USB+red, RTP/PCM con SDP por HTTP y Link Audio del SDK oficial. No se añaden módulos de kernel; recepción de red y AES67 completo quedan pendientes. Ver límites de pruebas físicas en OUTPUTS.md.
- Se mantiene el gadget en **26×26**, también al cambiar escenas, por indicación del usuario. El kernel actual no expone p_channels/c_channels; 32×32 requeriría trabajo independiente en el módulo. El manual añade [BOM y montaje](MANUAL.md#16-build-your-own-device), separando componentes comprobados, sustitutos sin probar y piezas cuyo modelo no está identificado.

El resto conserva las notas y resultados históricos, con sus fechas originales. La indicación antigua de wifi sin configurar queda sustituida por esta actualización.

## Resumen histórico del 30 de octubre (21:15)

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

## Hub autónomo con pantalla (2026-11-01)

Idea del usuario: la Pi como hub sin host (Tracker en "2 OUT / 2 IN", mezclador, GP-150, MIDI), con salida por el Tracker y por el pHAT DAC, controlada desde un OLED con encoder, y **sin perder** el modo con la Force.

- **Hecho y desplegado en la Pi 4 [Pi]** (detalle en `docs/hw/2026-11-01-hat-oled.md`):
  - **OLED SH1106 128×64 en 0x3C** funcionando, con el menú de `rpi-audio-ui.service` (habilitado, `deploy.sh --enable --hat`). Fuente 5×7, 21 columnas × 8 filas.
  - **encoder** mueve el cursor; **PUSH** y **BACK** funcionan. La pantalla se apaga a los 60 s sin tocar nada y el primer toque solo la enciende.
  - el pHAT DAC aparece como tarjeta ALSA `sndrpihifiberry` y un tono por ella termina bien; **no sé si se oye** [?].
- **Modo `standalone` (`docs/STANDALONE.md`):**
  - jackd con el pHAT como driver (solo reproducción) y sin esperar al host; el pHAT es un destino más de las rutas (`local-dac`). Con la Force no cambia nada: es `[engine] mode`, por defecto `host`.
  - **probado en la Pi [Pi]:** jackd arranca sobre `sndrpihifiberry` (48 kHz, 256×3) y el usuario dice que `route usb-mixer local-dac` hecho desde la pantalla suena por el pHAT ("funciona", 2026-11-01). Fue una prueba temporal (`systemd-run`, unit `sa-try`), con `rpi-audiod.service` parado; **no está instalado como modo permanente** (`deploy.sh --host standalone` lo haría y la Pi dejaría de servir a la Force hasta quitarlo).
  - **MIDI entre dispositivos** (`midiroute`/`midiunroute`, `bridge/rpi-audiod/midiroute.py`): suscripciones `aconnect` entre los puertos MIDI de dos dispositivos USB, en los dos modos, guardadas en `slots.json` (`midi_routes`) y en los presets. En standalone el servicio es dueño de todas las suscripciones entre dispositivos; con host solo de las que él hizo. Pantalla: menú MIDI. **Probado solo con el `World` falso**, no con dispositivos MIDI reales [?].
- **Hecho en el repo [repo]:**
  - **rutas dispositivo→dispositivo** (`bridge/rpi-audiod/routing.py`, comandos `route`/`unroute`, clave `routes` de `slots.json` y de los presets, campo `routes` del status, `docs/MIDI.md`). Son conexiones JACK entre los puentes, por pares estéreo, y no tocan las del gadget. Un dispositivo nunca se enruta a sí mismo. Sin nivel por ruta: JACK suma y los niveles son los del dispositivo (`volume`). **Nunca probadas con aparatos reales**, solo con el `World` falso de `tests/test_supervisor.py`.
  - **pantalla:** modelo (`ui.py`), driver SH1106 sin dependencias salvo smbus2 (`sh1106.py`), fuente y render, decodificador del encoder y botones (`inputs.py`), bucle del servicio (`uiservice.py`) y el programa `rpi-audio-ui`. Los comandos van por `rpi-audiod cmd TEXTO`. Ajustes en `[ui]` de `config/rpi-audio.toml`. El audio no depende de la pantalla. Simulador en `tools/ui-sim.py`, capturas de hardware con `tools/panel-test.py` y `tools/oled-test.py`.
  - `install.sh`/`deploy.sh --hat`: I2C, overlay del pHAT, `i2c-dev` al arrancar y el servicio de la pantalla (sus ficheros se instalan siempre, solo se habilita con `--hat`).
  - `pytest -q tests`: 276 pasan, `flake8` limpio.
- **Falta:**
  - **CONFIRM:** en GPIO 23 no llegaba (contacto intermitente). El 2026-11-02 el usuario movió CONFIRM al GPIO 5 (pin 29) y BACK al GPIO 6 (pin 31); por defecto en `inputs.PINS`. Sin confirmar que CONFIRM llegue [?].
  - **sentido del encoder:** la primera versión iba al revés; está corregido y el usuario no lo ha confirmado [?].
  - **el Tracker en 2/2:** consumo desde la Pi 4 (1,2 A en total en los USB-A), enumeración, y si su Master de 2 canales incluye el retorno (posible bucle si se enruta de vuelta) [?]. El usuario no tiene acceso al Tracker ahora.
- `deploy.sh`/`install.sh` reinician `rpi-audiod` (la Force oye un corte): no se despliega esto con ella transmitiendo.

## Hecho

- **Repo:** rama `main` en `github.com/trak3r-os/rpi5-audioface` (alias SSH `github-trak3r`), autor `trak3r-os` con el correo oculto de GitHub. `LICENSE` (GPL-3.0-or-later), `CLAUDE.md`, `.gitignore` (`out/`), `.flake8`.
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
