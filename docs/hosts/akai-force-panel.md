# Akai Force / MPC OS: panel de control del hub (rpi-audio Panel)

Un plugin VST2 nativo ARM para MPC OS que muestra y controla el hub desde la pantalla táctil de la Force: dispositivos con su rango de canales, nombres, niveles y silencios, presets y el estado del enlace. No produce sonido: existe por su pantalla. Está en `tools/hosts/akai-force-panel/`, junto a su generador de arte y su empaquetado. Es de la Force, no del proyecto genérico: el protocolo que habla (`docs/MIDI.md`) lo puede usar cualquier host.

**Estado de la evidencia.** Compila para armhf, pasa sus pruebas en el portátil [repo] y el instalador acepta el paquete contra una copia de `MPC.settings` en el portátil [repo]. **Nada de esto se ha probado en la Force**: ni que MPC cargue el plugin, ni que la skin se vea como la vista previa, ni la comunicación con el hub [?]. Lo que falta está al final.

## Qué muestra

Una sola página de 1280×628, tema oscuro con un solo acento (menta) y rojo solo para "silenciado".

- **Cabecera:** título, el estado del enlace y la barra de presets.
  - Enlace: `44.1 kHz | 26x26` (frecuencia del host y canales del gadget, más `| +N` si hay más de 6 dispositivos), `Pi not found`, `Connecting...`, `No reply`, o el último error de una orden durante 4 s. Va en ASCII y en menos de 24 caracteres porque MPC lee los textos en directo con un búfer de 24 bytes y no está comprobado cómo decodifica UTF-8 [?].
  - 8 botones de preset, cada uno con el nombre del preset (`Preset N` si se guardó sin nombre, `-` si está vacío). **SAVE** se activa; el siguiente preset que se toca guarda ahí el enrutado actual y SAVE se apaga solo. Sin SAVE, tocar un preset lo carga.
- **Hasta 6 tiras de dispositivo**, ordenadas por canal IN de inicio y luego por canal OUT (los que no tienen IN, después; los aparcados, al final). Cada una:
  - nombre (al tocarlo abre un selector: Default, Guitar, Bass, Synth, Keys, Drums, Drum machine, Sampler, Vocal, Mic, Mixer, Line, FX, Tracker; Default borra el nombre) y estado (`running`, `parked`, `waiting: USB budget`, `not running`);
  - por sentido, IN y OUT: rango (`IN 3-8`, `OUT 5-8`, `-`), nombres de canal unidos (23 caracteres como mucho), fader de nivel 0–100 % con su valor y botón MUTE;
  - una tira sin dispositivo muestra un hueco vacío; un sentido que el dispositivo no tiene se atenúa.
- **Pie:** *On project load*: Ninguno o Preset 1–8. Se guarda en el proyecto, y al conectar por primera vez el plugin manda `preset load N` una sola vez.

Q-Links (los 16 de la Force, dos bancos de 8): banco 1 = niveles IN de las tiras 1–6 y niveles OUT de las tiras 1–2; banco 2 = niveles OUT de las tiras 3–6 y los silencios IN de las tiras 1–4. El resto de controles es solo táctil. Las vistas previas (`build/preview*.png`) se generan con `skin.py`; las lecturas en directo se dibujan con la regla "altura de MPC = 1,52 × el tamaño de la letra" [ext: docs de sd88me], que no se ha comprobado en pantalla [?].

Con el plugin o sin él, el hub también carga el preset N con un Program Change N−1 (0–7) en el canal 16 del cable de control.

## Cómo habla con rpi-audiod

- Un cliente del secuenciador ALSA, `rpi-audio panel`, con un puerto dúplex, en un hilo propio que arranca `create()` y para `destroy()`. Busca el cliente `rpi-audio` y su puerto `rpi-audio MIDI 1` (el primero si el nombre no aparece), y se suscribe en los dos sentidos. Los dos nombres se pueden cambiar en `panel.conf`, junto al `.so`. Si el cliente no está o desaparece, reintenta cada 2 s y lo muestra.
- Protocolo: SysEx de texto `F0 7D 52 41 … F7` y respuestas `F0 7D 52 42 … F7`, que pueden llegar partidas en varios eventos del secuenciador y se recomponen hasta el F7.
- Cada segundo pide `status` y lo interpreta con un lector JSON propio en el árbol. Órdenes que manda: `mute`, `volume`, `name`, `preset save|load N`. Como mucho 10 órdenes por segundo; los niveles se agrupan cada ~100 ms, así que arrastrar un fader no inunda el puerto.
- **No manda ninguna orden antes del primer `status` válido tras conectar**, ni durante 3 s tras crear la instancia ni 2 s tras restaurar el estado del proyecto (MPC escribe los parámetros guardados al abrir). Lo que MPC escriba antes solo cambia valores locales, y al sincronizar mandan los valores reales de la Pi. Tras un cambio local del usuario, se mantiene su valor 1,5 s (2 s tras salir la orden, porque la Pi la aplica en 1–2 s) antes de aceptar el de `status`.
- `status` de más de ~4000 bytes: `rpi-audiod` quita `fs_load`, `usbbus`, `client` y `card` y nunca nombres, niveles, silencios, rutas ni presets; el plugin no depende de esos campos (el nombre de la tira es `name`, si no `card`, si no la identidad).
- **El plugin avisa a MPC de lo que cambia la Pi** (otro host, la línea de órdenes, un preset): `audioMasterAutomate` para los valores numéricos que cambian y `audioMasterUpdateDisplay` si cambia algún texto, solo al cambiar, nunca en cada sondeo. El wrapper de sd88me solo avisaba desde dentro de `setParameter`, así que hubo que añadir un camino del motor al host (abajo).

## Parámetros

109, en un orden que no se reordena nunca (`params.lock`, `src/panel_layout.h`, `panel_def.py`; la prueba compara la tabla generada con la cabecera): enlace, 8 presets (disparador) y sus 8 nombres, SAVE, On project load y 6 × 15 por tira (nombre, estado, presente, visibilidad IN y OUT, rango, nombres, nivel y mute de cada sentido, tipo y la bandera de su lista). Los nombres que ve MPC son `Preset 3`, `S2 IN Level`, `S4 OUT Mute`…

## Compilar y probar

```sh
cd tools/hosts/akai-force-panel
./build.sh test      # pruebas en el portátil: ASan+UBSan, TSan y el plugin completo con un enlace simulado
./build.sh host      # .so nativo (sin ALSA si el portátil no tiene sus cabeceras)
./build.sh arm       # .so armhf en Docker (imagen rpi-audio-panel-armhf:bullseye, de Dockerfile.arm) y comprobación de ABI
./package.sh         # dist/: el zip y la carpeta lista para el instalador
```

Requisitos: g++, Python 3 con Pillow, Docker. La imagen usa los repositorios de archivo de Debian bullseye (ya no está en los normales). La compilación armhf enlaza `-lasound -lpthread` y libstdc++ en estático, así que no pide ningún `GLIBCXX`; `build.sh arm` falla si algún símbolo pide glibc > 2.32 o si el `.so` exporta algo más que `VSTPluginMain`.

Lo que se prueba: lector JSON, recomposición de SysEx, formato de órdenes, estado → tiras, cola de órdenes (agrupar, ritmo), retención de valores, sincronización antes de mandar nada, reintentos del enlace, y el plugin completo (`VSTPluginMain`, tabla de parámetros, avisos al host, selector de nombres, presets) contra un enlace simulado. Los números de la última pasada están en el informe de la sesión; vuelve a ejecutarlos antes de fiarte.

## Instalar (lo hace el usuario)

El plugin se instala con el instalador de sd88me, en `/media/AKAI_SSD/Synths`, que queda fuera de lo que Claude puede escribir en la Force. Guarda el proyecto antes: el instalador para y arranca MPC.

```sh
scp -r dist/rpi-audio-Panel-1.0.0 root@force.local:/tmp/
ssh root@force.local sh /tmp/rpi-audio-Panel-1.0.0/install.sh -y -t /media/AKAI_SSD/Synths
```

Después, añade **rpi-audio Panel** a una pista desde el navegador de instrumentos. `panel.conf` se conserva al actualizar. Para quitarlo, `uninstall.sh` del mismo paquete.

## Qué ha cambiado en el wrapper de sd88me

Tres cambios pequeños, anotados en `tools/hosts/akai-force-panel/vendor/mpc-vst-plugins/VENDORED.md` y en `THIRD_PARTY.md`: el gancho de parámetros numéricos pasa a un nombre genérico; `mpc_engine_t` gana `poll_changes`; y `housekeeping()` (desde `processReplacing`) avisa al host de lo que el motor ha cambiado por su cuenta. El wrapper viene de la copia de `barsiren-mcp` (MIT, del usuario), que es el commit `faae55a` de sd88me más arreglos y funciona en la Force, no de la cabeza actual de sd88me.

## Sin verificar en la Force

- Que MPC cargue el `.so` (necesita `libasound.so.2`, que MPC ya usa [Force]) y muestre la skin; el tamaño real de los textos en directo y si cortan los nombres largos (una etiqueta de nombre de 168 px cabe unos 14 caracteres).
- Que `snd_seq_open("default")` funcione dentro de MPC (JUCE lo usa para su MIDI, así que debería) y que el cliente `rpi-audio` y su puerto 0 aparezcan con esos nombres en la Force.
- La visibilidad condicional (`IndexedEnabling`) con tres estados, los selectores emergentes con 15 opciones y la tecla de cierre.
- Que MPC llame a `processReplacing` con la pista parada (de eso depende que los cambios de la Pi lleguen a la pantalla) y que no reconstruya la pantalla de automatización por cada `audioMasterAutomate`. Si registra los avisos como automatización al grabar, hay que ajustar.
- Que MPC no reescriba parámetros guardados después de los 2 s de bloqueo tras restaurar el estado.
- Qué hace MPC con el estado del proyecto: el plugin solo guarda *On project load*.
- Cuánto tarda la Pi en aplicar una orden y si la retención de 2 s basta.
- Que `name` en `status` sea el nombre personalizado o el del perfil: el selector marca Default solo si no hay `name`, y ninguna opción si hay uno que no es de la lista.
