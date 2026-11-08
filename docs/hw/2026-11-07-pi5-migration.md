# 2026-11-07: cambio de la Pi 4 a una Pi 5 con la misma SD

El usuario cambió la Pi 4 por una Pi 5 y arrancó con la misma tarjeta SD. Sesión de puesta en marcha; sin host USB ni dispositivos USB conectados.

## La placa

- [Pi] Raspberry Pi 5 Model B Rev 1.1, **1 GB**, 4 × Cortex-A76 (CPU part 0xd0b). Kernel `6.18.50+rpt-rpi-2712`, **páginas de 16 KiB**. Debian 13 trixie. EEPROM al día (25-09-2026).
- [Pi] Red: `raspberrypi.local`, Ethernet 192.168.1.109 y Wi-Fi 192.168.2.34 (`bender_5G`). Misma clave de host que la Pi 4 (misma SD). Las IP anteriores (.106, .229) ya no responden.
- [Pi] USB: dos xHCI del RP1, `xhci-hcd.0` (buses 1 USB2 de 2 puertos y 2 USB3) y `xhci-hcd.1` (buses 3 y 4). No hay VL805 ni hub interno. Los dispositivos FS caen en el bus 1 o el 3, así que el presupuesto «por bus» de `rpi-audiod` queda por controlador.
- [Pi] Alimentación: `max_current` del firmware 3000 mA, `usbpd_power_data_objects` todo a cero (no hay negociación USB-PD), `usb_max_current_enable=0`, EXT5V 5,01-5,14 V, `throttled=0x0`. Con esto **la Pi 5 limita los USB-A a 600 mA en total** [ext, documentación de Raspberry Pi]. No se ha cambiado.
  - La fuente es la oficial de 45 W, que sí ofrece 5,1 V/5 A por PD [ext, fichas de distribuidores]. La culpa es del splitter 8086 [ext, tabla del fabricante]: en POWER solo presenta 5,1 kΩ en CC y no habla PD, y en DATA POWER presenta a la Pi una resistencia fija en CC (10 kΩ a 5 V), que equivale a «3 A por defecto». Con este splitter, la Pi verá 3 A con cualquier fuente.
  - Enchufar la fuente directa no es opción: el USB-C de la Pi es a la vez la entrada de alimentación y el puerto del gadget. Para los dispositivos que consuman, un hub alimentado. `usb_max_current_enable=1` solo tras medir bajo carga (`get_throttled`, EXT5V): sin contrato PD no se sabe si la fuente o el splitter dan más de 3 A a 5 V [?].

## Qué fallaba al arrancar

- `rpi-audio-gadget` fallaba con «no UDC»: el `dtoverlay=dwc2,dr_mode=peripheral` estaba bajo `[pi4]` en `config.txt` (así venía escrito a mano desde el 29-10). `rpi-audiod` no arrancaba por depender del gadget.
- `systemd-modules-load` no encontraba `fs_isoc_pad` (módulo DKMS solo del VL805, compilado para el kernel `-v8`).
- La UI (OLED) y el pHAT sí arrancaban: `gpiochip0` es `pinctrl-rp1` (el conector de 40 pines) en este kernel, y `hifiberry-dac` sale como tarjeta 2.

## Cambios

- [Pi] `config.txt`: el bloque del overlay pasa de `[pi4]` a `[all]`, con un comentario genérico. Copia previa: `/boot/firmware/config.txt.rpi-audio-20261107-154340`. Vale para Pi 4 y Pi 5.
- [repo] `install.sh`: la comprobación del overlay mira solo las líneas que aplican a esta placa (sin sección, `[all]` o el filtro de modelo de la placa leído de `/proc/device-tree/model`). Antes buscaba en todo el fichero: en una Pi 5 daba por bueno un overlay bajo `[pi4]`, y en una imagen trixie limpia la línea `[cm5] dtoverlay=dwc2,dr_mode=host` la hacía negarse («dwc2 overlay without dr_mode=peripheral»). Pruebas nuevas en `tests/test_install.py`.
- [repo] `tools/gadget-watch.sh` y `tools/soak.sh`: el nombre del UDC se lee de `/sys/class/udc` (antes fijo `fe980000.usb`; en la Pi 5 es `1000480000.usb`).
- [repo] `PI_HOST` por defecto en `tools/*.sh`: `no3z@raspberrypi.local`.
- [Pi] `tools/deploy.sh --enable --hat --host akai-force`: `modules-load.d/rpi-audio.conf` queda sin `fs_isoc_pad` (el instalador ya lo añadía solo con VL805). El registro DKMS de `fs-isoc-pad` se deja, por si la SD vuelve a una Pi 4.
- Reinicio de la Pi (sin gadget no podía haber un host transmitiendo).

## Comprobado tras el reinicio [Pi]

- UDC `1000480000.usb`, `bound driver configfs-gadget.rpi-audio`; tarjeta `UAC2Gadget` (3). Estado `not attached`: no hay host en el USB-C.
- `rpi-audio-gadget`, `rpi-audiod`, `rpi-audio-ui` y `rpi-audio-cpu` activos, ninguna unidad fallida. Governor `performance`.
- `rpi-audiod doctor`: todo `ok` salvo el aviso del UDC sin host. jackd en modo Hub sobre `sndrpihifiberry`, 48 kHz, 256 × 3.
- Pruebas locales: `tests/test_install.py` 33 correctas.

## Primera sesión con la Force (21:02–21:15)

Pi 5 en el USB host de la Force; mezclador (PCM2902), GP-150 y luego el Tracker en los USB-A.

- [Pi] La Force enumera el gadget (UDC `configured`, MIDI conectado a los 20 s del arranque). MPC abre el audio a **44,1 kHz** en los dos sentidos al elegir rpi-audio.
- [Pi, código] **Fallo:** en modo Hub los puentes del gadget (`zita-j2a`/`zita-a2j` sobre `hw:CARD=UAC2Gadget`) no abrían: `Can't open ALSA … device`, reintento cada 6 s. `u_audio` en 6.18.50-rpi-2712 exige `PERIODS [4 16]` (`arecord --dump-hw-params`) y el daemon pedía `-n 3`. A mano, `zita-a2j … -p 256 -n 3` falla y `-n 4` abre. Arreglado a `-n 4` y desplegado: los dos puentes corren y el host aparece `running` a 44,1 kHz.
- [Pi] **Rutas:** en Hub, al host solo llega lo que tiene ruta. Las del mezclador seguían con su clave de la Pi 4 (`usb-1-1.3-08bb:2902`); ahora es `usb-3-2-08bb:2902`. Añadidas: mezclador → IN 1–2, OUT 3–4 → mezclador, Tracker 1–8 → IN 15–22, OUT 11–12 → Tracker. GP-150 sigue en IN 3–8 / OUT 5–8. Las rutas viejas quedan esperando.
- [Pi] **Presupuesto FS:** OUT 3–4 → mezclador no se abre: el bus 3 lleva Tracker (720 + 183 B) y la entrada del mezclador (196 B) = 1099 B, el límite medido en la Pi 4. No se ha medido el del RP1.
- [Pi] **GP-150** enumera a 480 Mbit/s en el bus 1: no consume presupuesto FS.
- [Pi] **Tracker a 8 canales en el RP1, reproduciendo (datos distintos de cero):** usbmon, 60 s: 59 997 paquetes de captura de 704/720 B, **0 errores ni vacíos**; mezclador 59 997 sin errores; 0 xruns nuevos. En la Pi 4 (VL805) este caso perdía 40–195 paquetes en 20 s. Falta un soak largo y la integridad con señal conocida.
- [Pi] Desde las 21:11:57 el I²C de la pantalla (`1f00074000.i2c`) da `controller timed out` ~1/s, y `eth0` queda sin portadora; coincide con conectar el Tracker. La Pi no se reinició (mismo arranque, `throttled=0x0`). Se sigue por Wi-Fi.
- [Pi] 21:18: el mezclador pasa al USB-A del bus 1 (con la GP-150, que va a HS). Nueva clave `usb-1-2-08bb:2902`: cada cambio de puerto obliga a rehacer sus rutas (hecho: IN 1–2, OUT 3–4; quitadas las de `usb-3-2`). Los dos puentes abren. usbmon 20 s: mezclador 20 000 paquetes, GP-150 159 992 (microtramas), Tracker 19 999, **0 errores** en todos.
- [?] No comprobado en la Force: si MPC oye cada entrada. No había `FORCE_PASS` para MPC Remote.

## Falta

- **Enumerar y transmitir con un host** (portátil y Force): 26×26, MIDI, soak. Las pruebas de la Pi 4 no valen aquí.
- **Dispositivos USB**: Tracker a 8/10 canales en un controlador del RP1 (¿desaparecen las pérdidas del VL805?), presupuesto FS real de cada controlador, dos FS en controladores distintos.
- **OLED, encoder y sonido del pHAT de oído**: arrancan, no se han tocado ni escuchado.
- **Slots**: los dispositivos sin número de serie se identifican por la ruta USB (p. ej. el mezclador `usb-1-1.3-08bb:2902`). En la Pi 5 la topología cambia (sin hub interno), así que esos dispositivos tendrán clave nueva y habrá que reasignar sus canales y presets. El GP-150 va por número de serie y no cambia.
- **Alimentación**: decidir si los dispositivos alimentados por bus caben en 600 mA o usar un hub alimentado. `usb_max_current_enable=1` solo con una fuente que dé de verdad 5 A.
- `tools/hosts/pi-usb-c-bench.py` (banco del xHCI interno de la Pi 4) ya no aplica: exige una Pi 4 y el overlay bajo `[pi4]`, así que se niega en esta configuración.

## Latencia de ida y vuelta con el portátil como host (2026-11-08)

- Montaje: JACK en el portátil sobre `hw:rpiaudio` a 44,1 kHz, 256×2; en la Pi, conexión temporal `usb_host_in:capture_1 → usb_host_out:playback_1` (sin pasar por ningún dispositivo); `jack_iodelay` en el portátil. Pi en Hub, jackd 256×3 a 48 kHz.
- [Pi] Total host → Pi → host según `[usb] host_period` (los puentes del gadget, 4 periodos): **256: 65,2 ms · 128: 47,0 ms · 64: 39,0 ms**. Restando los ~17,4 ms del propio JACK del portátil (768 tramas), la parte de la Pi baja de ~48 a ~22 ms [est].
- [Pi] 0 xruns en cada ventana de ~30 s. Es una prueba corta: falta un soak con 64 y con la Force, y medir el salto por un dispositivo (cable de bucle en el mezclador).
- Queda la Pi con `host_period = 64` en `/etc/rpi-audio/rpi-audio.toml` para seguir probando; el valor por defecto del código sigue en 256.

## Bajada de periodos con la Force como host (2026-11-08, 14:01–14:30)

- Pi con Tracker y mezclador (la GP-150 no aparecía); MPC abre 26×26 a 44,1 kHz. Cada paso reinicia `rpi-audiod` y observa 2 min: xruns del `status`, avisos en el journal y estado del gadget. MPC volvió a abrir el stream solo tras cada reinicio [Pi].
- [Pi] Limpios (0 xruns, 0 avisos): `host_period` 64; jackd del pHAT `[standalone] period` 128 (×3); `[bridge] period` 128 y 64 (×2); `host_period` 32.
- [Pi] `[standalone] period = 64`: **+8 xruns** en 2 min → vuelto a 128.
- [Pi] Soak de 9 min con jackd 128×3, puentes de dispositivo 64×2 y puentes del gadget 32×4: 0 xruns nuevos, gadget RUNNING en los dos sentidos; zita del gadget ~10–20 % de un núcleo, carga 1,4.
- Sin medir la latencia con estos valores: con la Force no hay bucle de vuelta. Falta medirla con el portátil, el salto por un dispositivo (cable de bucle) y un soak largo antes de cambiar los valores por defecto del repo (siguen en 256/256/256).
- MPC Remote por túnel funcionó para ver la pantalla (Preferences → Audio Device: rpi-audio); no hizo falta tocar nada.
- [Pi] Soak de 60 min con esos valores y la Force en marcha (Tracker + mezclador): **0 xruns nuevos** (14 → 14), gadget RUNNING en las 13 lecturas, carga 1,2–1,6. usbmon 30 s al final: bus 1 (mezclador, captura) 29 999 URB y bus 3 (Tracker 8 ch) 29 999 URB, **0 errores** en ambos.
- [Pi] **Temperatura 79–81 °C** sostenida durante todo el soak; `get_throttled` = `0xe0000` (límite térmico, recorte de frecuencia y throttling *ocurridos* desde el arranque, ninguno activo en las lecturas; sin subtensión). Falta refrigeración activa: con buffers pequeños, un recorte de frecuencia es lo que daría xruns.

## Latencia con los periodos bajados, Hub frente a reloj del host (2026-11-08, 21:57–22:04)

- Mismo montaje que por la mañana (portátil con JACK 256×2 a 44,1 kHz, 768 tramas = 17,4 ms propias; bucle por software en la Pi; `jack_iodelay`).
- [Pi] **Hub** (jackd 128×3, `host_period` 32): 29,1 / 29,5 / 31,1 / 29,1 ms en total; parte de la Pi 514–605 tramas = **11,7–13,7 ms** (por la mañana, ~48 ms). Varía de una apertura a otra por los remuestreadores de zita.
- [Pi] **Reloj del host** (modo `host`, jackd directamente sobre el gadget, sin zita en el bucle): con `[engine] period` 64×3, 991 tramas exactas = 22,5 ms total, **5,1 ms de la Pi**; con 32×3, 935 tramas = 21,2 ms total, **3,8 ms de la Pi**. Mismo valor en cada apertura.
- [Pi] El contador de xruns pasó de 14 a 19 durante estas pruebas; no se sabe qué paso los causó (el JACK del portátil, sin tiempo real, también falló con periodos de 32 y 64 y provocó errores de sincronía en los puentes del gadget).
- Se devolvió la Pi a Hub (copia de `slots.json` previa) con `[engine] period` 64. Ahora el grueso del bucle es el buffer del propio host.
- Referencia externa: [squeaksquad/USB-AoIP](https://github.com/squeaksquad/USB-AoIP) (Pi 5, UAC2, Apache-2.0) mide 11,45 ms a 44,1 kHz Mac → Pi → Dante → conversor → Pi → Mac con buffer de 32 en el Mac; sin JACK ni zita (un único proceso SCHED_FIFO con MMAP) y `req_number=2` [ext].
