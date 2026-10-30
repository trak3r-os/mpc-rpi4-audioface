# MIDI: puertos del gadget, MIDI de paso y mapa de control

Con `GADGET_MIDI_PORTS` mayor que 0, el gadget añade una función USB MIDI (`f_midi`) junto al audio. El host ve un solo dispositivo con N puertos MIDI, que llamaremos cables, en cada sentido. En Linux se llaman `rpi-audio MIDI 1` … `rpi-audio MIDI N`. Cualquier host USB los entiende, y `rpi-audiod` los usa para dos cosas:

- **MIDI de paso:** cada puerto MIDI de cada dispositivo USB enchufado a la Pi va a un cable propio, en los dos sentidos.
- **Control:** un cable lleva órdenes para `rpi-audiod`: asignar canales, silenciar y ajustar niveles. Cualquier host puede mandarlas. Para MPC basta una pista MIDI; un DAW o un VST pueden además leer el estado.

Estado de la evidencia:
- probado contra un portátil Linux: los cuatro cables, el MIDI de paso en los dos sentidos, las órdenes SysEx y los CC [Pi][portátil];
- en la Force, MPC abre el audio y se suscribe a los cuatro cables [Force];
- el control desde MPC está por probar.

Detalle en `docs/hw/2026-10-30-f4-midi.md`.

**Las respuestas salen con `aplaymidi`, no con `aseqsend`.** Un puerto del secuenciador del kernel solo abre su salida cuando alguien está suscrito a él, y `aseqsend` envía sin suscribirse [Pi]. `aplaymidi` sí se suscribe; recibe un fichero MIDI de una pista con el SysEx.

## Gadget

| Ajuste (`gadget.env`) | Por defecto | Qué hace |
|---|---|---|
| `GADGET_MIDI_PORTS` | 0 | Cables por sentido, de 0 (sin MIDI) a 16 |
| `GADGET_MIDI_ID` | `MIDIGadget` | Id de la tarjeta ALSA del MIDI en la Pi; `rpi-audiod` busca el gadget por él |

- La función de audio se enlaza primero, así que los números de sus interfaces no cambian.
- Con MIDI, `bcdDevice` pasa de 0x0100 a 0x0101. Así, un host que guarda los descriptores por VID, PID y revisión (Windows) los vuelve a leer.
- En la Pi, el cable k es el puerto k−1 del cliente del secuenciador ALSA de la tarjeta `GADGET_MIDI_ID`. Para que exista, tienen que estar cargados `snd-seq` y `snd-seq-midi`; `deploy.sh` los deja cargándose al arrancar.

## Cables

- El cable de control es `[midi] control_port` (1 por defecto).
- **Puntos MIDI:** cada puerto del secuenciador de una tarjeta de sonido USB es un punto MIDI. Su identidad es `IDENTIDAD/P`: la identidad del dispositivo (la misma que en el audio) y el número de puerto, por ejemplo `usb-1234:5678-ABC/0`.
- **Asignación:** cada punto recibe un cable distinto del de control, fijo por identidad. Las asignaciones se guardan en `slots.json` bajo `"midi"` y se reparten como los canales de audio, pero de uno en uno y sin alinear a pares.
  - Un punto que vuelve recupera su cable.
  - Un punto nuevo toma el primer cable libre que no tenga guardado un punto ausente; si no hay ninguno, le quita el suyo a un ausente; si tampoco, queda aparcado.
- **Con un solo cable** (`GADGET_MIDI_PORTS=1`), todos los puntos comparten el cable 1 con el control. Es para hosts que solo usan un cable.
- `rpi-audiod assign IDENTIDAD/P --midi K` fija un cable. Sin `/P`, se entiende el puerto 0.

## Rutas

- **Cuándo:** solo mientras el gadget está conectado a un host (`/sys/class/udc/*/state` es `configured`).
- **Con qué:** suscripciones del secuenciador en el kernel (`aconnect`), así que no añaden latencia en espacio de usuario.
- **Qué rutas:** para un punto con el cable k:
  - si el puerto del dispositivo es legible (R), va del dispositivo al gadget, puerto k−1: el host lo recibe;
  - si es escribible (W), va del gadget, puerto k−1, al dispositivo: lo que el host manda por ese cable.
- **Limpieza:** `rpi-audiod` quita las suscripciones entre un puerto del gadget y un cliente de una tarjeta USB que no correspondan a ninguna ruta suya, por ejemplo tras una reasignación. Nunca toca otras: las de `aseqdump`, otros programas o las que pongas a mano entre dispositivos.

## Control

Todo va por el cable de control, en los dos sentidos.

### SysEx de texto

```
F0 7D 52 41 <texto ASCII> F7      orden
F0 7D 52 42 <texto ASCII> F7      respuesta
```

- `7D` es el identificador para uso no comercial; `52 41` ("RA") lo separa de otros usos de `7D`.
- El texto solo puede tener bytes de 0x20 a 0x7E.
- **La respuesta va por el mismo cable con `52 42` ("RB").** Así, si un host devuelve el cable como eco, por ejemplo con MIDI thru, una respuesta no vuelve a entrar como orden. Su texto empieza por `ok`, por `error: ` o, en el caso de `status`, es un JSON que empieza por `{`.
- **Ritmo:** se atienden hasta 20 órdenes por décima de segundo, y las respuestas salen en orden desde un hilo aparte. Si se acumulan más de 20 respuestas pendientes, se descarta la nueva.

| Orden | Respuesta | Efecto |
|---|---|---|
| `ping` | `ok rpi-audio` | — |
| `status` | JSON | El mismo contenido que `/run/rpi-audio/status.json` |
| `assign IDENTIDAD [in=N] [out=N] [midi=K]` | `ok` | Fija el primer canal IN, el primer canal OUT o el cable MIDI. `midi=` sin `/P` significa `/0` |
| `mute IDENTIDAD in\|out on\|off` | `ok` | Corta o repone las rutas de audio de ese sentido |
| `volume IDENTIDAD in\|out PORCENTAJE` | `ok` | Nivel del propio dispositivo, de 0 a 100: `in` es su captura (lo que llega al host) y `out` su reproducción |

Las órdenes cambian el estado guardado (`slots.json`), igual que la línea de órdenes, y el servicio lo aplica en uno o dos segundos. Con una identidad desconocida, la orden se guarda igualmente y se aplica cuando el dispositivo aparece.

### CC en los canales de control

Sirven para hosts que no mandan SysEx, como una pista MIDI de MPC con automatización o Q-Links. Van por el cable de control: en `[midi] channel_in` (16 por defecto) para lo que entra al host (IN) y en `channel_out` (15) para lo que sale de él (OUT).

El número de CC indica a qué dispositivo va la orden: N es el canal del host en el que empieza su bloque en ese sentido, de 1 a 27. Por ejemplo, si el GP-150 entra en MPC por IN 3–8, su nivel de captura es el CC 35 en el canal 16.

| Canal | CC | Efecto | Valor |
|---|---|---|---|
| `channel_in` (16) | 32 + N (33–59) | Nivel de captura del dispositivo cuyo bloque IN empieza en N | 0–127 → 0–100 % |
| `channel_in` (16) | 64 + N (65–91) | Silencia su entrada (IN) | ≥ 64 silencia, < 64 repone |
| `channel_out` (15) | 32 + N (33–59) | Nivel de reproducción del dispositivo cuyo bloque OUT empieza en N | 0–127 → 0–100 % |
| `channel_out` (15) | 64 + N (65–91) | Silencia su salida (OUT) | ≥ 64 silencia, < 64 repone |

Ningún otro CC es una orden. Así quedan fuera los mensajes de modo de canal (120–127, como "All Notes Off"), que muchos hosts mandan al parar, y los CC que suelen reiniciar: 0, 1, 7, 10 y 64. Un CC de esas dos franjas que no corresponde a ningún dispositivo se ignora y se anota en el registro. Con un solo cable, los dispositivos también reciben estos CC y estos SysEx: un aparato que escuche en los canales 15 o 16, o en modo omni, los verá.

Una orden SysEx debe caber en unos 200 bytes. El secuenciador corta los SysEx largos en trozos, y una orden partida no se reconoce. Una respuesta de más de unos 4 KB podría llegar cortada [?]: el buffer de salida del puerto en el kernel es de 4 KB. Con dos dispositivos, `status` ocupa menos de 1 KB, y cada dispositivo de audio añade unos 340 bytes.

## Estado guardado (`/var/lib/rpi-audio/slots.json`)

```json
{
 "in": {"IDENTIDAD": 3}, "out": {"IDENTIDAD": 5},
 "in_channels": {"IDENTIDAD": 6}, "out_channels": {"IDENTIDAD": 4},
 "midi": {"IDENTIDAD/0": 2},
 "mute": {"in": ["IDENTIDAD"], "out": []},
 "volume": {"in": {"IDENTIDAD": 100}, "out": {"IDENTIDAD": 80}}
}
```

- Un nivel guardado se vuelve a aplicar cada vez que el dispositivo aparece.
- Sin nivel guardado, rige `[bridge] min_volume`: si la reproducción arranca a 0, se sube a ese nivel.
