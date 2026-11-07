# 2026-11-04: matriz de canales USB del Tracker

Continuación de [Tracker → LineOut](2026-11-04-tracker-lineout.md), a petición del usuario: probar más configuraciones y determinar hasta dónde funciona el montaje actual.

## Montaje y método

- [Pi] Tracker original con track3r-os v1.1.0, Pi 4/VL805 por hub interno Single-TT, sin otras interfaces USB de audio. Pi en Hub sobre pHAT DAC, 48 kHz, 256×3; Tracker S16 a 44,1 kHz, puentes zita 256×2. DAC al 100 %. La canción continúa durante los cambios de perfil.
- [Pi] Cambios de ejecución con `usb profile N`, conservando la preferencia de USB RETURN y sin guardar el proyecto ni instalar firmware. A partir de diez canales este firmware no presenta retorno, aunque su preferencia siga On. El Master siempre se enruta al DAC, último par en perfiles pares. El ensayo vuelve a estéreo en su limpieza final.
- [Pi] Cada muestra dura 20 s tras estabilización y recoge completados USB isócronos de captura con usbmon. Se cuentan todos los paquetes erróneos/vacíos, la alineación a tramas, el incremento de bloques descartados y la diferencia del contador de xruns del observador. Las consultas CDC se hacen fuera de la ventana usbmon. Los errores de captura encontrados tienen estado `-18` y longitud 0.
- [límite] Son muestras cortas con una canción concreta, no una certificación para cualquier carga ni un soak largo. El intento auxiliar de grabación JACK de la primera matriz no pudo crear su fichero por permisos del directorio temporal; los resultados siguientes se basan en usbmon y contadores, no en esas grabaciones. La grabación posterior de 2/2 sí se realizó tras ajustar el directorio temporal.

## Captura, sin abrir reproducción en el Tracker

| Canales que envía el Tracker | Mapa de fábrica | Paquetes en ~20 s | Erróneos/vacíos | Bloques descartados adicionales | XRuns adicionales |
|---|---|---:|---:|---:|---:|
| 2 | Master L/R | 19 995 | **0** | **0** | 0 |
| 4 | T1–T2 + Master L/R | 19 995 | 233 | 65 | 0 |
| 6 | T1–T4 + Master L/R | 19 995 | 433 | 129 | 0 |
| 8 | T1–T6 + Master L/R | 19 995 | 195 | 52 | 0 |
| 10 | T1–T8 + Master L/R | 19 995 | 23 | 4 | 0 |
| 11 | T1–T9 + Master L/R | No abre | Rechazo de ancho de banda | — | — |

- [Pi] Todos los paquetes válidos tienen un número entero de tramas. El modo de diez canales transmite y pierde menos en esta muestra que 4/6/8, pero **no es limpio**. La cantidad de pérdidas no es monotónica con el número de canales; esta tabla no demuestra que sean proporcionales al uso de CPU o a bytes/s.
- [Pi] Once canales se enumera, pero no se activa ni en zita ni en ALSA directo. El kernel informa `Not enough bandwidth for altsetting 1` y `usb_set_interface failed (-28)`. El presupuesto agregado estimado por rpi-audiod (990 B < 1099 B) no basta para predecir la aceptación de este endpoint por el controlador; no se interpreta como un fallo del remuestreador.
- [Pi] El intento de once canales no llegó a aplicar un mapa personalizado; al fallar la apertura se restauró el perfil estéreo. No se cambia el mapa de stems guardado del usuario.

## Comprobación de buffers sin el puente

Captura ALSA directa con rpi-audiod parado temporalmente, sin JACK/zita y sin reproducción USB. Cada ventana usbmon dura ~8 s dentro de una captura de diez segundos; el servicio y la ruta estéreo se restauran al terminar.

| Canales | Periodo ALSA | Buffer ALSA | Paquetes | Erróneos |
|---|---:|---:|---:|---:|
| 4 | 256 | 1024 | 7997 | 67 |
| 4 | 1024 | 4096 | 7998 | 33 |
| 11 | 1024 | 4096 | No abre | Rechazado por USB, `-28` |

[Pi] Aumentar buffers no elimina las pérdidas de cuatro canales. No se instala ese cambio como solución. Comparar muestras de distinta duración/canción/fase no permite atribuir la reducción de 67 a 33 únicamente al buffer.

## Estéreo con retorno abierto

- [Pi] Perfil **2 OUT / 2 IN**, ruta Master → DAC y ruta temporal `usb-host` → Tracker, sin host USB conectado: se abre reproducción de silencio, sin realimentar el Master a sí mismo.
- [Pi] En ~20 s: **19 995 paquetes de captura, 19 996 de reproducción y 19 995 de feedback; cero errores y cero vacíos en los tres endpoints**. Cero xruns adicionales; el reporte posterior del Tracker da cero underruns de retorno.
- [Pi] Grabación JACK de ocho segundos: picos Master L/R 0,4051/0,4074, ningún salto entre muestras superior a 0,5 de escala completa. No prueba la recepción audible de una fuente real en el Tracker: el retorno de esta prueba es silencio.
- [límite] La consulta CDC `usb audio` inicial agotó su plazo de tres segundos; la ventana usbmon y el reporte posterior sí terminaron. No hay delta fiable de contadores internos de captura para esta fila. Las cifras de cero errores se refieren a usbmon y al observador.
- [Pi] La ruta temporal al Tracker se elimina al terminar; vuelve a captura estéreo → DAC, reproducción USB cerrada.

## Evidencia y pendientes

- [Pi] Confirmación final en **2 OUT / 2 IN con reproducción cerrada**, Master → DAC: **59 990 paquetes de captura durante ~60 s, cero errores/vacíos, cero bloques descartados, cero paquetes perdidos según el Tracker y cero xruns adicionales**. Esta es la configuración de escucha que queda activa. El perfil sigue siendo de ejecución, sin guardar el proyecto del Tracker.
- [Pi] Artefactos y scripts temporales en `out/2026-11-04-tracker-matrix/` (ignorado por git); copias remotas en `/tmp/rpi-audio-tracker-matrix/`. Sin audio, series ni salidas en bruto en git.
- [?] Resolver las pérdidas de 4–10 canales exige investigar controlador/transporte/firmware; no quedan explicadas por xruns de JACK ni desaparecen con captura directa y buffer mayor. No se modifica track3r-os desde este repositorio.
