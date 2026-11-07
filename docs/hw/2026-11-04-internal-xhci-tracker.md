# Tracker por xHCI interno: 8, 10 y 11 canales sin errores USB medidos

Continuación de [las pruebas por VL805 y el primer intento USB-C](2026-11-04-pi-usb-host.md). El usuario vuelve a conectar por USB-C usando **otro hub**, con pantalla/red y más funciones. Se reutiliza la autorización expresa del ensayo temporal y la restauración posterior; no se pide otra aprobación del mismo cambio.

## Configuración y controladores comprobados

- [Pi] Raspberry Pi 4 Model B Rev 1.5, kernel **6.18.50+rpt-rpi-v8**, firmware original del Tracker **v1.1.0 (a3fe987526ec)**. Proyecto `12guitareno` reproduciéndose a **98 BPM**. Sin cambios de kernel, EEPROM ni firmware del Tracker.
- [Pi] `tools/deploy.sh --usb-c-bench host` sustituye el overlay periférico por `otg_mode=1` bajo `[pi4]`, con la copia de reversión comprobada de la sesión anterior. Tras reiniciar aparece **`/sys/devices/platform/scb/fe9c0000.xhci/usb3`**. El Tracker enumera por ese controlador, **sin pasar por el VL805 PCIe**.
- [Pi, usuario] Ruta nueva: **USB-C de la Pi → splitter 8086 → hub Fresco Logic 1d5c:5012 → Tracker a 12 Mbit/s**. El modelo comercial del nuevo hub no se identifica. Su descriptor ofrece TT por puerto y tiene **alternate setting 1 activo**. En otra rama aparecen un hub Genesys, lector microSD, Ethernet Realtek y audio C-Media; no se abren sus flujos ni se accede a sus ficheros para estas pruebas.
- [Pi, límite] Antes del ensayo, en un arranque posterior a la sesión previa, se observó `throttled=0x50000` y un aviso de baja tensión seguido de normalización. Tras el reinicio del ensayo y durante las medidas se comprueba **`throttled=0x0`**. El aviso anterior no explica por sí solo las pérdidas previas, que se habían medido con 0x0.
- [Pi] En modo xHCI interno no existe UDC para el gadget. El servicio gadget falla y el daemon de audio queda inactivo por su dependencia de systemd; la UI y SSH por WiFi permanecen disponibles. Las medidas siguientes usan **ALSA directa**, sin JACK, zita, DAC ni remuestreo de la Pi. No hay escucha por LineOut durante este modo de ensayo.

## Captura sin retorno

Perfiles `8 out`, `10 out` y `11 out`, PCM S16_LE a **44 100 Hz**, buffer ALSA de 200 ms. Se comprueba la ruta `fe9c0000.xhci` después de cada reenumeración. Cada ventana de 20 s de usbmon queda dentro de una grabación de 24 s, tras arrancar el flujo; el estado de paquetes se lee de los descriptores isócronos completados del host, no del contador de paquetes preparados en el Tracker.

| Canales | Ventanas usbmon | Paquetes completados | Erróneos | Vacíos | Bloques descartados adicionales en las grabaciones |
|---|---|---:|---:|---:|---:|
| 8 | 3 × 20 s | **59 978** | **0** | **0** | **0** |
| 10 | 3 × 20 s | **59 999** | **0** | **0** | **0** |
| 11 | 1 × 20 s | **19 997** | **0** | **0** | **0** |

- [Pi] Las siete ejecuciones de arecord terminan con código 0; cada WAV contiene **1 058 400 frames** (24 s). Las duraciones de pared rondan 24,07–24,12 s, incluido el arranque. Todos los estados de paquete observados son 0; no hay tamaños que rompan un frame PCM.
- [Pi] Tamaños de paquete de datos: 704/720 B para ocho canales, 880/900 B para diez, **968/990 B para once**. Once canales abre y transmite aquí: el rechazo `-28` del VL805 no era una imposibilidad universal del firmware o del tamaño máximo de paquete Full-Speed.
- [Pi, límite] Al comparar contadores antes de abrir y después de cerrar cada grabación, `missed` sube **30** en cada ejecución de 8/10 y **29** en la primera de 11. Esos deltas abarcan arranque/parada; no se presentan como cero ni se confunden con errores del host dentro de las ventanas observadas. Para comprobar el flujo continuo se hace la medida siguiente.

## Once canales: un minuto continuo y contadores con el flujo activo

- [Pi] Grabación ALSA de **66 s**, con **60 s continuos de usbmon** dentro. Los contadores inicial/final del Tracker se consultan después de arrancar y antes de detener arecord, manteniendo el flujo abierto.
- [Pi] **60 004 paquetes**, **0 erróneos**, **0 vacíos**, **0 tamaños inválidos**. Delta de contadores durante el flujo: **0 nuevos starts, 0 underruns, 0 bloques descartados y 0 missed**. El contador de preparados sube 60 196 entre consultas, un intervalo algo mayor que la ventana de usbmon; no se usa como recuento del host.
- [Pi] WAV con **2 910 600 frames** a 44,1 kHz, exactamente 66 s; arecord termina con código 0 en ~66,091 s de pared. No se comprueban sesiones de una hora ni se declara estabilidad ilimitada.

## Dúplex: 8 OUT / 2 IN

- [Pi] Perfil `8 duplex`, arecord de ocho canales y aplay de dos canales simultáneos, ambos a S16/44,1 kHz y buffer de 200 ms. Aplay envía **silencio**; no se realimenta el Master ni se prueba el contenido de un retorno musical.
- [Pi] Ventana usbmon de ~20 s dentro de flujos de 27 s; contadores del Tracker consultados con ambos flujos activos:

| Endpoint | Paquetes | Erróneos | Vacíos |
|---|---:|---:|---:|
| Captura IN | **19 999** | **0** | **0** |
| Reproducción OUT | **19 999** | **0** | **0** |
| Feedback IN | **20 000** | **0** | **0** |

- [Pi] Arecord y aplay terminan con código 0; **0 nuevos starts, 0 underruns de captura, 0 bloques descartados y 0 missed** entre consultas durante el flujo. Los contadores de retorno mantienen **0 empty, 0 bad, 0 dropped-frames y 0 underruns**. No se convierte la prueba de silencio en una comprobación de escucha del retorno.

## Alcance y restauración

- [Pi, límite] **El Tracker original puede transmitir once canales en esta misma Pi por otra ruta USB**. También se ha abierto 8/2 dúplex sin errores USB medidos. No se necesita el prototipo de prearmado para conseguir estos resultados.
- [usuario, límite] Cambian **controlador y hub externo** respecto a las medidas con VL805/Genesys. El usuario no tiene el adaptador necesario para conectar este mismo hub por USB-A. Por tanto, no hay A/B con el mismo hub: los resultados apuntan a una dependencia de la ruta/controlador/hubs, sin separar driver, firmware del controlador, hardware VL805 y hub integrado VIA.
- [repo, límite] Esta es una comparación de transporte, no un arreglo instalado del flujo VL805. Usar el USB-C como host impide usar ese mismo puerto simultáneamente como gadget UAC2/MIDI hacia la Force. No se da por resuelto el uso final con la Force ni la escucha multicanal a través del daemon.
- [Pi] Después de cada ensayo se restaura el perfil **2 OUT / 2 IN** del Tracker. Se copian todas las grabaciones y resultados al ordenador **antes de reiniciar**, porque `/tmp` en la Pi es tmpfs. A continuación se ejecuta `--usb-c-bench restore`, se comprueba que `config.txt` es idéntico a la copia original y se reinicia. La conexión física del Tracker debe volver al USB-A para recuperar la escucha.
- [repo] Scripts, cuatro carpetas de resultados, WAV, usbmon y volcados en `out/2026-11-04-pi-usb-host/internal-xhci-results/`, ignorado por git. No se guardan números de serie ni salidas en bruto en esta nota.

## Estado final verificado después de restaurar

- [usuario, Pi] El usuario conecta el Tracker **directamente a un USB-A azul**, sin el hub externo. Vuelve a la ruta VL805 → VIA integrado → Tracker. `config.txt` idéntico al original, UDC `fe980000.usb`, gadget/audio/UI activos, `throttled=0x0`.
- [Pi] Tracker original **2 OUT / 2 IN**, captura activa y retorno parado; proyecto reproduciéndose. Hub de la Pi a **48 kHz, 256 × 3**, Master estéreo → pHAT DAC activo al **100 %**.
- [Pi] Comprobación final ~20 s: **19 992 paquetes, 0 erróneos, 0 vacíos, 0 tamaños inválidos, 0 bloques descartados, 0 missed y 0 xruns adicionales**. Captura y estado conservados en `rpi-audio-internal-xhci-restored/` dentro de la carpeta de evidencia local.
