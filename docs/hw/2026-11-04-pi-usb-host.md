# 2026-11-04: contraste con el portátil y diagnóstico del USB de la Pi

El usuario aporta capturas limpias en este portátil, vuelve a conectar el Tracker a la Pi y pide investigar la Pi. Firmware del Tracker **v1.1.0 (a3fe987526ec)**, proyecto musical a **98 BPM**.

## Evidencia del portátil

- [repo, usuario] Leídos el script, `matrix.log`, volcados CDC y cabeceras WAV de la sesión que el usuario indica en `/tmp/`. Copia de los textos y cabeceras en `out/2026-11-04-pi-usb-host/pc-reference/`; no se incorpora audio ni datos privados a git.
- [repo, usuario] Captura ALSA directa `hw:Track3r,0`, S16, 44,1 kHz, buffer de 200 ms, 60 s por perfil **2/4/6/8/10 OUT**, retorno no presentado. Todos los WAV contienen **2 646 000 tramas**; arecord tarda ~60,013–60,016 s, sin errores ni bloques descartados en los contadores del Tracker. Esto contrasta con las pérdidas crecientes de la Pi y demuestra capacidad multicanal en esas condiciones.
- [límite] El script del portátil llama `d_packets` al incremento del contador `in_packets` del Tracker: son paquetes **preparados por el dispositivo**, no un recuento directo de paquetes recibidos por el host. Sin usbmon no existe en esa sesión un recuento independiente de estados host `-18`. El tiempo de captura, los contadores y la escucha aportan evidencia fuerte de funcionamiento, pero no se renombra ese contador como una medida que no es.

## Topología real de la Pi

- [Pi] Pi 4, kernel **6.18.50+rpt-rpi-v8**, controlador VL805 por PCIe 5 GT/s. Al conectar directamente el Tracker aparece detrás del hub integrado **VIA 2109:3431, Single-TT**.
- [Pi, usuario] El usuario conecta el hub del portátil a los USB azules. La nueva ruta es **VL805 → VIA integrado → Genesys 05e3:0610 → Tracker**. Genesys negocia a 480 Mbit/s; descriptor de TT por puerto y **alternate setting 1** seleccionado: Multi-TT activo. El Tracker sigue a **12 Mbit/s**. El mismo hub contiene una interfaz Ethernet ASIX; no se modifica su configuración de red.
- [ext, código] Un TT traduce las transacciones hacia el dispositivo Full-Speed; Single-TT y Multi-TT son configuraciones distintas del hub. La [documentación oficial de Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#single-tt-usb-hubs) describe esa diferencia. El VIA es parte de la Pi: no se puede trasladar por separado al portátil como si fuese el hub externo.

## Medidas con Genesys, firmware original

Hub de audio de la Pi a 48 kHz, Tracker a 44,1 kHz. Se hace sonar el proyecto; solo captura, puente de reproducción USB cerrado. Muestras usbmon de ~20 s:

| Canales | Paquetes de captura | Erróneos/vacíos | Bloques descartados adicionales | XRuns adicionales |
|---|---:|---:|---:|---:|
| 8 | 19 995 | **54** | 12 | 0 |
| 10 | 19 995 | **5** | 1 | 0 |

[Pi] Las pérdidas continúan aunque el TT más próximo al Tracker es el Genesys Multi-TT. Son menores que en las muestras previas por conexión directa, pero las ventanas cortas no bastan para atribuir una mejora cuantitativa estable. No se concluye que el Single-TT sea por sí solo toda la causa, ni que el VL805 esté físicamente averiado.

## Fuera de ALSA y del puente de audio

- [Pi] Se para temporalmente rpi-audiod y se reproduce el modo del portátil: **8 OUT** sin retorno presentado, `arecord` directo, S16/44,1 kHz y buffer de 200 ms. En una ventana usbmon de ~15 s: **32 errores/vacíos de 14 997 paquetes**. El dispositivo musical y zita/JACK quedan fuera de esta captura.
- [Pi, código] Sonda temporal con la [API asíncrona oficial de libusb](https://libusb.sourceforge.io/api-1.0/group__libusb__asyncio.html): reclama solo las interfaces de audio del Tracker, captura el endpoint IN 0x84 con doce transferencias en cola y varía los paquetes por transferencia. Se desprende temporalmente el driver de audio y se vuelve a asociar al acabar; la consola CDC se conserva. Compilada con `-Wall -Wextra -Werror` usando la biblioteca instalada y un header oficial temporal, sin instalar paquetes ni modificar módulos del kernel.

| Captura USB directa (~15 s) | Transferencias en cola | Paquetes completados | Paquetes erróneos/vacíos |
|---|---:|---:|---:|
| 1 paquete por transferencia | 12 | 14 998 | **29** |
| 8 paquetes por transferencia | 12 | 15 000 | **25** |
| 32 paquetes por transferencia | 12 | 15 008 | **32** |

- [Pi] Ninguna transferencia completa falla como conjunto; los errores se publican en sus descriptores isócronos individuales. Esta tabla cuenta estados de libusb; no se identifica su valor enumerado con el errno crudo `-18` de Linux. ALSA/usbmon proporciona ese contraste por separado.
- [Pi] Aumentar mucho la cola o retirar ALSA y JACK no elimina las pérdidas. El fallo sigue en el camino USB compartido por ambas pruebas (USB core/xHCI/VL805, hubs y su interoperabilidad con el dispositivo). La prueba no separa todavía hardware del controlador frente a su firmware o driver.

## Estado de la plataforma

- [Pi] ASPM PCIe **desactivado en Link Control**, aunque la política global diga powersave. Contadores PCIe AER correctables y no fatales: **0**. `get_throttled=0x0`; no se cambian voltajes, reloj ni gobierno de CPU.
- [Pi, límite] Intento de cambiar la afinidad de la IRQ USB a CPU2: el kernel devuelve **EPERM**. No se ejecuta esa comparación. La afinidad queda en su valor inicial `0-3`; no se solicita otra aprobación ni se intenta sortear esa restricción.
- [Pi] VL805 **000138c0**, marcado actualizado por `rpi-eeprom-update`. Hay actualización del **bootloader** disponible, que no cambia la versión VL805 ofrecida. Se consulta el estado, sin programar ninguna actualización de arranque.
- [ext] Las [notas oficiales del EEPROM](https://github.com/raspberrypi/rpi-eeprom/blob/master/firmware-2711/release-notes.md) identifican 138C0 como la corrección de split transactions; esa versión ya está instalada. El [cambio original](https://github.com/raspberrypi/linux/pull/5262) trataba una condición concreta del TT integrado; no se da por demostrado que explique estas pérdidas de captura ni que actualizar el bootloader las corrija.
- [Pi] Once canales, también detrás del Genesys: se enumera, pero el puente no puede abrirlo; se conserva el rechazo de ancho de banda del kernel. Se restaura estéreo después.
- [código, límite] **Once canales sí caben en el tamaño máximo de un paquete Full-Speed**: el descriptor pide 45×11×2 = 990 B, menor que 1023 B. Eso no garantiza que el controlador y la topología acepten su reserva de tiempo. El rechazo observado en la Pi no demuestra una imposibilidad universal del Tracker o de USB Full-Speed; el portátil no probó once canales en la sesión aportada.

## Estado final

- [Pi] Firmware original del Tracker; **2 OUT / 2 IN**, reproducción USB cerrada sin rutas, Master estéreo → DAC al 100 %, proyecto sonando. Audio/UI activos.
- [Pi] Comprobación final ~20 s detrás del Genesys: **19 996 paquetes, cero errores/vacíos, cero bloques descartados, cero intervalos perdidos y cero xruns adicionales**.
- [repo] Scripts C/Python, cabecera libusb, volcados, grabaciones y resultados se conservan en `out/2026-11-04-pi-usb-host/`, ignorado por git. No se instala un supuesto arreglo ni se cambia el kernel, el firmware del Tracker, el arranque o la configuración de red.
- [?] Para separar driver de hardware hace falta otra comparación controlada, por ejemplo con otro kernel de la Pi o con un controlador USB distinto. No se presentan esas comparaciones como realizadas ni como soluciones garantizadas.

## Contraste de la propuesta USB-C con xHCI interno

- [ext] La [documentación oficial de `otg_mode`](https://www.raspberrypi.com/documentation/computers/config_txt.html#otg_mode) confirma que `otg_mode=1` selecciona el xHCI USB 2.0 interno para el conector USB-C de la Pi 4. Permite comparar con otro controlador sin cambiar el kernel ni el firmware del Tracker. La ejecución posterior se detalla en la sección siguiente.
- [Pi] Releído el sistema: **Raspberry Pi 4 Model B Rev 1.5**, kernel **6.18.50+rpt-rpi-v8**. El bloque `[pi4]` de `config.txt` contiene `dtoverlay=dwc2,dr_mode=peripheral`; el `otg_mode=1` existente está bajo `[cm4]` y no activa ese modo en esta placa. UDC `fe980000.usb` ligado al gadget, servicios gadget/audio activos. Tracker sigue capturando estéreo a 44,1 kHz por el VL805.
- [Pi, repo] **Conflicto con la función del producto:** el USB-C es también la conexión UAC2/MIDI de la Pi hacia la Force u otro host. Durante una prueba como host interno no se puede mantener ese gadget en el mismo puerto. Un resultado limpio sería evidencia para el diagnóstico; no resolvería por sí solo el uso simultáneo de ambas conexiones en esta Pi.
- [repo] Preparación inicial: borrador local de `config.txt` en `out/2026-11-04-pi-usb-host/usb-c-host-draft/`, junto con la copia original leída de la Pi. Sustituye solamente el overlay periférico bajo `[pi4]` por `otg_mode=1`. Antes de ejecutarlo se requerían comprobar adaptador/alimentación, autorización para el arranque, copia de reversión en la Pi y procedimiento de despliegue que no volviera a imponer el overlay periférico. La ejecución autorizada y su restauración se detallan a continuación.
- [usuario, repo, ext] Alimentación actual mediante **8086 USB-C/PWR Splitter** y cargador original de Pi 4. El modelo y su tabla ya constaban en STATUS y el manual. El [fabricante en Lectronz](https://lectronz.com/products/1463) confirma que **USB2 DATA no conecta VBUS** y lleva resistencias CC de 5,1 kΩ a masa; DATA POWER sí lleva 5 V hacia la Pi. El usuario conecta el Tracker a USB2 DATA y no se enciende: comportamiento coherente con la ausencia de alimentación. **Activar host por software no añade una conexión de 5 V que el splitter no tiene.** No sirve para conectar directamente un Tracker alimentado por USB. Antes de cambiar el arranque hace falta otra disposición física: alimentación/datos apropiados para host, o una solución autoalimentada cuya enumeración funcione con el enlace ascendente sin VBUS y sus terminaciones CC. Un hub cualquiera con fuente propia no se da por compatible automáticamente. No se puentea VBUS ni se unen fuentes.
- [Pi, código] El descriptor ALSA actual anuncia únicamente **44100 Hz**; el código público de descriptores usa `bInterval=1` para el endpoint de audio Full-Speed. No hay comparación a 48 kHz disponible en este firmware. La Pi sí remuestrea a 48 kHz para el DAC, fuera de las pruebas de captura USB directa.
- [Pi] Reanalizadas las capturas guardadas: los **54/5/32** errores de las sesiones Genesys 8/10 y ALSA con ajustes del portátil son todos **`iso_frame_desc.status=-18` y longitud 0**; las URB completas tienen estado 0. Los paquetes correctos son 704/720 B con ocho canales y 880/900 B con diez. La [documentación del kernel](https://docs.kernel.org/driver-api/usb/error-codes.html) define `-EXDEV` en el descriptor isócrono como transferencia parcialmente completada. No identifica por sí solo el origen físico ni debe confundirse con un rechazo al encolar una URB.
- [ext, límite] [#3962](https://github.com/raspberrypi/linux/issues/3962) documenta el límite agregado de 1023 B periódicos Full-Speed por trama del VL805 y propone el host interno. [#4314](https://github.com/raspberrypi/linux/issues/4314) sí contiene una solución con `otg_mode=1`, pero cambiando **dwc2 en CM4**, no nuestro VL805. [#5188](https://github.com/raspberrypi/linux/issues/5188) trata pérdidas isócronas con dwc2/CM4: analogía, sin demostrar la misma causa. [#7737](https://github.com/raspberrypi/linux/issues/7737), abierta el 3 de noviembre de 2026, trata un bloqueo bulk IN tras cancelar URB en 6.18: no prueba que explique las pérdidas periódicas del endpoint isócrono del Tracker.

## Ensayo autorizado con el xHCI interno: sin enumeración

- [usuario] Autoriza expresamente activar temporalmente host USB-C, reiniciar, probar 8/10 y restaurar con otro reinicio. Confirma **splitter USB2 DATA → adaptador USB-C a USB-A hembra → cable USB-A del Ugreen 20265 alimentado → Tracker**; Tracker encendido. La referencia 20265 corresponde al hub USB 3.0 de tres puertos con Ethernet; no se interpreta «4 en 1» como USB4. El modelo no basta para identificar el adaptador intermedio.
- [repo] Añadido `tools/deploy.sh --usb-c-bench host|restore`, ruta independiente del instalador normal: ejecuta `tools/hosts/pi-usb-c-bench.py`, guarda original/propuesta en `/var/backups/rpi-audio-usbc-bench` y rechaza sobrescribir ediciones posteriores o configuraciones ambiguas. No reinicia por sí solo ni cambia servicios. Para esta Pi se usa `PI_HOST=no3z@192.168.2.229 PI_SSH_HOST_KEY_ALIAS=192.168.1.106`, conservando la verificación estricta de clave SSH. Cinco casos de prueba nuevos; suite completa **458 correctos, 13 omitidos**, flake8 y sintaxis de deploy correctos.
- [Pi] Aplicado por deploy únicamente el cambio de overlay periférico a `otg_mode=1` bajo `[pi4]`, con copia previa y sincronización antes del reinicio. Kernel y firmware del Tracker conservados.
- [Pi] Tras reiniciar aparece **`/sys/devices/platform/scb/fe9c0000.xhci/usb3`**, root hub 480 Mbit/s, sin UDC. Es el controlador interno, distinto del VL805 PCIe. El servicio gadget falla por ausencia de UDC y audio queda inactivo por su dependencia; UI activa. Se conserva WiFi y `get_throttled=0x0`.
- [Pi, límite] **Ningún hub ni Tracker enumera bajo usb3**, tampoco durante la espera y las comprobaciones después de solicitar reconectar el cable de datos. Estado del puerto raíz **`0000.0100 power`**, sin conexión; ningún `/dev/ttyACM*` del Tracker. No se llega a abrir captura: **no hay resultados de audio de 8/10 canales con el xHCI interno**. No se concluye que falle el audio de ese controlador. El montaje de datos/adaptación/alimentación ascendente sigue sin validar; que el Tracker encienda no demuestra ese enlace.
- [Pi] Ejecutado `--usb-c-bench restore` y segundo reinicio. Comparación byte por byte y SHA-256 confirman **`config.txt` idéntico al original**. UDC/gadget/audio/UI recuperados; el controlador interno adicional ya no aparece. No se modifica la red, EEPROM, kernel ni firmware del Tracker.
- [usuario, Pi] El usuario devuelve el Ugreen a un USB-A azul: ahora enumera como **Genesys 05e3:0610 USB2 + 05e3:0612 USB3**, ASIX 0b95:1790 a 5 Gbit/s, Tracker a 12 Mbit/s detrás de su rama USB2. En esta conexión el hub sí enumera; no demuestra por sí solo cuál es la pieza que impidió la conexión por el splitter.
- [Pi, límite] Primer intento de medir tras el segundo reinicio descartado: usbmon no estaba cargado y el script no obtuvo muestras. Se carga el módulo instalado, se comprueba el archivo de captura y se repite en una carpeta distinta; no se cuenta una captura vacía como cero errores.

### Capturas válidas tras restaurar, por USB-A/VL805

Mismo firmware original y proyecto `12guitareno` a 98 BPM, reproducción activa. Hub a 48 kHz, Tracker a 44,1 kHz, captura abierta y retorno USB cerrado sin rutas. Ventanas usbmon de ~20 s:

| Canales | Paquetes | Errores/vacíos | Bloques descartados adicionales | Intervalos perdidos adicionales | XRuns adicionales |
|---|---:|---:|---:|---:|---:|---:|
| 8 | 19 994 | **42** | 10 | 42 | 0 |
| 10 | 19 995 | **3** | 0 | 3 | 0 |
| 2, final | 19 994 | **0** | 0 | 0 | 0 |

- [Pi] **Estado final verificado:** archivo de arranque original idéntico, UDC `fe980000.usb`, servicios gadget/audio/UI activos, `get_throttled=0x0`; Tracker v1.1.0 original, **2 OUT / 2 IN**, captura funcionando, retorno parado, Master → DAC activo al 100 %, proyecto sonando. El gadget conserva 26×26 para un host externo, sin host conectado en esta comprobación.
- [Pi, límite] Ni ocho ni diez canales quedan limpios con esta conexión USB-A. La sesión no demuestra rendimiento de audio del xHCI interno porque allí no enumeró el dispositivo. Para esa comparación sigue faltando un montaje físico que establezca el enlace host, con VBUS/señalización y alimentación adecuados; no se atribuye el fallo de enumeración al VL805, que estaba fuera de ese recorrido.
- [repo] Evidencia del arranque xHCI, volcados y capturas válidas bajo `out/2026-11-04-pi-usb-host/usb-c-host-results/`; resultados válidos en `rpi-audio-usbc-restored-v2/`. Ningún audio, número de serie o volcado bruto se incorpora a git.

## Seguimiento con otro hub: sí enumera y transmite once canales

- [Pi, usuario] En un ensayo posterior, el usuario cambia al hub Fresco Logic 1d5c:5012. El mismo xHCI interno sí detecta el Tracker: **8/10 canales sin errores en 3 × 20 s por perfil, once canales sin errores en un minuto continuo y 8/2 dúplex con retorno de silencio sin errores durante ~20 s**. El arranque original se restaura otra vez, con estéreo final 19 992 paquetes sin errores. No hay A/B con este mismo hub por USB-A por falta de adaptador. La falta de enumeración anterior corresponde al montaje Ugreen/adaptador, no a una incapacidad demostrada del host interno. [Método, recuentos y límites](2026-11-04-internal-xhci-tracker.md).

## Resultado con el xHCI interno

- [Pi] Medido en [2026-11-04-internal-xhci-tracker.md](2026-11-04-internal-xhci-tracker.md), ruta xHCI interno → hub Fresco Logic 1d5c:5012 Multi-TT → Tracker. **0 errores** a 8, 10 y 11 canales, 11 canales durante un minuto seguido y 8/2 dúplex. El VL805 rechazaba los 11 canales. Hub y controlador cambian a la vez; no hay A/B con el mismo hub.

## Qué significa `-EXDEV` con 0 B (código del kernel 6.18)

- [código] En `drivers/usb/host/xhci-ring.c` de `rpi-6.18.y`, un descriptor isócrono acaba en `-EXDEV` por dos caminos: un evento **Missed Service Error** (código 23) sobre el TD, o `skip_isoc_td()`, que pone `-EXDEV` y longitud 0 a los TD saltados después de un Missed Service Error sin TD o de un Ring Overrun/Underrun. Un error de bus aparecería como `-EPROTO` (USB Transaction Error), uno de ancho de banda como `-ECOMM` y un babble como `-EOVERFLOW`. No hemos visto ninguno de ellos.
- [código, est] Por tanto el síntoma es que **el propio controlador declara que no atendió el endpoint en su intervalo**, no que el paquete llegara corrupto. Con doce transferencias en cola (sonda libusb) el anillo no se vacía, así que el Ring Overrun es improbable; queda por confirmar con traza.
- [código] Quirks del VL805 (1106:3483) en `xhci-pci.c`: `LPM_SUPPORT`, `TRB_OVERFETCH`, `EP_CTX_BROKEN_DCS`, `AVOID_DQ_ON_LINK`, `VLI_SS_BULK_OUT_BUG`, y `VLI_HUB_TT_QUIRK` **solo con firmware < 138C0**. Con nuestro 138C0 ese parche del TT ya no se aplica: la corrección está en el firmware. Ningún quirk del VL805 toca la planificación isócrona.
- [código] `XHCI_SW_BW_CHECKING` solo se activa en controladores Intel. El rechazo de 11 canales lo devuelve el **firmware del VL805** a la orden Configure Endpoint, no el kernel. Encaja con el límite de 1023 B periódicos FS por trama de #3962: 990 B de audio más el endpoint de interrupción CDC (16 B, bInterval 16) y la sobrecarga de cada transacción. [est] No sabemos cómo contabiliza esa sobrecarga.
- [Pi, est] Más canales no dan más errores: 8 canales dan 54/42 por ventana y 10 canales 5/3. Un límite de ancho de banda puro empeoraría con el tamaño. Esto apunta a la **planificación de split transactions del VL805**, que depende de cómo caen los paquetes en los microframes. No lo hemos demostrado.

## Traza preparada para la próxima vez en el VL805

- [repo] `tools/xhci-error-trace.sh [segundos]`: activa `xhci-hcd:xhci_handle_event` con un filtro que deja fuera Success y Short Packet, lo graba, lo cuenta por código/slot/endpoint y restaura el estado del trazado (`trap`). Necesita sudo y no toca el audio.
- [Pi] Probado 3 s en el xHCI interno: registra eventos (dos `Stall Error` de otro dispositivo, ajenos al Tracker) y deja `tracing_on=1`, el evento desactivado y `filter none`, como estaban.

## Traza en el VL805: el controlador declara Missed Service

- [Pi] Tras la restauración, Tracker **conectado directo a un USB-A azul** (VL805 → VIA Single-TT). Línea base a **2 canales**, captura del daemon en marcha: **0 eventos** no exitosos en 20 s.
- [Pi] Un único ensayo a **8 OUT**, solo captura. Se para rpi-audiod, se lanza `arecord` directo S16/44,1 kHz con buffer de 200 ms y se graban 20 s de usbmon y de traza en la misma ventana. Después se restaura **2 duplex** y se arranca rpi-audiod.

| Fuente | Paquetes | `-18`/0 B | Eventos no exitosos |
|---|---:|---:|---|
| usbmon, EP 0x84 | 19 996 | **148** | — |
| traza xHCI | — | — | **148 × `Missed Service Error`, slot 2 ep 9** (DCI 9 = EP 4 IN) |

- [Pi] **Correspondencia exacta uno a uno.** No aparece ningún `USB Transaction Error`, `Bandwidth Overrun`, `Babble`, `Ring Overrun` ni `Ring Underrun`. Cada evento llega con **puntero TRB 0**: el kernel lo trata como Missed Service sin TD y descarta el TD siguiente con `skip_isoc_td()` (`-EXDEV`, 0 B). **El VL805 dice no haber atendido el endpoint en su intervalo.** El paquete no llega corrupto por el bus y el driver no lo pierde.
- [Pi] Distribución: eventos aislados, nunca dos tramas seguidas; intervalos de 2 a 998 ms, mediana 34 ms, siempre múltiplos de 1 ms, sin periodo fijo. Todos se procesan en CPU0 con la CPU ociosa (`<idle>`). [est] Un conflicto fijo de planificación produciría un patrón periódico; esto parece más bien una latencia interna del VL805 que de vez en cuando no llega a tiempo. Puede ser el acceso a memoria por PCIe, su firmware o el TT. No está demostrado.
- [Pi] 148/19 996 = 0,74 %, más que con el Genesys Multi-TT (54 y 42 por ventana). Coincide con las medidas previas por conexión directa, pero no es un A/B controlado.
- [Pi] **Estado final verificado:** Tracker en 2 duplex, captura de 2 canales `RUNNING`, gadget/audio/UI activos, UDC `not attached` (sin host conectado, igual que antes), trazado devuelto a `tracing_on=1` / evento desactivado / sin filtro, `throttled=0x0`, proyecto sonando. Evidencia en `out/2026-11-04-pi-usb-host/vl805-trace/`.

### A/B con carga de memoria

- [ext] En linux-usb (junio–septiembre de 2026) se describen MSE/`-EXDEV` aislados en audio USB con AMD Zen5 que [desaparecen con tráfico de memoria sostenido](https://ratatoskr.run/linux-usb/2026/06/17070983/t), atribuidos a la latencia DMA del host. Se reproduce la idea aquí.
- [Pi] Mismo montaje directo VIA, 8 OUT, un ensayo de cada. Con carga, tres `dd if=/dev/zero of=/dev/null bs=32M` fijados a CPU1–3; sin carga, como control.

| Modo | Paquetes | `-18`/0 B (usbmon) | Missed Service (traza) | Relojes ARM/core |
|---|---:|---:|---:|---|
| Carga de memoria | 19 996 | **136** | 136 | 1,8 GHz / 500 MHz |
| Sin carga | 19 996 | **136** | 138 | 1,8 GHz / 500 MHz |

- [Pi] **La carga de memoria no cambia nada.** La traza cuenta 2 eventos más que usbmon sin carga porque las ventanas no coinciden exactamente en los bordes. Los relojes son iguales en ambos modos, así que no hay escalado de frecuencia entre medidas. [est] No apoya la hipótesis de estados de bajo consumo de la memoria; no descarta la latencia PCIe del propio VL805.
- [Pi] Estado final verificado: 2 duplex, captura de 2 canales `RUNNING`, gadget/audio/UI activos, trazado restaurado, sin `dd` residuales, `throttled=0x0`, proyecto sonando.

## A/B con el mismo hub Fresco: el controlador es la causa

- [usuario, Pi] El usuario conecta el hub Fresco del ensayo interno a un USB-A azul. Ruta: **VL805 → VIA integrado → Fresco 1d5c:5012 (Multi-TT, alt 1) → Tracker**. Es el mismo árbol de hubs que dio 0 errores por el xHCI interno, con el Genesys, el lector, la Ethernet y el C-Media colgando también del Fresco. Solo cambian el controlador y el VIA que tiene delante, que forma parte de la Pi y no se puede evitar en los USB-A.
- [Pi] Método idéntico: rpi-audiod parado, `arecord` directo, 20 s de usbmon y traza. Un ensayo de cada.

| Ruta | Canales | Paquetes | `-18`/0 B | Missed Service (traza) |
|---|---:|---:|---:|---:|
| xHCI interno → Fresco | 8 | 59 978 (3 × 20 s) | **0** | — |
| **VL805 → VIA → Fresco** | 8 | 19 996 | **40** | 40 |
| xHCI interno → Fresco | 10 | 59 999 (3 × 20 s) | **0** | — |
| **VL805 → VIA → Fresco** | 10 | 19 996 | **4** | 4 |

- [Pi] Con el mismo hub, el VL805 vuelve a perder paquetes y la traza vuelve a dar Missed Service uno a uno. Las cifras son del orden de las del Genesys Multi-TT (54/42 y 5/3). Los `Stall Error` del slot 4 ep 3 son de otro dispositivo, también presentes en el xHCI interno, y no afectan al Tracker. **El hub no lo arregla: la causa está en el VL805 (o en el VIA integrado delante).** Un Multi-TT reduce las pérdidas frente a la conexión directa al VIA Single-TT (136–148 a 8 canales), pero no las elimina.
- [Pi] Primer intento descartado: con el Tracker ya a 8 canales, el script aceptó la tarjeta anterior durante la reenumeración y perdió la consola. No llegó a medir. El Tracker reenumeró solo y rpi-audiod volvió a capturar. El script ahora espera a que cambie el número de dispositivo y a la consola.
- [Pi] Estado final verificado: 2 duplex, captura de 2 canales `RUNNING`, gadget/audio/UI activos, trazado restaurado, `throttled=0x0`, proyecto sonando. El Tracker sigue detrás del Fresco en el USB-A.

## Contexto externo

- [ext] **No hay firmware VL805 posterior a 138C0.** Es la última entrada del VL805 en las [notas de rpi-eeprom](https://github.com/raspberrypi/rpi-eeprom/blob/master/firmware-2711/release-notes.md), y es el único binario VL805 en `firmware-2711/latest`.
- [código, ext] `xhci_vl805_hub_tt_quirk()` solo se llama al encolar bulk/interrupt y control, nunca desde `xhci_queue_isoc_tx`, y solo actúa sobre dispositivos FS colgados directamente del hub raíz. Forzarlo con `xhci_hcd.quirks` no afectaría a la captura isócrona.
- [ext] Del lado de Linux, 6.18.49 ya trae «Handle bogus TRB pointers in Missed Service Error events» (Pecio), y la serie de errores isócronos de febrero de 2025 es anterior a 6.18. Los cambios de frame ID de Nyman (agosto de 2026) no llevan marca de stable y tratan otro caso (MOTU, CFC). No hay ningún parche de linux-usb para VIA/VL805 con isócrono detrás de TT. [est] Un kernel más nuevo no tiene motivo conocido para arreglarlo.
- [ext] Raspberry Pi en el foro: el ancho FS isócrono total del VL805 está limitado a 1023 B por trama ([t=273027](https://forums.raspberrypi.com/viewtopic.php?t=273027)), y la mejora «depende de que VIA publique firmware» ([t=345191](https://forums.raspberrypi.com/viewtopic.php?t=345191)). Ese firmware no ha llegado. No se encuentra ningún parámetro de kernel o `config.txt` que lo mitigue.
- [ext] En la Pi 4, el dwc2 (gadget) y el xHCI interno son **alternativas sobre el mismo USB-C** ([config.txt, `otg_mode`](https://www.raspberrypi.com/documentation/computers/config_txt.html#otg_mode)). No puede ser gadget hacia el host y host hacia el Tracker a la vez.
- [ext, est] **Pi 5 / CM5:** el gadget dwc2 del BCM2712 va por el conector de alimentación, y los USB-A dependen de dos xHCI del RP1, que son controladores distintos ([whitepaper OTG RP-009276-WP](https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-009276-WP/Using-OTG-mode-on-Raspberry-Pi-SBCs)). Por arquitectura permitiría ambos papeles a la vez, alimentando por GPIO/PoE. Salvedades: [#6289](https://github.com/raspberrypi/linux/issues/6289) (gadget en Pi 5 con cables C-C) y ningún dato de FS isócrono detrás de TT en el RP1. **No probado.**

## Contraste de parches xHCI recientes y pérdida real en el bus

- [Pi] `HCCPARAMS1` del VL805 = `0x002841eb`: **sin CFC** (bit 11 = 0). [código] En 6.18 el número de trama de inicio solo se calcula con CFC. Si no hay CFC, cada TD isócrono va con `TRB_SIA` (lo antes posible). Los parches de frame ID de Nyman (mayo/agosto de 2026) no actúan en este controlador, y además tratan el **arranque** del flujo, no paquetes sueltos con el flujo en marcha.
- [ext] [#7737](https://github.com/raspberrypi/linux/issues/7737) y su arreglo de 7.3 (7c0c31c) tratan un bloqueo bulk tras cancelar URB: no aplican. [#7731](https://github.com/raspberrypi/linux/issues/7731) (Pi 5): el autor ya lo atribuye a la combinación snd-usb-audio/interfaz, porque también falla en Intel con 7.0; no indica un defecto del RP1.
- [Pi] **Pérdida real en el bus.** El contador `iso_in_missed` del Tracker cuenta las tramas sin token IN desde el SOF anterior ([código] `usb/include/o3os/usb/device.h`). Antes/después de cada grabación de 24 s:

| Ruta | Canales | `iso_in_missed` del Tracker | `-18` en la Pi (20 s) |
|---|---:|---:|---:|
| xHCI interno → Fresco | 8/10 | ~30 (arranque/parada) | 0 |
| VL805 directo | 8 | 172 / 167 | 136 / 136 |
| VL805 → Fresco | 8 | 57 | 40 |
| VL805 → Fresco | 10 | 13 | 4 |

- [Pi, est] A 8 canales en directo, el dispositivo ve unos 140 tokens IN que faltan por encima de la línea base, coherente con lo que declara el VL805. Con el Fresco, la línea base de arranque/parada tapa la señal. El VL805 no pide el paquete en esa trama; no es un recuento erróneo del driver, así que un kernel más nuevo no tiene por qué cambiarlo. [límite] El contador también subiría si el Tracker no tuviera el paquete listo y no viera el token. Sin analizador USB no se separan ambos casos del todo, pero el mismo Tracker no pierde ninguno por el xHCI interno ni en el portátil.

## Kernel 7.3.1 de prueba (tryboot) y A/B Tracker parado/en reproducción

- [usuario] Autoriza probar un kernel más nuevo en la Pi, con arranque y reinicios.
- [repo] Compilado `raspberrypi/linux` rpi-7.3.y, commit `5f369cb6094aa8e5bb574ca000cfd04494dc93c7` (7.3.1), con `bcm2711_defconfig` y sufijo `-v8-rpiaudio-test`, en un contenedor `debian:trixie` en el portátil, sin instalar nada en su sistema. Lleva 7c0c31c y los cambios de frame ID. [código] En 7.3, sin CFC, solo el primer TD de un flujo usa frame ID; el resto sigue con `TRB_SIA`, como en 6.18.
- [Pi] **Instalación temporal:** kernel/DTB/overlays/cmdline en `/boot/firmware/test-7.3/`, módulos en su propio directorio y `tryboot.txt` = `config.txt` + `os_prefix=test-7.3/`. Un reinicio `0 tryboot` arranca 7.3 una sola vez. Una unidad de guarda limitada a ese kernel reiniciaría a los 20 min. `config.txt` no se toca. El Force no estaba conectado (`not attached`) en ninguno de los reinicios.
- [Pi] 7.3.1 arranca con WiFi, gadget, audio y UI activos; misma topología VL805 → VIA → Fresco → Tracker; `HCCPARAMS1 = 0x002841eb`.

| Kernel | Tracker | Canales | Paquetes | `-18`/0 B | Missed Service |
|---|---|---:|---:|---:|---:|
| 7.3.1 | parado (tras reiniciarse con la Pi) | 8 | 19 996 | **0** | 0 |
| 7.3.1 | reproduciendo | 8 | 19 995 | **39** | 39 |
| 7.3.1 | — | 10 | — | rechazo `-28` (*Not enough bandwidth*) | — |
| 6.18.50 | **parado** | 8 | 19 995 | **0** | 0 (`iso_in_missed` +6) |
| 6.18.50 | **reproduciendo** | 8 | 19 996 | **67** | 67 (`iso_in_missed` +78) |

- [Pi] **7.3.1 no lo arregla:** con el Tracker sonando pierde 39 paquetes, del orden de los 40 de 6.18 con el mismo hub, y además rechaza 10 canales que 6.18 sí abría. [?] La causa de ese rechazo no se investiga.
- [Pi] **Hallazgo:** el primer cero de 7.3 se debía a que el Tracker no estaba reproduciendo, porque se reinició al reiniciar la Pi. Repetido en 6.18 con el mismo montaje: **parado, 0 pérdidas; reproduciendo, 67.** El contador `iso_in_missed` del Tracker sube igual (+6 frente a +78). Por el xHCI interno, reproduciendo, había 0 pérdidas.
- [Pi, est] Las pérdidas necesitan **las dos condiciones a la vez**: el VL805 y el Tracker ocupado reproduciendo. Ninguna de las dos basta sola. Encaja con que, mientras renderiza, el Tracker tarde a veces en rearmar su único paquete IN. El VL805 tolera peor ese retraso que el xHCI interno o el portátil, quizá porque coloca el token IN en otro momento de la trama o con más variación. El VL805 lo notifica como Missed Service. No está demostrado: falta medir la posición de los tokens en el bus.
- [repo] El parche de prearmado de dos paquetes IN ([tools/hosts/tracker-usb-prearm/](../../tools/hosts/tracker-usb-prearm/)) ataca justo ese margen. El usuario ha decidido no tocar el Tracker por ahora.
- [Pi] Restaurado y verificado: 6.18.50, ningún fichero de prueba en `/boot/firmware`, `/lib/modules` ni systemd, `config.txt` intacto, gadget/audio/UI activos, Tracker en 2 duplex reproduciendo con la captura `RUNNING`, trazado en su estado original, `throttled=0x0`. Un primer A/B en 6.18 se descartó porque usbmon no estaba cargado tras el reinicio; el script se negó a contar la captura vacía. En un segundo, `key play` no paró el Tracker sin una pausa antes de leer el estado; se rehízo. Evidencia en `out/2026-11-04-pi-usb-host/kernel-7.3-trial/` y `vl805-play-ab/`.

## Patrón de pérdidas y parámetros xHCI de prueba (6.18.50 parcheado)

- [usuario] «go with 1»: probar un kernel que cambie lo que Linux declara al VL805 para el endpoint isócrono IN FS detrás de un TT. Revisión independiente (Fable) del plan y del código del kernel antes de compilar.
- [Pi] **Las pérdidas siguen siempre al paquete de tamaño máximo.** El endpoint 0x84 alterna paquetes de 44 y 45 tramas; el de 45 es exactamente `wMaxPacketSize`. En todas las capturas, el paquete perdido es el siguiente a uno de 45 tramas, nunca a uno de 44:
  - 8 canales, Fresco, reproduciendo: 67/67 tras 720 B, aunque solo el 16 % de los paquetes son de 720 B.
  - Hoy, mismo montaje: 8 canales 40/40 y 52/52 tras 720 B; 6 canales 221/221 tras 540 B; 4 canales 1014/1014 tras 360 B.
  - [Fable, sin rehacer aquí] Lo mismo en las capturas con Genesys y VIA de 4 a 10 canales.
- [Pi] **Segundo síntoma, también solo en el VL805:** completados retrasados exactamente un microframe: ~1122 µs desde el anterior, seguido de ~878 µs. Recaen casi siempre en el paquete grande:
  - 8 canales: 114 en paquetes de 720 B, frente a 1 en los de 704;
  - 6 canales: 777 frente a 33;
  - 4 canales: 1526 frente a 659.

  Con el Tracker parado hay 0; [Fable] por el xHCI interno, 1–2 cada 20–60 k paquetes.
- [Pi] **«Parado» significa también «datos a cero»:** la captura con el Tracker parado son 19 995/19 995 paquetes a cero (en los 32 B que muestra usbmon); reproduciendo, ninguno. La diferencia parado/reproduciendo puede deberse al contenido y no a la carga del Tracker. [Fable, est, sin rehacer aquí] El relleno de bits NRZI alarga la transacción FS con datos reales y nunca con ceros; en sus cuentas el retraso y la pérdida crecen con la cantidad de relleno a 8 canales.
- [repo] El prearmado de dos paquetes IN ya se probó en hardware en otra sesión y **no quitó las pérdidas** ([prueba](2026-11-04-tracker-prearm-hardware.md)). Con dos paquetes armados, un retraso del ISR de menos de una trama no deja el endpoint vacío. Junto con el patrón anterior, **se descarta que el Tracker rearme tarde**. Queda como hipótesis: el VL805 programa demasiado pocos complete-splits para una transacción FS que llega al tamaño máximo con datos reales. [?] Sin analizador de bus no está demostrado.
- [repo, código] **Parche de prueba**, `out/2026-11-04-pi-usb-host/xhci-tune-trial/xhci-tune.patch`, sobre el 6.18.50 exacto de la Pi (`cff533aec2fa`):
  - Quirk `XHCI_VLI_FS_ISOC_TUNE`, activado solo para el VL805 (PCI 1106:3483).
  - Parámetros `xhci_hcd` escribibles en caliente:
    - `vli_fs_isoc_in_pct` escala, en endpoints isócronos IN FS detrás de un TT, Max Packet Size, Max ESIT Payload y Avg TRB Length (`vli_fs_isoc_in_fields`). Nunca baja de lo que había y no pasa de 1023.
    - `vli_hub_ttt` fuerza el TT Think Time.
  - Compilado en contenedor, arrancado una vez por tryboot (`test-xhci/`) con la misma guarda de 20 min. El Force no estaba conectado (`not attached`).
- [Pi] **Los valores llegan al controlador:** el contexto de salida del VL805 (debugfs) muestra `maxp 540, max ESIT payload 540, avg trb len 540` para el endpoint de 4 canales, que en realidad es de 360.

| Canales | maxp declarado | Pérdidas en ~20 s | Retrasos +1 µframe |
|---:|---|---:|---:|
| 4 | 360 (control) | 1014 | 2185 |
| 4 | 422 (+17 %) | 1042 | 2239 |
| 4 | 540 (+50 %) | 1034 | 2218 |
| 6 | 540 (control) | 221 | 810 |
| 6 | 632 (+17 %) | 192 | 758 |
| 8 | 720 (control, dos pasadas) | 40 / 52 | 40 / 61 |
| 8 | 756 (+5 %) | 42 | 64 |
| 8 | ≥ 792 | rechazo `-28` (*Not enough bandwidth*) | — |
| 10 | 900 (control) | rechazo `-28` | — |

- [Pi] **Inflar el tamaño declarado no cambia nada:** ni las pérdidas ni los retrasos se mueven fuera del ruido, ni siquiera con +50 % a 4 canales. El VL805 acepta los valores, pero no los usa para colocar o alargar los splits de este endpoint, o no es ese el límite. Se descarta esa vía.
- [Pi] El presupuesto FS periódico del VL805 es muy justo:
  - a 8 canales no admite más de ~756 B;
  - a 10 canales, sin parche, se rechazó en este arranque tras varios rechazos previos, cuando en el kernel normal sí abría. [?] No se sabe si el VL805 arrastra contabilidad de rechazos anteriores.
  - Al arrancar, el C-Media del Genesys también recibe `-28` alguna vez.
- [Pi] TT Think Time **no se probó**. Fable lo estima despreciable (≤ 2,7 µs frente a microframes de 125 µs), y VIA y Genesys ya declaran TTT 3 y pierden más que el Fresco con 0. Además, reaplicarlo exige desautorizar el hub y desconecta todo lo que cuelga de él.
- [Pi] Restaurado y verificado:
  - 6.18.50 normal, sin `test-xhci/`, `tryboot.txt`, módulos de prueba ni unidad de guarda; `config.txt` intacto.
  - Gadget, audio y UI activos; trazado en su estado original.
  - El último caso (6 canales, +30 %) terminó con error y dejó el Tracker en perfil 8 y parado. Se devolvió a **perfil 2, reproduciendo**, con la captura de 2 canales `RUNNING`.
- Evidencia en `out/2026-11-04-pi-usb-host/xhci-tune-trial/`.

## Flujo vecino en el mismo TT y TRB más largo que el paquete (noche)

- [usuario] «investigate more kernel possibilities, ask fable», y después «i've connected a mixer, you can start the tests». Fable propuso dos pruebas baratas: un flujo FS periódico vecino en el mismo TT, y TRB más largos que el paquete.
- [Pi] **Cambio de montaje.** La Pi responde ahora por Wi-Fi (192.168.2.229; misma clave de host que .106).
  - El primer intento cambió el Tracker de 8 duplex directamente a `usb profile 4 out`. El Tracker se desconectó y **no volvió a enumerar**: lecturas del descriptor `-110` y luego `-71` (no acepta dirección). Desenchufar el cable no bastó; hizo falta apagarlo y encenderlo. [?] Fallo del USB del Tracker, a anotar en track3r-os. Desde entonces, cada cambio de perfil pasa por 2 duplex, como en las sesiones anteriores.
  - Tras apagarlo, el Tracker quedó conectado **directamente al hub VIA de la placa** (1-1.1), junto al mezclador Burr-Brown 08bb:2902 (1-1.4). Los dos comparten el TT único del VIA. El Fresco y el Genesys ya no están conectados.
  - Con este montaje, la línea base a 4 canales son **263–313 pérdidas** en ~20 s, frente a las ~1000 de por la tarde detrás del Fresco. [?] No es comparable: el Tracker se reinició entre medias y el contenido influye.

### Prueba 1: flujo vecino (negativa)

Tracker a 4 canales, reproduciendo, ~20 s por caso:

| Caso | Pérdidas | Retrasos +1 µframe |
|---|---:|---:|
| Línea base | 269 | 2863 |
| + captura del mezclador (2 ch 48 k, 192 B) | 317 | 2843 |
| + reproducción al mezclador (2 ch 44,1 k, ruido a −50 dBFS) | 264 | 2878 |
| + las dos | 273 | 2828 |
| Tracker en 4 duplex, sin retorno | 267 | 2886 |
| Tracker en 4 duplex, con retorno abierto | 288 | 2781 |
| Línea base otra vez | 313 | 2773 |

- [Pi] Un flujo periódico vecino en el mismo TT **no cambia nada**. El mezclador no pierde ningún paquete en ningún caso. (El primer resumen contaba «2000 malos» en su OUT, pero era un error de lectura: usbmon muestra 5 de los 6 descriptores y el sexto campo era la longitud.)

### Prueba 2: `wMaxPacketSize` y TRB más grandes que el paquete real (positiva)

- [código] El prearmado y el parche xHCI anterior solo cambiaban el contexto del endpoint; la longitud de cada TRB seguía siendo 360/540/720 B. snd-usb-audio pide `min(1,5 × tasa, wMaxPacketSize)` por paquete, y usbcore rechaza longitudes mayores que `wMaxPacketSize` (`-EMSGSIZE`). Con 45 tramas por paquete, el paquete grande llena el TRB **exactamente**.
- [repo, código] Módulo snd-usb-audio de prueba (`out/2026-11-04-pi-usb-host/maxp-test/snd-usb-maxp.patch`, fuente 6.18.50).
  - Compilado en la Pi contra sus cabeceras, en `/tmp`. El vermagic es idéntico al del kernel (`6.18.50+rpt-rpi-v8`).
  - Se carga con `insmod` en lugar del de serie: sin reinicio ni cambios de arranque.
  - Parámetros `fs_isoc_in_maxp_pct` y `fs_isoc_in_maxp_id`. Al analizar el descriptor, sube `wMaxPacketSize` del endpoint isócrono IN FS de un único dispositivo (vid:pid). Cambia el descriptor en memoria, así que usbcore, el contexto xHCI y la longitud de los TRB ven el valor nuevo: equivale a que el dispositivo declarara un valor mayor.
- [Pi] El dmesg confirma el cambio (`maxp 360 -> 450`…). En usbmon, todas las URB salen con la longitud nueva (`submit_lengths`). El Tracker sigue mandando paquetes de 44/45 tramas.

| Canales | `wMaxPacketSize` / TRB | Pérdidas | Missed Service | Retrasos +1 µframe |
|---:|---|---:|---:|---:|
| 4 | 360 / 360 (control) | 263 | 264 | 2920 |
| 4 | 450 / 450 (+25 %) | **0** | 0 | 3302 |
| 4 | 540 / 536 (+50 %) | **0** | 0 | 3262 |
| 6 | 540 / 540 (control) | 351 | 351 | 1177 |
| 6 | 632 / 632 (+17 %) | **0** | 0 | 1084 |
| 8 | 720 / 720 (control) | 73 | 73 | 159 |
| 8 | 756 / 756 (+5 %) | **0** | 0 | 131 |
| 4 | 360 / 360 (control final) | 302 | 302 | 2795 |

- [Pi] **Con un TRB mayor que el paquete más grande, desaparecen las pérdidas** a 4, 6 y 8 canales. Basta un 5 % a 8 canales. Los controles intercalados siguen perdiendo, y `arecord` no informa de errores.
- [Pi] Los retrasos de un microframe siguen igual. Son inocuos: el dato llega.
- [est] El VL805 pierde el servicio del TD siguiente **cuando un paquete FS isócrono llena exactamente su TRB**. Con paquete corto (*Short Packet*) no pasa. Encaja con todo lo anterior:
  - solo tras paquetes de 45 tramas;
  - nunca con ceros: el relleno NRZI alarga la transacción y eso explica la dependencia del contenido;
  - nada que dependa del contexto del endpoint ni de la carga.
- [?] Cada caso duró ~20 s y se midió una vez. Falta una prueba larga (≥ 10 min a 8 y 10 canales) y comprobar la integridad del audio con una señal conocida. 10 canales no se probó: el VL805 ya rechaza 900 B a veces, y más aún 945.
- [Pi] Restaurado y verificado:
  - parámetro a 0 y Tracker reenumerado (descriptores originales);
  - `rmmod` del de prueba y `modprobe snd_usb_audio` de serie (sin los parámetros de prueba);
  - Tracker en 2 duplex reproduciendo, rpi-audiod y UI activos, gadget `not attached`.

  El kernel queda marcado como *tainted* (módulo fuera del árbol) hasta el próximo reinicio.
- Evidencia en `out/2026-11-04-pi-usb-host/neighbour-test/` y `out/2026-11-04-pi-usb-host/maxp-test/`.

### Incremento mínimo, prueba larga y módulo para la Pi

- [usuario] «can we do only the pi?» y «go for it»: arreglarlo solo en la Pi, con el Tracker sin cambios. Antes, comprobar el incremento mínimo y hacer una prueba larga.
- [Pi] **Basta con +1 byte.** Mismo módulo de prueba, con un parámetro nuevo `fs_isoc_in_maxp_add` (bytes); ~20 s por caso:

| Canales | Control: pérdidas | +1 byte | +1 trama |
|---:|---:|---:|---:|
| 4 | 201 | **0** (TRB 361) | **0** (368) |
| 8 | 150 | **0** (721) | **0** (736) |
| 10 | 10 | **0** (901) | **0** (920) |

  El VL805 admitió 901 y 920 B a 10 canales: +1 byte apenas consume presupuesto.
- [Pi] **Prueba larga, 10 min, +1 byte** (`maxp-test/run3-long/`):
  - 10 canales: 599 752 paquetes, **0 pérdidas**, 0 Missed Service;
  - 8 canales: 598 842 paquetes, **0 pérdidas**;
  - control a 8 canales sin ajuste, 2 min: 811 pérdidas, todas tras paquetes de 720 B.

  `arecord` no informó de errores. [?] La integridad del audio con una señal conocida sigue sin comprobarse; sin pérdidas ni xruns, la cuenta de tramas es completa.
- [código] **Cuándo actuar.** El notificador `USB_DEVICE_ADD` llega después de que las interfaces se enlazan: `usb_generic_driver_probe` llama a `usb_set_configuration` antes que a `usb_notify_add_device`. Un `usb_device_driver` propio sí llegaría antes, pero sustituye al genérico y deja sin ejecutar las notificaciones y la gestión de energía del genérico. Elegido: el notificador más una reconfiguración.
- [repo] **Módulo `tools/kernel/fs-isoc-pad/`** (`fs_isoc_pad.c`, Kbuild, Makefile, dkms.conf; GPL-2.0-or-later, véase `THIRD_PARTY.md`). Para dispositivos FS tras un TT en el VL805 (PCI 1106:3483):
  - suma `pad` bytes (1 por defecto) a `wMaxPacketSize` de todos los endpoints isócronos IN de datos (no los de *feedback*), en la copia analizada de los descriptores; los crudos que lee `lsusb` no cambian;
  - después vuelve a fijar la configuración activa (`usb_driver_set_configuration`), así que la tarjeta aparece, desaparece y vuelve una vez al conectar;
  - solo usa API exportada: `usb_register_notify`, `usb_for_each_dev` para los dispositivos ya conectados, y `usb_driver_set_configuration`;
  - al descargarse, restaura los tamaños y reconfigura.
- [Pi] **Probado con `insmod`, sin instalar**, compilado en `/tmp` contra las cabeceras, con el snd-usb-audio de serie:
  - Al cargar: `1-1.4: … +1 on 18 isochronous IN endpoint(s)` (mezclador) y `1-1.1: … on 1` (Tracker; 0x85, de *feedback*, excluido). Las dos tarjetas vuelven solas.
  - En los cambios de perfil, el Tracker reenumera y el notificador lo ajusta cada vez.
  - Resultados, 60 s por caso:

| Caso | TRB | Pérdidas |
|---|---:|---:|
| 4 canales, módulo cargado | 361 | **0** |
| 8 canales, módulo cargado | 721 | **0** |
| 10 canales, módulo cargado | 901 | **0** |
| 8 canales, tras `rmmod fs_isoc_pad` | 720 | 466 |

  La descarga restaura de verdad: tras ella vuelven las pérdidas.
- [Pi] Ojo: al recargar, las tarjetas cambiaron de número (Track3r pasó a ser la 1 y CODEC la 2). rpi-audiod las busca por nombre.
- [Pi] Restaurado y verificado:
  - sin `fs_isoc_pad` y con snd-usb-audio de serie;
  - Tracker en 2 duplex reproduciendo, rpi-audiod y UI activos, gadget `not attached`;
  - borradas las capturas grandes de la Pi (`/var/tmp`, `/tmp`).

  Quedan en `/tmp` (se borran al reiniciar) los fuentes de prueba (`/tmp/sndusb`, `/tmp/fsip`). El kernel sigue *tainted* hasta reiniciar.
- [usuario] «ok, yeah commit»: instalarlo y hacer commit.
- [Pi, repo] **Instalado por `tools/deploy.sh`.** `install.sh` hace esto solo si hay un VL805 (PCI 1106:3483) y nunca bajo `RPI_AUDIO_ROOT`:
  - instala `dkms` (3.2.2-1~deb13u1, el único paquete nuevo; las cabeceras ya estaban);
  - copia el fuente a `/usr/src/fs-isoc-pad-0.1`, hace `dkms add/install` para el kernel en marcha y añade `fs_isoc_pad` a `/etc/modules-load.d/rpi-audio.conf`;
  - recarga el módulo solo si cambió el fuente;
  - `--uninstall` lo descarga y lo quita de DKMS y de `/usr/src`.

  Un segundo despliegue no recompila ni recarga (idempotente). `dkms status`: `fs-isoc-pad/0.1, 6.18.50+rpt-rpi-v8, aarch64: installed`. Despliegue hecho por Wi-Fi (`PI_HOST=no3z@192.168.2.229`, con la clave de host conocida), sin `--enable`, `--hat` ni `--host`: unidades, perfil y red tal como estaban.
- [Pi] **En uso real:** después del despliegue, rpi-audiod puso solo al Tracker a 8 canales. Captura `Packet Size = 721`, y en 20 s de usbmon 19 996 paquetes, 0 malos.
- [?] Pendiente: arrancar la Pi en frío con el módulo (lo carga `modules-load`, con los dispositivos ya enumerados), probar con el Force conectado y comprobar la integridad del audio con una señal conocida.
- Evidencia en `out/2026-11-04-pi-usb-host/maxp-test/` (`run2-min`, `run3-long`) y `out/2026-11-04-pi-usb-host/fs-isoc-pad-test/`.

## Conclusión de la investigación

- [Pi, código] Las pérdidas multicanal por los USB-A son **Missed Service Errors que notifica el VL805**, uno a uno con los `-18` de usbmon. Siempre caen en el TD que sigue a un paquete de tamaño máximo (45 tramas), y solo con datos reales: con el Tracker parado el flujo son ceros y no hay pérdidas. Por el xHCI interno o el portátil no las hay en ningún caso.
- [Pi] No dependen de:
  - ALSA/JACK, la CPU de la Pi, la carga de memoria ni la profundidad de cola;
  - el hub (VIA Single-TT, Genesys y Fresco Multi-TT);
  - el kernel (6.18.50 y 7.3.1);
  - el tamaño de paquete que Linux declara al VL805 (parche de prueba).
- [repo] Tampoco las quita el prearmado de dos paquetes IN en el Tracker.
- [Pi] Tampoco depende de un flujo periódico vecino en el mismo TT.
- [Pi, est] **Disparador encontrado:** un paquete que llena exactamente su TRB (actualizado esa noche). Si `wMaxPacketSize`, y con él el TRB, es mayor que el paquete más grande, las pérdidas pasan a 0 a 4, 6 y 8 canales ([prueba 2](#prueba-2-wmaxpacketsize-y-trb-más-grandes-que-el-paquete-real-positiva)). [ext, est] No se conoce firmware del VL805 ni quirk que lo corrija de serie.
- [Pi] **Arreglo solo en la Pi, probado:** el módulo `tools/kernel/fs-isoc-pad/` suma 1 byte. Con él, 0 pérdidas a 4, 8 y 10 canales con el snd-usb-audio de serie; en la prueba larga (10 min) a 8 y 10 canales también 0. Falta instalarlo.
- Opciones (antes de tener el módulo):
  1. **En el dispositivo** (track3r-os): declarar `wMaxPacketSize` al menos una trama mayor que el paquete máximo que envía. A 8 canales serían 46 × 16 = 736 B, por debajo de los 756 B que el VL805 admitió. Así basta con un Linux sin modificar. [est] Equivale a la prueba 2, que cambió ese mismo descriptor en memoria. 10 canales siguen al límite del presupuesto del VL805.
  2. **En la Pi:** un snd-usb-audio con el ajuste para dispositivos FS isócronos IN tras el VL805. Sirve para cualquier dispositivo, pero hay que mantener un módulo fuera del árbol (o subirlo al kernel).
  3. **Estéreo**, **Pi 5/CM5** o **disimular** las pérdidas: siguen siendo opciones, pero ya no hacen falta si 1 o 2 se confirman.
- [?] Pendiente:
  - Prueba larga (≥ 10 min) a 8 canales con el ajuste, e integridad del audio con una señal conocida.
  - Decidir entre la opción 1 y la 2.
  - Probar un dispositivo HS multicanal en el VL805.
