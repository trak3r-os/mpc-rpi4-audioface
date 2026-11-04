# 2026-11-04: apagar y reiniciar desde el OLED

El usuario pregunta si debe desenchufar para apagar y propone una opción de menú; después solicita también reset. Se interpreta como **reinicio de Linux conservando ajustes**, sin restauración de fábrica. Se añaden las dos acciones y se deja la Pi encendida durante la validación.

## Implementación [código, repo]

- **Power** al final del menú principal, después de Settings: **Shut down** y **Restart**. Ambas abren una confirmación con **Cancel** seleccionado. Girar hasta la acción y pulsar PUSH/CONFIRM la ejecuta; BACK cancela. Un doble clic inicial no apaga/reinicia. Las pantallas avisan de que el audio se detendrá.
- Una vez solicitada, la acción queda en una pantalla de espera y los eventos siguientes no acumulan más solicitudes. Si falla, se conserva el error y BACK vuelve a la confirmación. Los resultados de apagado/reinicio se muestran aunque haya habido giros/pulsaciones ignorados durante la espera; no se pierden por el filtro de revisiones de mensajes antiguos.
- El trabajador de comandos local ejecuta únicamente `/usr/bin/sudo -n /usr/bin/systemctl poweroff` o `reboot`. No se añade un comando de sistema al protocolo de audio/USB MIDI. La política `/etc/sudoers.d/rpi-audio-power`, root y modo 0440, autoriza solo esos dos argv exactos; instalación, actualización UI-only y desinstalación gestionan el archivo. `visudo -cf` lo valida antes de instalar. El instalador declara sudo como dependencia.
- El apagado/reinicio sigue el ciclo normal de systemd y las paradas ya existentes de los servicios de audio/gadget; no usa force ni corta la alimentación por GPIO. La UI avisa de esperar al apagado y al fin de la actividad del LED de la Pi antes de desenchufar. La pantalla negra no se presenta como prueba de apagado completado, porque la UI termina antes y su salvapantallas también puede apagarla.
- El simulador no ejecuta acciones de sistema. Se amplían manual/DISPLAY y capturas con la figura 23, Power y Cancel seleccionado. La vista móvil se revisa visualmente. Referencia de manejo: [guía oficial de iniciación de Raspberry Pi](https://magazines-static.raspberrypi.org/books/full_pdfs/000/000/026/original/000_RPi_BeginnersGuide_DIGITAL.pdf), que indica esperar al fin del parpadeo verde antes de retirar la fuente tras shutdown.

## Verificación y despliegue [repo, Pi]

- **451 passed, 13 skipped**, con tomli como tomllib en Python 3.10. Incluye cuatro combinaciones de acción/botón, Cancel por defecto, BACK, protección contra repetición, fallo recuperable con eventos mientras el comando está pendiente, despacho con subprocess simulado, rechazo de acciones/argumentos desconocidos y política/desinstalación en raíz temporal. Ninguna prueba ejecuta apagado/reinicio reales.
- Flake8 de UI/pruebas/herramientas modificadas, `bash -n install.sh tools/deploy.sh` y comprobación de espacios correctos.
- Política instalada validada por visudo. Como usuario rpi-audio, comprobación **solo de permisos** con `sudo -n -l`: `systemctl poweroff` y `systemctl reboot` permitidos; `poweroff --force` y `restart rpi-audiod` denegados. Estas consultas no ejecutan las órdenes consultadas.
- Instalación con `tools/deploy.sh --ui-only`, incluyendo política y reinicio exclusivo de la UI. Verificación del menú instalado y doble pulsación que cancela mediante el modelo en memoria, sin enviar órdenes al sistema. Audio conserva PID **305906**, servicios activos y `NRestarts=0`.

**Límite:** no se ha ejecutado un apagado ni reinicio completo en esta sesión. Su funcionamiento real, el estado final del OLED y la secuencia de LEDs quedan pendientes de una prueba física elegida por el usuario; las pruebas actuales comprueban interfaz, despacho y permisos.
