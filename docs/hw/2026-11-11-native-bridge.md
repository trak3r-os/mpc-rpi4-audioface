# 2026-11-11: puente nativo del gadget, medido con el portátil

Puente de `db4821c` (`rpi-audio-hostbridge`, `[usb] host_bridge = "native"`) frente a zita y al modo reloj del host. **Todo con el portátil como host; nada con la Force.**

## Montaje

- Pi 5 en Hub: jackd sobre el pHAT a 48 kHz, 128×3. Gadget UAC2 26×26, 44,1 kHz, S16, paquetes de 250 µs.
- Portátil: jackd 256×2 sin tiempo real sobre `hw:rpiaudio` (768 tramas propias de ida y vuelta).
- `jack_iodelay` en el canal 25. En la Pi, un bucle por software `usb_host_in:capture_25` → `usb_host_out:playback_25`; en modo host, `system:capture_25` → `system:playback_25`. **Parte de la Pi = total − 768 tramas.**
- Configuración de prueba en `/etc/rpi-audio/rpi-audio.d/zz-bench.toml`, borrada al acabar. La Pi quedó en Hub con zita, su configuración por defecto.
- [Pi] 72,5–75,7 °C en todas las medidas, `throttled=0x0` (nunca recortó) y ARM a 2,4 GHz. No hay ventilador (no aparece `cooling_fan`). Con la Force y sus dispositivos, el soak del 2026-11-08 llegó a 79–81 °C ([sesión](2026-11-07-pi5-migration.md)).
- Scripts en el scratchpad de la sesión, fuera del repo. Las salidas en bruto no van a git.

## Hallazgo: sin un PCM abierto, el IN del gadget da 44 000 tramas/s

- [ext] `u_audio_iso_complete` (rpi-6.12.y) reenvía cada petición con la longitud entera nominal y no acumula el resto. A 44,1 kHz con paquetes de 250 µs salen 11 tramas por paquete, es decir **44 000 tramas/s** de ceros, mientras la Pi no tenga abierto y en marcha el PCM de reproducción del gadget.
- [Pi] Medido en el portátil, por el ritmo de llegada de `arecord`: **43 999,6 tramas/s** con `rpi-audiod` parado y **44 099,2** con el puente abierto.
- Consecuencia: entre que el host empieza a transmitir y la Pi abre el gadget, el host recibe 100 tramas/s de menos, y su alineación entre captura y reproducción se desplaza. Afecta a cualquier puente y a cualquier host. Fila nueva en `PLAN.md` §1.
- [est] Esto explica casi toda la variación del viaje de ida y vuelta entre aperturas que el 2026-11-08 se atribuyó a los remuestreadores de zita. El puente nativo varía lo mismo entre aperturas: rango de 84 tramas, frente a 80 de zita. Lo que sí es de zita es la deriva dentro de una misma medida (tabla A).
- [Pi] Remedio para medir: un `jack_freewheel y`/`n` en el portátil reinicia sus streams ALSA sin cambiar la altsetting USB, así que los puentes de la Pi siguen abiertos y el portátil se realinea.
- [est] Remedio de producto, sin probar: dejar abierto el PCM de reproducción del gadget (en silencio) antes de que el host transmita. Encaja con el riesgo de `PLAN.md` de que la Force exige que la Pi esté reproduciendo.

## Latencia

**Método A, aperturas** (como el 2026-11-08): cada medida es un jackd nuevo en el portátil. Cinco aperturas por configuración y última lectura de `jack_iodelay`.

| Puente en la Pi | Parte de la Pi | Mediana | Deriva dentro de la medida | Resyncs por apertura |
|---|---|---|---|---|
| zita (configuración actual) | 11,6–13,4 ms | 11,7 ms | hasta 84 tramas | 0 0 0 0 0 |
| **nativo, margen 1,5 ms, calidad 32** (por defecto) | **6,3–8,2 ms** | **6,5 ms** | **3 tramas** | 0 0 0 0 1 |
| nativo 1,0 ms, q32 | 5,5–8,0 ms | 7,1 ms | 55 | 1 2 1 1 0 |
| nativo 0,75 ms, q32 | 4,7–7,7 ms | 6,7 ms | 79 | 0 1 2 3 1 |
| nativo 0,5 ms, q32 | 4,4–6,1 ms | 4,8 ms | 81 | 2 4 0 3 1 |
| nativo 0,75 ms, q16 | 4,1–6,7 ms | 5,5 ms | 110 | 1 1 3 1 3 |

Referencia del 2026-11-08 con el mismo método: Hub con zita 11,7–13,7 ms; modo host 5,1 ms (64×3) y 3,8 ms (32×3).

**Método B, realineado:** cada apertura más cuatro realineados por freewheel, con la mediana de 24 lecturas por ventana. Dos aperturas por configuración.

| Configuración | Parte de la Pi, mediana | Rango | Ventanas |
|---|---|---|---|
| modo host | 5,5 ms | 2,6–15,9 ms | 8 |
| nativo 0,5 ms | 5,1 ms | 4,4–6,8 ms | 10 |
| nativo 1,0 ms | 7,8 ms | 6,0–8,9 ms | 10 |
| nativo 1,5 ms | 8,6 ms | 6,7–11,1 ms | 10 |
| zita | 14,8 ms | 13,6–18,6 ms | 5 |

- [Pi] Con zita, 4 de los 8 realineados no dieron ninguna lectura en 6 s, y otra ventana saltó a 25 667 tramas (descartada). No se investigó.
- **Incertidumbre:** entre ventanas hay unas 200 tramas (4,5 ms) de dispersión en todos los modos, también en modo host. [est] Viene del portátil: es jackd sin tiempo real, y la alineación entre captura y reproducción depende de cómo arranquen sus streams. Hoy el modo host también varía entre aperturas, cosa que el 2026-11-08 no se vio. Dentro de una ventana, `jack_iodelay` es estable a ±2 tramas. **Los valores absolutos valen ±2 ms; las diferencias entre configuraciones, comparadas por medianas, son lo robusto.**
- [Pi] **Conclusión:** el puente nativo con 1,5 ms quita **5–6 ms** del viaje de ida y vuelta frente a zita: 5,2 ms por el método A y 6,2 ms por el B. Queda unos 1,5–3 ms por encima del modo host. Con 0,5 ms iguala al modo host, pero con resyncs (abajo).

## Resyncs y estabilidad

- [Pi] **Con 1,5 ms:** 1 resync en 5 aperturas de unos 12 s (método A). **0 resyncs y 0 errores** en la prueba de integridad de 300 s y en la de 60 s. El buffer quedó en 53–77 tramas sobre un margen de 66, y como mucho 391 µs de retraso dentro del ciclo.
- [Pi] Con márgenes por debajo de 1,5 ms, 1–4 resyncs por apertura de 12 s. [?] La causa no está identificada: el portátil no registró xruns. 1,5 ms se queda como valor por defecto.
- [Pi] Xruns de JACK en la Pi durante las pruebas (journal, desde las 17:50): **4 con zita** (17:57–17:58, `usb_host_out` sin terminar a tiempo), **1 con el nativo a 0,75 ms** (18:06:24) y 3 del medidor durante el cambio a modo host. **Con el nativo a 1,5 ms, ninguno.**

## CPU (26 canales por sentido, % de un núcleo, media de 10 s)

| | captura | reproducción | jackd |
|---|---|---|---|
| zita | 10,7 | 11,7 | 1,6 |
| nativo 1,5 ms, q32 | 2,6–2,7 | 3,1–3,3 | 1,7–1,9 |

[Pi] El puente nativo gasta **unas 4 veces menos**: 5,7–5,9 % frente a 22,4 % entre los dos sentidos.

## Integridad

`tonegen` (26 tonos de 110·k Hz a −12 dBFS) → `aplay` en el portátil → gadget → puente de captura → bucle en el JACK de la Pi (los 26 canales) → puente de reproducción → gadget → `arecord` → `tonecheck --expect-order`.

- [Pi] **300 s:** los 26 canales en orden y 0 glitches en régimen; solo los del arranque y el final. Los niveles salieron de −12,0 a −36,5 dBFS, bajando con la frecuencia. Era un **artefacto de la prueba**: `tonecheck` mide el nivel entre 0,5 y 1,5 s después de que empiece la señal, y el script conecta los 26 bucles de uno en uno con `jack_connect` justo en ese segundo. La fracción de ventana que falta por canal coincide al milisegundo con su glitch de arranque: ch 8 a 0,51 s y ch 26 a 1,44 s.
- [Pi] **60 s con `--skip 4`**, midiendo ya con los 26 bucles conectados: **los 26 canales a −12,0/−12,1 dBFS**, en orden, 0 glitches, `OK`.
- [repo] Núcleo, en un banco fuera del repo con 26 canales intercalados y llamadas del tamaño del periodo: ganancia 0,00 dB de 110 a 10 000 Hz y −0,66 dB a 18 kHz (44,1 → 48 kHz, q32), en los dos sentidos.

## Informe de latencia a JACK: corregido

- [código] El puente fijaba la latencia de sus puertos al registrarlos, y el siguiente cambio de grafo la sobrescribía. Ahora la fija desde `jack_set_latency_callback` (`4091b83`).
- [Pi] Desplegado y comprobado con `jack_lsp -l`: `usb_host_in` declara **107** tramas de captura, que son (66 + 32) × 48/44,1. `usb_host_out` declara **104** de reproducción, que son 66 × 48/44,1 + 32. Con el bucle conectado, `jack_lsp -L` da 211 en total; el valor sobrevive al cambio de grafo.

## F5 desplegado (por defecto)

- [Pi] `rpi-audiod.service` es ahora `Type=notify`, con `NotifyAccess=main` y `WatchdogUSec=30s`. Tras reiniciarlo, a los 55 s seguía `active/running` con `NRestarts=0`, el mismo instante de arranque y ningún mensaje de watchdog. El latido llega.
- [Pi] `RuntimeWatchdogUSec=1min`: Raspberry Pi OS ya arma de serie el watchdog hardware.
- **No aplicado:** `--read-only` ni `--hw-watchdog`. Cambian el arranque y necesitan el visto bueno del usuario. Detalle en [2026-11-11-f5-appliance.md](2026-11-11-f5-appliance.md).
- `deploy.sh` volvió a sobrescribir `/etc/rpi-audio/rpi-audio.toml`; se repuso desde `rpi-audio.toml.bak-20261111`, que es idéntico al de antes (comprobado con `cmp`).

## Pendiente

- **La Force:** nada de esto está probado con ella. Falta saber si MPC tolera la corrección de ritmo y hacer un soak con el puente nativo.
- Soak de 60 min con el puente nativo, **con ventilador**: sin él la Pi ya está a 72–76 °C, y la Pi 5 empieza a recortar frecuencia a 80 °C.
- Medir con el JACK del portátil en tiempo real, para bajar la incertidumbre de ±2 ms.
- La causa de los resyncs con márgenes por debajo de 1,5 ms, y por qué zita pierde la lectura tras un realineado.
- Probar el remedio de dejar abierto el PCM del gadget antes de que el host transmita.
- Decidir si el puente nativo pasa a ser el de por defecto. Por ahora sigue zita, hasta probarlo con la Force.
