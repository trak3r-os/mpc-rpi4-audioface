# rpi-audio: hub de audio USB genérico sobre una Raspberry Pi 4

La Pi se presenta ante un host USB como una interfaz de audio UAC2 (gadget configfs en el USB-C), y detrás agrega y enruta cualquier dispositivo de audio o MIDI USB. El proyecto es genérico: **no pongas nombres ni supuestos ligados a un host concreto** en el código, la configuración por defecto ni los nombres. Lo específico de cada host (la Akai Force es el primero que probamos) va en `docs/hosts/` y `tools/hosts/`. El plan, con su evidencia, está en `docs/PLAN.md`.

Al empezar cada sesión, lee `docs/STATUS.md` (estado y traspaso) y la fase en curso de `docs/PLAN.md`. Mantén el foco en la tarea actual.

## Reglas

- **Evidencia.** Marca los hechos como en el plan: [Pi], [Force], [repo], [código], [ext], [est] o [?]. Nunca digas "hecho", "funciona" o "estable" sin haber ejecutado en el mismo turno el comando que lo demuestra, y di qué falta. Una prueba contra un host (p. ej. el portátil) no demuestra nada sobre otro (p. ej. la Force).
- **Hosts: solo lectura.** En un host (la Force), por SSH, solo diagnósticos que no escriban (`tools/hosts/`). Nunca instales, escribas ficheros, reinicies servicios ni cambies preferencias en un host. Tres excepciones:
  1. **La SD de MockbaMod** (autorizada por el usuario el 2026-10-29): en la Force se puede escribir en `/media/662522`, de donde MPC carga sus add-ons con `LD_PRELOAD`. Nunca con una prueba en marcha, y nada fuera de esa ruta.
  2. **MPC Remote** (autorizada por el usuario el 2026-10-30): el addin MPC Remote se instala en esa misma SD (`tools/hosts/akai-force-remote/`). A través de su MCP se puede manejar MPC para probar rpi-audio: ver la pantalla, tocarla, pulsar botones, mandar MIDI y cambiar las preferencias de audio y MIDI. También se pueden crear pistas de prueba en un proyecto nuevo.
     - Nunca guardar, sobrescribir ni borrar proyectos, samples o ficheros del usuario.
     - Nunca pulsar REC ni tocar lo que no tenga que ver con la prueba.
     - Siempre con `bind=127.0.0.1` y por túnel SSH.
  3. **rpi-audio Panel** (autorizada por el usuario el 2026-10-30): el plugin `tools/hosts/akai-force-panel/` se instala, actualiza o desinstala con el `install.sh`/`uninstall.sh` de su paquete.
     - Ese instalador escribe solo su carpeta en `/media/AKAI_SSD/Synths`, registra el plugin en `MPC.settings` y reinicia MPC.
     - Nada más en AKAI_SSD ni en las preferencias, y nunca con un proyecto del usuario sin guardar.

  Las contraseñas van en variables de entorno (`FORCE_PASS`), nunca en un fichero. La Force se resuelve como `force.local`.
- **Pi.** `no3z@192.168.1.106`, con clave SSH. Los cambios de sistema van por `tools/deploy.sh` (idempotente) y se anotan en `docs/hw/`. Nada destructivo sin preguntar: formatear, borrar datos, cambiar la red o el arranque.
- **Gadget.** Se monta una vez al arrancar (`rpi-audio-gadget.service`). No reenlaces el UDC en bucle: los reenlaces repetidos pueden bloquear el dwc2.
- **No editar** `../track3r-os`, `../o3-sdk` ni `../o3-303`. Lo que necesite el Tracker se anota en `docs/PLAN.md` §7.
- **Privacidad.** Nada de contraseñas, números de serie ni salidas en bruto en git: van a `out/`, que está ignorado. En `docs/hw/` solo van resúmenes.
- **Licencia.** GPL-3.0-or-later. El código reutilizado lleva su aviso en `THIRD_PARTY.md`. No uses amidiminder: su autor prohíbe el trabajo derivado con IA.
- **Git.** El usuario dio permiso total sobre el repo el 2026-10-30: commit y push a `origin` cuando haga falta, sin reescribir historia ya publicada. `origin` es `git@github-trak3r:trak3r-os/mpc-rpi4-audioface.git` (alias SSH `github-trak3r`, no `github.com`). Los commits van como `trak3r-os <342899900+trak3r-os@users.noreply.github.com>`, el correo oculto de GitHub, nunca con el correo personal ni el del trabajo. Está fijado en la configuración local del repo.

## Estructura

`gadget/`: el gadget por configfs · `systemd/`: units · `config/`: configuración que se instala en `/etc/rpi-audio/` · `tools/`: inventario, despliegue, tonos de prueba · `tools/hosts/`, `docs/hosts/`: lo específico de cada host · `tests/`: pytest de la lógica pura · `docs/hw/`: sesiones con hardware.

## Comandos

```sh
tools/pi-facts.sh > out/pi-facts-$(date +%F-%H%M%S).txt          # inventario de la Pi (solo lectura)
tools/deploy.sh                                                   # copia e instala en la Pi (sudo sin contraseña)
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-probe.sh > out/force-probe-….txt
python3 -m pytest -q tests
```

Las comprobaciones de tonos están en `docs/STATUS.md`.
