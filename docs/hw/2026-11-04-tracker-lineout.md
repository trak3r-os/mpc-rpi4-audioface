# 2026-11-04: Status WiFi y Tracker por LineOut

## Wifi y pantalla

- [Pi] Pi 4 por `bender_5G`, `192.168.2.229`; Ethernet sin enlace. SSH verifica la clave conocida de `192.168.1.106` con HostKeyAlias, sin desactivar su comprobación.
- [código, Pi] **Status → WiFi** abre la vista existente de conexión, nombre, IP y señal, alimentada por el trabajador de telemetría. Se conserva Connections → WiFi. Comprobado importando la UI instalada con telemetría real: conectada a bender_5G, IP correcta, señal 100 %.
- [Pi] Primer despliegue con `tools/deploy.sh --ui-only`, copia `/var/backups/rpi-audio-ui.IS5TS7/ui`; después despliegue completo para la mitigación del audio, con `tools/deploy.sh` por wifi.

## Silencio y artefactos

- [Pi] Tracker v1.1.0 en **8 OUT / 2 IN**, 44,1 kHz, ocho canales de captura y dos de retorno, Full-Speed. Hub sobre pHAT a 48 kHz, periodo 256, tres periodos; puentes zita 256×2. Sin otro host USB.
- [Pi] No había ruta del Tracker al DAC, solo rutas antiguas de dispositivos ausentes. Conectados Master L/R (7–8, cuarto par) a `local-dac`. La señal pasa por `level_dac_out` y llega a `system:playback_1/2`.
- [usuario] Se oye, con muchos chirps; tras cerrar el retorno no utilizado describe el ruido residual como «brrrr» intermitente, no saturación continua. Altavoces por entrada de línea.
- [Pi] Sin throttling (`0x0`), governor performance, hilos de audio FIFO. Los medidores pasivos no registran xruns durante las muestras del ruido. La sesión acumula un xrun durante las interrupciones/rearranques de diagnóstico; no se usa ese total para negar las pérdidas USB.
- [Pi] Ocho canales, retorno abierto: usbmon captura 30 paquetes IN erróneos de 2998 en ~3 s, estado `-18`, longitud 0. También 251 errores de feedback. La señal JACK antes y después de ganancia al 100 % coincide muestra a muestra: en 4 s, 49 saltos superiores a 0,5 de escala completa en R, pico 0,9985.
- [Pi] Captura ALSA directa, sin JACK ni zita, cuatro segundos a S16/44,1 kHz/ocho canales: solo captura, pico Master L/R 0,4027; en dúplex con retorno de silencio, R llega a 0,9725 y aparecen 34 saltos superiores a 0,5. Se restaura el servicio tras cada prueba. Esto reproduce una parte del fallo antes del DAC y del remuestreador, sin aislar todavía controlador USB frente a firmware.
- [Pi] Los contadores del Tracker muestran aumento de `in_dropped_blocks` y `iso_in_missed`; el audio interno no registra underruns. Los contadores de mezcla también tienen saturaciones históricas y actividad del limitador, pero no bastan para explicar el ruido descrito.

## Mitigación de Hub

- [código] Hub abre un puente de reproducción USB físico solo si alguna ruta guardada tiene ese dispositivo como destino. Quitar la última ruta cierra el puente y libera su presupuesto. Añadir una ruta lo vuelve a abrir. No reinicia la captura ni el reloj local. Host y standalone conservan su comportamiento.
- [código] Readiness acepta una asignación de reproducción guardada sin stream activo en Hub cuando el perfil no requiere una ruta hacia ella. Una ruta que sí necesita esa reproducción sigue mostrando Waiting si no está disponible. Se conservan las comprobaciones de capacidades y dispositivos ausentes.
- [Pi] Desplegado y verificado: captura del Tracker activa, reproducción cerrada, ruta al DAC aplicada. En seis segundos desaparecen los picos grandes de la grabación JACK (pico L/R ~0,405; ningún salto >0,5), pero usbmon sigue dando 55 errores de captura en 5997 paquetes. **El usuario sigue oyendo barridos:** cerrar el retorno no resuelve todo el fallo de ocho canales.
- [Pi, usuario] Bajada temporal de DAC al 40 % para descartar saturación. Tono directo de 440 Hz, cinco segundos, amplitud 0,1, S32/48 kHz por el pHAT: **«pitido OK»**. Se restaura la música y después el nivel original del DAC (100 %).

## Estado final y límites

- [Pi] Guardado el mapa de stems previo en `out/`; era el de fábrica: T1–T6 y Master L/R. Cambio de ejecución con `usb profile 2`, conservando el ajuste de retorno; el descriptor sigue ofreciendo **2 OUT / 2 IN**, pero Hub no abre la reproducción porque ninguna ruta la usa. Ruta anterior del Master sustituida por el primer par estéreo → `local-dac`.
- [Pi, usuario] **4997 paquetes de captura sin errores en ~5 s**, frente a las pérdidas del modo de ocho canales. El usuario confirma **«Suena limpio»**. Es una prueba corta, no un soak.
- [límite] Se escucha el Master estéreo; no se transportan stems independientes en esta configuración. El cambio del perfil USB del Tracker es de ejecución y no se guarda su proyecto; reiniciar o cargar un proyecto puede restaurar otro perfil. No se modifica ni instala firmware del Tracker. La causa de las pérdidas con ocho canales queda pendiente en PLAN §7.
- [repo] **453 pruebas correctas, 13 omitidas**. Incluyen ciclo sin retorno → ruta de retorno → quitar ruta → reabrir, conservación de captura/reloj y readiness de asignaciones ociosas. Python local 3.10 usa tomli como sustituto de tomllib para ejecutar las pruebas; flake8 y `git diff --check` correctos. Manual inglés/HTML regenerado.
- [privacidad] Grabaciones, mapas y diagnósticos en `out/2026-11-04-tracker-lineout/`, ignorado por git; sin identificadores privados ni audio en el repositorio.
