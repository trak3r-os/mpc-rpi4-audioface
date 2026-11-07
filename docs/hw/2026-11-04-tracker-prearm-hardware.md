# 2026-11-04: prueba del prearmado USB IN en el Tracker

Continuación de [la investigación de código](2026-11-04-tracker-usb-code.md). El usuario autoriza compilar, instalar y probar el prototipo («dale», después «continua»), y confirma que el proyecto musical está guardado.

## Imagen y comprobaciones previas

- [repo] Copia aislada de la fuente pública de la versión instalada, a3fe987526ec. No se cambia el checkout de desarrollo de track3r-os ni se publica ninguna release. Rama de ensayo `fix/usb-in-prearm`, commit final **8be92e993c832d964bcb097ea6bfa40ddd0f7267**, etiqueta local **v1.1.0-usbpre.2**. El parche de revisión queda en [tools/hosts/tracker-usb-prearm](../../tools/hosts/tracker-usb-prearm/README.md).
- [repo] Revisión de riesgo y revisión independiente del código: APPROVE tras corregir la etiqueta de área de la suite QEMU nueva. Revisión independiente del manifiesto, memoria, SHA y CRC: APPROVE para ensayo, sin afirmar que sea una solución.
- [repo] **13/13 casos host dirigidos**, incluidos datos no nulos en orden durante la interrupción diferida; **150/150 casos USB con ASan/UBSan**; **20/20 ctests del target** y **3/3 suites USB Cortex-M4F QEMU**.
- [repo] Dos compilaciones target nuevas con HEX idéntico. Check_image **9/9**, flashconfig exacta `ffffffffffffffffffffffffdef9ffff`, SP `0x20030000`, imagen contigua `0x00000000..0x000F0FFF`, final alineado a 4 KiB. Compilador Arm GNU 15.3.Rel1, MinSizeRel, 44,1 kHz, sin audio de prueba ni comandos bench añadidos. El propósito de la imagen es exclusivamente el ensayo.
- [repo] FLASH con padding **987136 B**, sin cambio de extensión respecto a la base. SRAM_U **138320 B**, frente a **137296 B**: **+1024 B** tras alineación. De 196608 B quedan 58288 B tras estáticos; reservados 24576 B de pila y 32768 B de suelo libre, sobran **944 B** sobre ambas reservas. SDRAM_STATIC **160384 B**, sin cambio.
- [repo] Fichero de ensayo **o3os-usbpre2.ptf**, 16 caracteres. SHA-256 `8704a1019f66171351539b5cda98fbda1207d450e706b2e277f5b8dec6e53de4`, CRC32 **28EBA485**. Imagen, fuentes aisladas, manifiesto y salidas en `out/2026-11-04-tracker-prearm-hw/`, ignorado por git.

## Instalación y condiciones

- [Pi, unidad] La tarjeta ya contiene la versión conocida **track3r-os-v1.1.0.ptf**. Su verificación previa por la vía documentada `fw arm`, CRC **34F94820**, termina correctamente. No se sobrescribe ese fichero ni se tocan los firmwares originales del usuario.
- [unidad] Instalación de la candidata con el `o3console.py` del proyecto: `--put`, validación de nombre/tamaño/CRC en la tarjeta, `--update` con nonce del dispositivo y comprobación de versión al volver. Arranca **v1.1.0-usbpre.2 (8be92e993c83)**. No se usa SWD ni el botón de reset; la primera imagen del directorio de firmware se conserva.
- [unidad] Se recupera el mismo proyecto musical y tempo **98 BPM**. Se reactiva la reproducción para medir con carga musical. Pi en Hub, DAC a 48 kHz, Tracker a 44,1 kHz, zita 256×2. DAC silenciado durante cada actualización y devuelto al nivel original (100 %) al escuchar. Sin host USB conectado a la Pi.
- [código, unidad] La pregunta del usuario sobre la frecuencia se responde con los estados reales: **Tracker 44,1 kHz; DAC de la Pi 48 kHz**. Zita convierte entre los relojes; esta prueba no cambia las frecuencias. Las capturas ALSA directas anteriores ya perdían paquetes a 44,1 kHz sin zita ni DAC, por lo que no se atribuye el fallo únicamente a 44,1 → 48.

## Matriz de captura, veinte segundos por perfil

| Canales del Tracker | Errores antes, versión original | Errores con prearmado doble | Bloques descartados con prearmado | XRuns adicionales con prearmado |
|---|---:|---:|---:|---:|
| 2 | 0 / 19995 | **0 / 19995** | 0 | 0 |
| 4 | 233 / 19995 | **203 / 19994** | 58 | 0 |
| 6 | 433 / 19995 | **448 / 19995** | 134 | 0 |
| 8 | 195 / 19995 | **161 / 19995** | 41 | 0 |
| 10 | 23 / 19995 | **12 / 19995** | 1 | 0 |

- [Pi] Mismo proyecto y tempo; ventanas cortas en momentos distintos. Las diferencias de recuento no prueban mejora estadística. **4–10 canales siguen perdiendo paquetes: el parche no cumple el criterio de aceptación.** Los paquetes fallidos siguen vacíos; no aparecen tamaños de trama incompletos.
- [unidad] Lectura final con la candidata: **0 underruns de audio, 0 late/slips/hwfault**, ISR USB máximo **17198 ciclos = 95,5 µs**, sin alcanzar el límite de vueltas. No se interpreta el máximo de este arranque como un delta CPU directamente comparable al máximo acumulado del arranque anterior.
- [límite] No se amplía a dúplex ni a once canales con esta candidata: ya falla la aceptación en captura sola y once tenía rechazo previo de ancho de banda sin cambios de descriptor. No se afirma ninguna mejora de recepción de retorno con esta imagen.

## Decisión

- [Pi, código] Se rechaza el prototipo como solución al ruido. La prueba simulada de tolerancia a interrupciones sigue siendo válida, pero no identifica la causa física observada. El problema de 4–10 canales continúa acotado a transporte/controlador/hub/dispositivo; no se atribuye exclusivamente al firmware del Tracker ni al remuestreador de la Pi.
- [unidad] Restaurada por la vía documentada **v1.1.0 (a3fe987526ec)**, CRC **34F94820**, conservando el proyecto y los ficheros del usuario. Se elimina únicamente la candidata de ensayo que se había añadido a la tarjeta; el parche y la imagen verificada se conservan localmente para revisión.
- [Pi, unidad] Estado final: **2 OUT / 2 IN**, reproducción USB cerrada sin rutas, Master estéreo → pHAT DAC, nivel de DAC **100 %**, música en marcha. Confirmación de ~20 s tras restaurar: **19 995 paquetes USB, cero errores/vacíos, cero bloques descartados, cero paquetes perdidos según el Tracker y cero xruns adicionales**. Los servicios de audio/UI de la Pi permanecen activos.
