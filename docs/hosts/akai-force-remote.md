# Akai Force: MPC Remote, para manejar MPC desde aquí

[MPC Remote](https://github.com/jacob-sabella/mpc-addin-remote) (licencia MIT, de jacob-sabella, en el catálogo de sd88me) es un addin que MPC carga con `LD_PRELOAD`. Sirve su pantalla en el navegador y un servidor MCP. Lo usamos para las pruebas de rpi-audio que necesitan a alguien delante de la Force: elegir rpi-audio tras cada arranque, montar pistas de prueba o mirar la pantalla. Lo autorizó el usuario el 2026-10-30 (`CLAUDE.md`, excepción 2).

El código propio está en `tools/hosts/akai-force-remote/`.

## Instalación

- **Versión:** la 1.0.3, fijada por su sha256 en `install.sh`. La v1.1.0 no tiene binario publicado.
  - La librería necesita glibc 2.17 o posterior, `libc`, `libdl` y `libpthread`.
  - Solo exporta `mpc_remote_addin_start`, así que no intercepta funciones de ALSA y no choca con MidiLoop ni con `mpc_internal_io` [código].
- **No se usa su instalador**, porque escribe en `/data`, en `/etc` y en la raíz del sistema. `install.sh enable` copia el `.so` y su configuración a `AddOns/mpcRemote/` en la SD de MockbaMod, con `run_mpcRemote.sh`, igual que nuestro add-on. El addin lee sus ajustes junto al `.so`.
- **Configuración:** la de serie, con `bind=127.0.0.1` y el puerto 6720. **No tiene contraseña:** solo se entra por túnel SSH y nunca se abre a la red.

```sh
tools/hosts/akai-force-remote/install.sh fetch                    # descarga y comprueba la versión fijada en out/
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-remote/install.sh enable    # luego reiniciar la Force
FORCE_HOST=root@force.local FORCE_PASS=… tools/hosts/akai-force-remote/install.sh tunnel    # localhost:6720, en primer plano
tools/hosts/akai-force-remote/mcp.py --list                       # herramientas del MCP
tools/hosts/akai-force-remote/mcp.py screenshot '{"zoom": 0.5}'   # captura en out/mpc-screen.png
```

`mcp.py` es un cliente MCP mínimo, solo con la biblioteca estándar. Así no hace falta registrar el servidor en un cliente MCP. Si se prefiere: `claude mcp add --transport http mpc http://localhost:6720/mcp`, con el túnel abierto.

## Lo visto en la Force (2026-10-30)

- **Carga [Force]:** con el reinicio cargó, y `/info` responde: pantalla de 1280×800, XR24, y la pantalla táctil en `/dev/input/event0`.
- **Botones [Force]:**
  - las pulsaciones van al `Virtual RawMIDI` de MockbaMod (cliente 133), que el addin encuentra solo;
  - MENU abre el menú, aunque no hace nada en el selector de proyectos del arranque.
- **Manejo [Force]:**
  - un campo desplegable con el borde rojo se abre con `double_tap`; con un toque sencillo no pasa nada;
  - así se eligió rpi-audio en Preferences → Audio Device: MENU, PREFERENCES (1094, 720), AUDIO DEVICE (166, 420), doble toque en el campo y la primera línea de la lista. MPC abrió el gadget a 26×26 y el add-on el códec.
- **Arranque [Force]:** el primer arranque de MPC tras instalarlo se quedó sin MidiLoop y lo reinició el `midicheck` de MockbaMod, a los 15 s. Fue la carrera de la lista `LD_PRELOAD` entre los scripts de los add-ons, no el addin. Está en `docs/hw/2026-10-30-f4-midi.md`.

## Quitarlo

`install.sh disable` y reiniciar la Force. La carpeta `AddOns/mpcRemote/` se queda, inactiva.
