# 2026-11-04: pausas y parpadeo al girar el encoder

## Evidencia [Pi, usuario, código]

El usuario confirma que mover el I²C a un trabajador no eliminó las pausas. Journal de la UI: ráfagas de EIO al girar, con recuperación después de uno o dos segundos, sin avisos de bucle de entrada lento. UI/audio activos y sin reinicios automáticos; `get_throttled=0x0`.

- Traza de 30 s durante la prueba física solicitada: **10 EIO**, **826 lecturas GPIO**; GPIO sigue recibiendo eventos durante los fallos de pantalla. Los ioctl fallidos medidos duran aproximadamente **0,2–10,9 ms**. El retraso fijo de recuperación y la reinicialización completa añadían demora visible.
- Debug temporal del controlador I²C: fallos también con comandos de **4 bytes** y con inicialización de 24 bytes, además de datos de 129 bytes. El controlador anota error `0x400` (longitud/estado). Fuente del driver consultada como referencia: [i2c-bcm2835.c de Raspberry Pi](https://github.com/raspberrypi/linux/blob/rpi-6.18.y/drivers/i2c/busses/i2c-bcm2835.c). No se atribuye el EIO por sí solo a una pieza concreta.
- Prueba de carga con la UI detenida y restaurada mediante trap: las primeras **148** alternancias de cursor con bloques de 128 bytes terminan antes de la ráfaga de errores durante el giro. Los tamaños menores también fallan durante esa ráfaga, incluidos comandos cortos. Esta prueba alternaba filas rápidamente; el usuario comunica parpadeo intenso. Se reconoce que el test lo provocaba, se detiene y no se repiten pruebas visuales rápidas.
- Repetición con el encoder quieto y lectura GPIO paralela: **150 frames por tamaño, 128/32/16 bytes**, **0 errores y 0 eventos GPIO**. Medianas de dos páginas: **24,598 / 29,102 / 35,123 ms**. Reducir el tamaño máximo por transacción no se adopta: no arregló las ráfagas y añade sobrecarga.
- Solo la UI tiene abierto `/dev/i2c-1`. Pinmux correcto en GPIO 2/3 (SDA/SCL) y 17/27 (encoder). El usuario indica que placa/cables están mayormente firmes, aunque podrían moverse algo. Contacto, ruido o alimentación compartida son hipótesis; no hay medición eléctrica ni componente defectuoso identificado. El debug del kernel queda restaurado a **0**.

## Cambios y comprobaciones [código, repo, Pi]

1. Reintento desde **10 ms**, con crecimiento limitado a **50 ms**. Un EIO no provoca cerrar el descriptor ni ejecutar repetidamente el apagado/encendido de la inicialización. Solo se reabre un adaptador retirado o descriptor inválido. Conserva el último frame y aplica el más reciente tras la recuperación.
2. Una página se invalida antes de enviarla. Si un envío parcial falla y el siguiente frame vuelve a los píxeles previos, se vuelve a escribir la página: no se confía en una caché que ya no representa la RAM.
3. Selección con **flecha blanca sobre negro**. Se elimina la inversión completa de la fila, conservando nombres, iconos, estados y tamaños de texto. El driver calcula el primer y último byte cambiado de cada página. Una navegación entre etiquetas cortas envía dos bloques de **4 bytes de imagen**, frente a dos de 128; los offsets de columna se recalculan incluyendo el margen SH1106.

La versión intermedia con reintentos rápidos pero reinicialización tras tres errores **no** resolvió el problema: el usuario seguía viendo pausas/parpadeo. Journal de esa revisión: recuperación entre **23 ms y 1,295 s**. Queda sustituida por la versión que no reinicializa ante EIO y usa flecha/columnas modificadas.

Instalación final con `tools/deploy.sh --ui-only`, copia previa `/var/backups/rpi-audio-ui.twWwZ3/ui`; reinicio exclusivo de la UI. Audio mantiene PID **305906** durante toda la sesión, sin tocar red, arranque, gadget ni conexiones de audio.

**437 passed, 13 skipped** con tomli como tomllib en Python 3.10; **91 pruebas dirigidas** de UI/render/servicio. Incluyen una ráfaga de siete fallos sin reinicializar/apagar, reapertura de adaptador retirado, reparación de página parcial, columnas con offsets mayores que 15 y verificación de dos spans de cuatro bytes al mover el cursor. Flake8 y espacios correctos. Manual/capturas regenerados y vista móvil de Outputs revisada visualmente.

## Resultado y límites [usuario, Pi]

Después de instalar la última versión se solicita girar sujetando placa y cables quietos; el usuario responde **«Smooth now»**. Esta confirmación valida la sensación de manejo en esa prueba, sin aislar cuánto aporta sujetar el cableado frente al nuevo render/transporte. No se declara eliminado el origen del fallo I²C: la revisión final registra todavía una ráfaga con recuperación de **0,401 s** tras ocho errores durante la comprobación. La mejora de interfaz y recuperación queda instalada; no se hacen cambios físicos remotos ni más pruebas visuales de parpadeo.

Trazas y scripts de diagnóstico en `out/`, ignorados por Git. Los resultados nativos de audio de sesiones anteriores no se repiten porque esta sesión cambia exclusivamente Python de UI/driver y documentación.
