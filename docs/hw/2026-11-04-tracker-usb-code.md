# 2026-11-04: origen de las pérdidas USB y prototipo de prearmado

Continuación de [la matriz del Tracker](2026-11-04-tracker-matrix.md). El usuario pregunta de dónde viene el fallo y si puede optimizarse por código.

## Lo comprobado y lo que falta

- [Pi, repo] El error está antes del DAC y del remuestreador: hay paquetes USB isócronos fallidos y descarte de bloques dentro del Tracker. La captura ALSA directa también lo reproduce. Ni el número de xruns de JACK ni el tamaño del buffer ALSA permiten diagnosticar por sí solos estas pérdidas.
- [repo] Análisis de las trazas anteriores: los URB válidos tenían una edad mediana de ~11 997 µs desde su envío al controlador; los fallidos, ~12 998 µs. También los paquetes que fallan llevan mucho tiempo encolados. No hay huecos entre completados mayores de 3 ms en esas ventanas. Esto no apunta a una falta de suministro de la aplicación de audio, pero no identifica todavía qué sucede dentro del controlador/hub/dispositivo.
- [ext, código] En el [driver xHCI de Raspberry Pi](https://github.com/raspberrypi/linux/blob/rpi-6.18.y/drivers/usb/host/xhci-ring.c), `-EXDEV` (`-18`) aparece al perder un intervalo de servicio o descartar una transferencia isócrona. Los errores de transacción USB y los desbordamientos se distinguen. Ese estado no basta para culpar exclusivamente al firmware del Tracker.
- [ext, código] El [driver de audio USB](https://github.com/raspberrypi/linux/blob/rpi-6.18.y/sound/usb/endpoint.c) mantiene transferencias de captura de hasta un milisegundo en Full-Speed y una cantidad fija de URB. Aumentar el buffer PCM no equivale a aumentar el número de paquetes de captura USB preparados.
- [Pi] Nueva ventana de unos doce segundos en cuatro canales: `iso_in_missed` aumenta **139** y los bloques descartados **38**; los contadores de errores del controlador USB del Tracker no cambian. Su tiempo máximo acumulado de ISR sigue en **11 592 ciclos = 64,4 µs**, sin alcanzar el límite de vueltas del ISR.
- [límite] Ese máximo mide la duración del ISR una vez que entra, no la latencia desde que el hardware solicita la interrupción. Los contadores del dispositivo tampoco descartan errores físicos de su transmisión IN, sin ACK isócrono. No se concluye «el cable está bien» ni «la IRQ nunca llega tarde» a partir de esas lecturas.
- [límite] Intento de traza xHCI detallada: el kernel deniega la escritura del filtro de eventos con EPERM, incluso en el diagnóstico por sudo. No se obtiene esa traza. Se deja deshabilitado el evento del espacio de trazas temporal y se restaura el Master estéreo → DAC.

## Código examinado

- [repo] Firmware en la unidad: v1.1.0, identificador de build a3fe987526ec. Ese commit está en el checkout público `../track3r-os/build-public/track3r-os-v1`, no en el historial del repo de desarrollo. El header USB examinado coincide con el de la versión pública; no se confunde el identificador de build con el HEAD de desarrollo.
- [código] `usb/include/o3os/usb/device.h`: `UsbBuffers` tiene un único `iso_in`; `arm_iso_in()` prepara un solo descriptor. `token_iso_in()` lo repone al procesar la interrupción de la transferencia anterior. OUT ya mantiene los dos descriptores preparados.
- [código] El controlador y `PingPong` admiten dos descriptores, pero no es seguro dar ambos al hardware usando el mismo buffer de muestras. Para aprovecharlos hay que mantener dos buffers independientes hasta completar cada transferencia.
- [código] USB tiene prioridad 64 y el render 128, por lo que el diseño permite que USB interrumpa el render. La cifra de carga de audio, por sí sola, no demuestra que el render impida atender USB.

## Experimento preparado

- [repo] Parche de revisión: [prearmado de dos paquetes IN](../../tools/hosts/tracker-usb-prearm/0001-prearm-two-iso-in-packets.patch), con [alcance y requisitos](../../tools/hosts/tracker-usb-prearm/README.md). Se conservan separados del firmware por la regla de CLAUDE.md que reserva los cambios de `../track3r-os` a su propio trabajo.
- [código] Dos buffers IN, uno por paridad del descriptor; prearmado de ambos y reposición del que queda libre. El feedback y la recepción no se cambian. El coste es un buffer adicional (~1 KiB), un paquete extra de precola/cebado y hasta dos construcciones de paquete en una llamada inicial.
- [repo] Prueba nueva con el controlador simulado: el host completa un paquete, pasa al frame siguiente y sondea de nuevo antes de atender el ISR. La versión actual no tiene segundo paquete; el prototipo responde a ambos y recupera el orden de descriptores después. Se ejecuta para 2/4/6/8/10/11 canales.
- [repo] Con el código original: **12 casos existentes pasan; la prueba nueva falla**. Con el prototipo: **13 casos pasan**, incluyendo secuencia de muestras, retorno, feedback, arranque/parada y reset del bus. Compilación host con warnings como errores; `git apply --check` correcto contra la fuente pública. Resultados iniciales con la librería local; se recompila además desde las fuentes USB actuales para evitar depender de un archivo estático antiguo.
- [límite] El simulador no modela tiempos de bus, CRC ni el traductor de transacciones del hub. La prueba demuestra tolerancia a una interrupción diferida, no que esa sea la causa física de las pérdidas ni que la optimización las elimine en la Pi.
- [pendiente] Antes de probar la imagen: mapa real SRAM_U y gates de compilación/target del Tracker. Después, comparación A/B de pérdidas en 4/8/10 canales y pruebas con retorno. Once canales tiene además el rechazo de ancho de banda del host; este parche no elimina esa restricción.
- [Pi] No se flashea la unidad ni se guarda su proyecto. Queda de nuevo en captura estéreo hacia LineOut, sin ruta de reproducción de retorno. Scripts, capturas y binarios de ensayo en `out/2026-11-04-tracker-code/`, ignorado por git.
