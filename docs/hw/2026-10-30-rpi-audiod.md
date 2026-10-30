# 2026-10-30: primera prueba de rpi-audiod con la Force

`rpi-audiod` v1, primera parte (`bridge/rpi-audiod/`), instalado con `tools/deploy.sh --host akai-force`. Arrancado a mano, sin habilitar al arranque; `rpi-audio-keepalive` sigue habilitado como respaldo. Horas en UTC; la Force registra en CET.

**Resultado:** 45 minutos sin un fallo, de 07:43:45 a 08:28 [Pi][Force]. Durante ese tiempo:

- MPC estaba en rpi-audio a 26×26;
- en la Pi corrían jackd y cuatro puentes zita: mezclador PCM2902 2/2 y GP-150 6/4, los dos a 48 kHz;
- en la Force, el add-on `mpc_internal_io` estaba activo.

No hubo ni una salida, ni un atasco, ni un xrun en el registro de `rpi-audiod`. El add-on quedó en +30,7 / −31,2 ppm, con los buffers en su objetivo y sin huecos nuevos.

## Qué hace

- **Alimentar el gadget:**
  - mira "Playback Rate" y "Capture Rate" cada 0,1 s y actúa cuando dos lecturas seguidas coinciden;
  - si el host transmite en los dos sentidos al mismo ritmo, arranca jackd en el gadget;
  - si solo graba de la Pi, reproduce silencio con `aplay`;
  - si no transmite, para todo.
- **Vigilar el gadget, no el proceso:**
  - si el puntero de reproducción del gadget (`/proc/asound/UAC2Gadget/pcm0p/sub0/status`) se queda quieto 1,5 s, cuenta como atasco, igual que si el proceso muere. Es el fallo de jackd del día 29 (`docs/hw/2026-10-29-f2-jack-bench.md`);
  - el arranque tiene 4 s de gracia;
  - el proceso se para con SIGTERM y, si no sale, con SIGKILL;
  - tras 3 fallos seguidos de jackd, reproduce silencio 10 s y vuelve a intentarlo.
- **Puentes:**
  - hay uno por sentido de cada tarjeta USB, con `zita-a2j` o `zita-j2a`, a `-p 256 -n 2`;
  - la frecuencia es la primera de `rates = [48000, 44100]` que admita el dispositivo, con el máximo de canales a esa frecuencia (`/proc/asound/cardN/stream0`);
  - si un puente muere, se relanza con espera creciente;
  - si la tarjeta desaparece o cambia su `usbbus` (se ha reenumerado), sus puentes se paran, desconectando antes sus puertos, y se lanzan de nuevo;
  - el nombre del cliente sale del id de la tarjeta: `gp150_in`, `codec_out`…
- **Canales fijos por identidad:**
  - la identidad es `usb-VID:PID-serie`, o `usb-PUERTO-VID:PID` si no hay una serie válida;
  - las asignaciones se guardan en `/var/lib/rpi-audio/slots.json`;
  - cada dispositivo recibe el primer bloque libre que empiece en canal impar;
  - si un dispositivo vuelve, recupera su bloque; si no hay sitio, queda aparcado;
  - `rpi-audiod assign ID --in N --out M` fija los canales a mano;
  - se reservan OUT 1–2 (la mezcla principal del host) y, en la Force, IN 25–26 para el add-on (`tools/hosts/akai-force.toml`).
- **Volúmenes:** si la reproducción de un dispositivo arranca a 0 en todos los canales, la sube al 80 %. El GP-150 arranca así tras cada reenumeración.
- **Estado:** `rpi-audiod status`, que lee `/run/rpi-audio/status.json`.
- **Tests:** 24 con pytest (`tests/test_audiod.py`) para la lógica pura (`audiod.py`), con salidas reales de la Pi como datos.

## Lo que falló y se arregló

- **jackd no abría `hw:CARD=UAC2Gadget`**: "Audio device … cannot be acquired". La reserva de tarjeta de jackd no entiende la forma `CARD=`. Se cambió a `hw:UAC2Gadget`, como en el banco, y se puso `JACK_NO_AUDIO_RESERVATION=1`, porque no hay sesión de D-Bus.
  - Mientras tanto saltó el respaldo: tras 3 fallos, silencio. MPC no dio error. [Pi][Force]
- **Al ejecutarlo a mano, no veía `GADGET_*`**, que solo existen en el entorno de la unit, y tomaba 2 canales. Ahora, si faltan, lee `/etc/rpi-audio/gadget.env`.
- **Mis reinicios del servicio** durante el despliegue cortaron la reproducción unos instantes:
  - MPC reinició su stream una vez, hacia las 07:43:45;
  - el add-on contó 7 huecos y su control de deriva tardó ~1 min en volver a ±32 ppm.

  Desde entonces, nada.

## Canales con este montaje

| Dispositivo | Entradas de MPC (IN) | Salidas de MPC (OUT) |
|---|---|---|
| Mezclador (CODEC, PCM2902) | 1–2 | 3–4 |
| GP-150 (modo USB actual: 6 entradas y 4 salidas, 48 kHz) | 3–8 | 5–8 |
| Entradas de la Force (add-on) | 25–26 | — |

## Pendiente

- Que el usuario confirme de oído el mezclador, el GP-150 y las vueltas.
- Habilitarlo al arranque (`deploy.sh --enable`) cuando haya pasado esa prueba.
- **Control desde el host:** el usuario prefiere hacerlo por USB y de forma genérica. Se propone añadir una función USB MIDI al gadget (F4), que serviría a la vez para el MIDI de paso de los dispositivos y para un mapa de control de `rpi-audiod`. Espera su visto bueno.
- Un hotplug de verdad: desenchufar el GP-150 y volverlo a enchufar con todo en marcha.
