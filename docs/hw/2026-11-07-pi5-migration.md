# 2026-11-07: cambio de la Pi 4 a una Pi 5 con la misma SD

El usuario cambió la Pi 4 por una Pi 5 y arrancó con la misma tarjeta SD. Sesión de puesta en marcha; sin host USB ni dispositivos USB conectados.

## La placa

- [Pi] Raspberry Pi 5 Model B Rev 1.1, **1 GB**, 4 × Cortex-A76 (CPU part 0xd0b). Kernel `6.18.50+rpt-rpi-2712`, **páginas de 16 KiB**. Debian 13 trixie. EEPROM al día (25-09-2026).
- [Pi] Red: `raspberrypi.local`, Ethernet 192.168.1.109 y Wi-Fi 192.168.2.34 (`bender_5G`). Misma clave de host que la Pi 4 (misma SD). Las IP anteriores (.106, .229) ya no responden.
- [Pi] USB: dos xHCI del RP1, `xhci-hcd.0` (buses 1 USB2 de 2 puertos y 2 USB3) y `xhci-hcd.1` (buses 3 y 4). No hay VL805 ni hub interno. Los dispositivos FS caen en el bus 1 o el 3, así que el presupuesto «por bus» de `rpi-audiod` queda por controlador.
- [Pi] Alimentación: `max_current` del firmware 3000 mA (fuente sin USB-PD de 5 A, por el splitter), `usb_max_current_enable=0`, EXT5V 5,07 V, `throttled=0x0`. Con esto **la Pi 5 limita los USB-A a 600 mA en total** [ext, documentación de Raspberry Pi]. No se ha cambiado.

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

## Falta

- **Enumerar y transmitir con un host** (portátil y Force): 26×26, MIDI, soak. Las pruebas de la Pi 4 no valen aquí.
- **Dispositivos USB**: Tracker a 8/10 canales en un controlador del RP1 (¿desaparecen las pérdidas del VL805?), presupuesto FS real de cada controlador, dos FS en controladores distintos.
- **OLED, encoder y sonido del pHAT de oído**: arrancan, no se han tocado ni escuchado.
- **Slots**: los dispositivos sin número de serie se identifican por la ruta USB (p. ej. el mezclador `usb-1-1.3-08bb:2902`). En la Pi 5 la topología cambia (sin hub interno), así que esos dispositivos tendrán clave nueva y habrá que reasignar sus canales y presets. El GP-150 va por número de serie y no cambia.
- **Alimentación**: decidir si los dispositivos alimentados por bus caben en 600 mA o usar un hub alimentado. `usb_max_current_enable=1` solo con una fuente que dé de verdad 5 A.
- `tools/hosts/pi-usb-c-bench.py` (banco del xHCI interno de la Pi 4) ya no aplica: exige una Pi 4 y el overlay bajo `[pi4]`, así que se niega en esta configuración.
