# 2026-10-29: F2, los dispositivos USB en la Pi 4

Los tres dispositivos de prueba van a los USB-A de la Pi 4, directos y sin hub. Todos pasan por el VL805 y su hub interno VIA 2109:3431, que tiene **un solo TT**. Mientras tanto, el gadget sigue conectado a la Force con el keepalive en silencio. Las salidas en bruto (con números de serie) están en `out/usb-inventory-*`, `out/usb-descriptors-*` y `out/gp150-*`.

## Inventario [Pi]

| Dispositivo | Velocidad | Audio | Endpoints isócronos (wMaxPacketSize, bInterval) |
|---|---|---|---|
| **Tracker** (track3r-os, 16d0:0e9f, `bcdDevice` 1.01) | **Full-Speed** | UAC1, **8 canales hacia la Pi, 2 hacia el Tracker**, S16, solo 44.100 Hz. Lleva también MIDI y CDC ACM | IN 720 B; OUT 180 B (asíncrono); feedback 3 B; los tres a 1 ms. **903 B por frame** |
| **Mezclador de 2 canales** (Burr-Brown PCM2902, 08bb:2902) | **Full-Speed** | UAC1, 2 entradas y 2 salidas, S16. La captura admite de 8 a 48 kHz; la reproducción, 32/44,1/48 kHz | OUT 192 B (adaptativo); IN 196 B a 48 kHz o 180 B a 44,1 kHz (asíncrono) |
| **Valeton GP-150** (84ef:0186) | **High-Speed** | UAC2, **2 entradas y 2 salidas**, 24 bits en S32_LE, **solo 48 kHz** | IN 256 B y OUT 256 B, asíncronos, cada 125 µs |

- El Tracker estaba en un modo **8/2**, no en el "10 OUT / 2 IN" que se esperaba. Está por confirmar con el usuario qué modo tiene elegido.
- El GP-150 tiene **2/2, no 6/4** como suponía el plan.
- La primera vez el GP-150 no apareció: el kernel no registró ningún intento de conexión. Tras reconectarlo, enumeró bien.
- El GP-150 es High-Speed, así que pasa por el hub sin TT y **no gasta del presupuesto Full-Speed**.

## Presupuesto Full-Speed del TT del VL805 [Pi]

Se abrieron los streams con `arecord` a `/dev/null` y `aplay` de silencio, contando los bytes recibidos.

| Combinación | Reserva FS (B/frame) | Resultado |
|---|---|---|
| Tracker 8/2 solo | 903 | OK |
| Mezclador solo (los dos sentidos, a 44,1 o a 48 kHz) | 372–388 | OK, bytes exactos |
| GP-150 solo (los dos sentidos) | 0 FS | OK, bytes exactos |
| Tracker 8/2 + reproducción del mezclador | 903 + 192 = 1095 | OK |
| Tracker 8/2 + grabación del mezclador a 48 kHz | 903 + 196 = 1099 | OK, bytes exactos (3 de 3) |
| Tracker 8/2 + GP-150 + grabación del mezclador a 48 kHz | 1099 FS | **OK**: los tres con los bytes exactos durante 9 s |
| Tracker 8/2 + los dos sentidos del mezclador | 903 + 196 (o 180) + 192 ≈ 1270–1290 | **Rechazado**: `Not enough bandwidth for altsetting 1`, `usb_set_interface failed (-28)` |
| Tracker 8/2 + grabación del mezclador a **44,1 kHz** | 903 + 180 = 1083 | **Falla** en 0,6 s con EIO y 0 bytes (3 de 3), **sin mensaje del kernel** |
| Solo la captura del Tracker + el mezclador (reproducción + grabación a 44,1) | 720 + 192 + 180 = 1092 | Reproducción OK; grabación a 44,1 con EIO |

- **El xHCI acepta hasta al menos 1099 B y rechaza hacia 1270 B** por frame en el TT único.
- **La captura del PCM2902 a 44,1 kHz falla con otro dispositivo FS en marcha**, aunque a 48 kHz ocupa más. Sin causa conocida:
  - quizá el planificador del TT del VL805 no logra colocar ese endpoint en los microframes (no hay error, solo no llegan datos) [est];
  - quizá sea una rareza del PCM2902 [?].
  - Sin debug dinámico no se puede ver.
- **Consecuencia:** en la Pi 4 tal cual, el Tracker 8/2 y el mezclador solo caben con **el mezclador en un sentido** (mejor la grabación, a 48 kHz). Es el riesgo "presupuesto FS del VL805" de `docs/PLAN.md`, ya medido.
- **Salidas, por orden de coste:**
  1. **Un hub USB 2.0 Multi-TT** alimentado, entre la Pi y los dispositivos Full-Speed. En teoría cada puerto tiene su propio TT y su propio milisegundo, y el hub interno lo atraviesa a High-Speed. Pero `docs/PLAN.md` recoge informes de que con el VL805 no ayuda: **se prueba antes de comprarlo**, con un hub que ya se tenga. Hay que comprobar que es MTT: `lsusb -v`, `bDeviceProtocol 2`, "TT per port".
  2. Una disposición más ligera del Tracker: ver `docs/PLAN.md` §7.
  3. La Pi 5 (F2b).
