# 2026-10-29: la Force con su audio interno y rpi-audio a la vez (add-on mpc_internal_io)

Primera prueba en la Force del add-on `tools/hosts/akai-force-internal-io/` (diseño en `docs/hosts/akai-force-internal-io.md`). Horas en UTC; la Force registra en hora local (CET, UTC+1), ya en el día 30.

**Resultado:** con MPC en rpi-audio a 26×26, el master suena también en las salidas principales y en los auriculares de la Force. Las dos entradas de la Force llegan a MPC como entradas 25&26. La deriva se compensa en ~90 s: +32 ppm en reproducción y −31 ppm en captura, frente a los ±31,7 ppm medidos. No hay xruns ni huecos. [Force]

## Permisos y escrituras

- El usuario autorizó instalar y reiniciar la Force ("permision granted"). Después de la carrera de abajo, eligió explícitamente "script corregido + reinicio".
- Escrituras, todas en la SD de MockbaMod (la excepción de `CLAUDE.md`), comprobadas con sha256:
  - `AddOns/mpcInternalIO/mpc_internal_io.so`;
  - `AddOns/mpcInternalIO/mpc_internal_io.conf`;
  - `AddOns/run_mpcInternalIO.sh`.
- Dos reinicios por SSH (`systemctl reboot`): a las 22:55:59 y a las 23:07:25.
- La sesión `rpi-audio-7d` estaba avisada y no lanzó nada en la Force durante la prueba.

## Primer arranque: la lista de LD_PRELOAD de MockbaMod se rompe

- **Síntoma [Force]:**
  - MPC registró `ld.so: object '…/MidiLoop/tkgl_anyctrl_lt.so\nso' … cannot be preloaded`;
  - después, ~1000 veces `ACVX: failed to open rawmidi port hw:2,0,1: Device or resource busy`. La superficie de control de la Force probablemente no respondía;
  - el `midicheck.sh` de MockbaMod reinició MPC.
- **Causa [Force]:**
  - `boot.sh` lanza todos los `AddOns/*.sh` en segundo plano (`"$f" &`) y espera 1 s antes de leer la lista.
  - Cada script lee `/dev/shm/.LD_PRELOAD` y lo reescribe con su librería, **sin cerrojo**, así que se pisan entre sí.
  - Esta vez quedó `…tkgl_anyctrl_lt.so\nso ` (restos de dos escrituras a la vez) y mi script añadió su ruta detrás.
- **Ya pasaba antes del add-on:** en el arranque anterior se había perdido `mockbaMagic.so` de la lista. Con un cuarto script, la carrera tiene más ocasiones.
- **Además, MPC arrancó con su audio interno** (ADA2), no con rpi-audio. Ver más abajo.

## Arreglo: el script del add-on espera y reescribe la lista una vez

- `run_mpcInternalIO.sh` espera 0,5 s. Los otros scripts escriben nada más arrancar.
- Después reescribe la lista una sola vez: solo rutas que existen, sin duplicados, la suya al final.
- **Prueba local [repo], con el BusyBox del portátil:**
  - repara exactamente la lista rota de esta noche;
  - en 200 carreras contra los tres scripts de MockbaMod, no deja ninguna ruta rota ni ninguna línea de más.
- **Lo que no arregla:** las entradas que los otros tres pierden entre sí, sin llegar a romperlas. En local pasa en 199 de 200 carreras. Es un fallo de MockbaMod; no se ha tocado su `boot.sh`.

## Segundo arranque (23:07:25)

- **Lista limpia [Force]:** `libforce_cursor.so tkgl_anyctrl_lt.so mpc_internal_io.so`.
  - `mockbaMagic.so` volvió a perderse por la carrera entre los otros. Esa librería dice no soportar la MPC 3.9.1.2.
  - MidiLoop cargó, con 0 errores ACVX y sin reinicio de MPC.
- **El add-on cargó:** `loaded: gadget 'rpiaudio', codec 'hw:CARD=ADA2', 4 playback and 2 capture pairs, gain -12.0 dB`.
- **MPC volvió a abrir su audio interno**, no rpi-audio. El add-on no vio ningún `snd_pcm_open` del gadget.
  - En F1 sí lo abría solo al arrancar.
  - En estos dos arranques la Pi no estaba reproduciendo (siguiente sección). Si esa es la causa está por ver [?]: el próximo arranque con el keepalive lo dirá.

## jackd se quedó parado al reiniciarse la Force

- **Qué pasó [Pi]:**
  - antes de la prueba, la Pi tenía jackd con los puentes del GP-150 y del mezclador;
  - al reiniciarse la Force, el driver ALSA de jackd dio 5 "poll time out" de 2,2 s y paró (22:56:13);
  - **el proceso siguió vivo** con el gadget abierto, así que el guardián, que solo miraba si existía el proceso, no hizo nada.
- **Desde entonces, nadie reproducía en el gadget.** Es el fallo conocido de F1 (`docs/hw/2026-10-29-f1-force.md`):
  - con el usuario eligiendo rpi-audio a mano, MPC dio `Unexpected audio capture error: -5` a los 50 s (23:14:40) y otra vez a las 23:15:58;
  - las dos veces volvió a su audio interno.
- **El control de deriva del add-on se disparó en esas sesiones:** llegó al tope de ±1000 ppm.
  - Es coherente con los reinicios de stream que hace MPC cuando la Pi no reproduce: cada uno reinicia el anillo y MPC vuelve a llenar su buffer.
  - Con la Pi reproduciendo no ha vuelto a pasar.
- **Bien resuelto en esos dos errores [Force]:** el add-on cerró el códec en cuanto MPC cerró el gadget, y MPC recuperó su audio interno sin problemas.
- **Arreglo:**
  - SIGTERM no cerró jackd; SIGKILL sí (23:17);
  - se arrancó `rpi-audio-keepalive` (silencio);
  - la lección para F2 está en `docs/hw/2026-10-29-f2-jack-bench.md`.

## Con la Pi reproduciendo (desde 23:18:02)

- **Apertura:** el usuario eligió rpi-audio. MPC lo abrió como `hw:0`, a 26×26, S16 y periodo 128. El keepalive empezó a reproducir en el acto.
- **El add-on abrió ADA2** a 4 canales para la reproducción y 2 para la captura: S32_LE, 44,1 kHz, periodo 64, buffer 1024.
- **Líneas de estado [Force]**, una cada ~29 s:

| Desde la apertura | Reproducción | Captura |
|---|---|---|
| 29 s | −83,5 ppm, llenado 499 de 512 | −24,2 ppm, 257 de 256 |
| 58 s | +39,9 ppm, 512 de 512 | −32,9 ppm, 256 de 256 |
| 87 s | +32,2 ppm, 512 de 512 | −31,3 ppm, 256 de 256 |
| 116 s | +29,9 ppm | −31,6 ppm |
| 145 s | +35,2 ppm, 513 de 512 | −32,2 ppm, 256 de 256 |

  En todas: 0 xruns del códec, 0 huecos y 0 desbordes.
- **Lo que comprobó el usuario [Force]:**
  - el master se oye en las salidas principales y en los auriculares;
  - una fuente en las entradas de la Force, en una pista con entrada 25&26, se oye.

## Arranques 3 y 4 (prueba de salidas)

- **Ajustes de prueba:** con permiso del usuario, se subieron unos ajustes temporales (`install.sh conf`): `playback = 1:1, 2:2, 3:3, 4:4`. Así MPC Out 1/2 va al par 1/2 del códec y Out 3/4 al par 3/4.
- **Arranque 3 (23:25:21) [Force]:**
  - lista limpia y 0 errores ACVX, pero **MPC arrancó sin el add-on**;
  - MPC leyó la lista (`libforce_cursor.so tkgl_anyctrl_lt.so`) antes de que el script la escribiera. Un retraso fijo de 0,5 s no basta: los scripts de la SD pueden arrancar tarde;
  - **MPC volvió a abrir su audio interno también sin el add-on**, así que el add-on no es la causa de eso. MPC no guarda el dispositivo en `MPC.settings`, ni en otro fichero de `/data/Settings` [Force]. Sigue abierto [?]; de momento, hay que elegir rpi-audio a mano tras cada arranque.
- **El script, otra vez [repo]:**
  - ahora escribe en cuanto arranca y vigila la lista cada 0,1 s durante 5 s;
  - la reescribe solo si le falta algo o tiene una ruta rota;
  - conserva todas las librerías que ha visto en ella.
- **Prueba local con BusyBox [repo]:** los tres scripts de MockbaMod arrancan con 0–0,3 s de retraso, y la lista se lee al segundo.
  - En 100 carreras: 0 rutas rotas y el add-on siempre dentro.
  - En 6 de cada 100 falta alguna de las otras librerías, que se perdió entre dos comprobaciones. Sin el script, en local se pierde alguna en 199 de 200.
  - Comprobar cada 20 ms no mejora (7 de 100).
- **Arranque 4 (07:33:11 del día 30) [Force]:**
  - lista `mockbaMagic.so tkgl_anyctrl_lt.so mpc_internal_io.so`, sin errores ACVX, con el add-on cargado;
  - esta vez se perdió `libforce_cursor.so`, el cursor del ratón, por la carrera entre los otros;
  - MPC, otra vez con el audio interno.

## Pendiente

- Saber qué par del códec son las salidas principales y cuál los auriculares. Ahora el master va a los dos.
- Ajustar el nivel: el add-on lo manda a −12 dB.
- Un soak largo, de 30 minutos, mirando las líneas de estado.
- El próximo arranque de la Force con el keepalive: ¿abre MPC rpi-audio solo?
- Volver a poner jackd y los puentes (GP-150, mezclador) sin perder la reproducción continua. Lo resuelve el supervisor de F2. Mientras tanto, el keepalive.
