# 2026-10-29: línea base de la Force (sin gadget)

`tools/hosts/akai-force-probe.sh` contra `force.local` (192.168.2.31), solo lectura. Uptime: 1 minuto. La salida en bruto está en `out/` (no va al repo: lleva números de serie).

## Sistema

- Kernel `6.18.26-az01-2026-04-30-rt4`, `SMP PREEMPT_RT`, armv7l.
- Distribución `az0x 5.0.17 (scarthgap)`, de inMusic, basada en Yocto.
- **MockbaMod** activo: "MOCKBAMOD MockbaMagic COMPLETED" en el log de MPC, y `tkgl_anyctrl` sustituye un puerto rawmidi.
- Procesos relevantes:
  - `az01-unsupp-dev`: decide qué dispositivos USB se aceptan;
  - `az01-launch-MPC`;
  - `MPC` (pid 770).

## Audio interno (ADA2) con MPC en marcha

| PCM | Formato | Canales | Rate | Periodo | Buffer |
|---|---|---|---|---|---|
| pcm0p (reproducción) | S32_LE, RW_INTERLEAVED | 4 | 44100 | 128 | 384 |
| pcm0c (captura) | S32_LE, RW_INTERLEAVED | 2 | 44100 | 128 | 256 |

Log de MPC:

```
**** Audio 44100Hz; 2-in; 4-out; 128sample buffer
**** Warning: inefficient input path: hardware=2 filter=32
**** Warning: inefficient output path: hardware=4 filter=32
```

"filter=32" encaja con un motor preparado para 32 canales por sentido.

## Tarjetas ALSA

| Índice | Tarjeta | Qué es |
|---|---|---|
| 0 | `A32` | Arturia KeyStep 32, Full-Speed, en `usb-ff500000.usb-1.1.2` |
| 1 | `Force` | La superficie de control de la Force (09e8:0040), Full-Speed. MPC la usa como `hw:1` para MIDI |
| 2 | `ADA2` | El códec interno |

Los índices dependen de lo que haya enchufado; MPC abre por índice.

## Topología USB

```
EHCI ff500000.usb (bus 2, High-Speed)
└─ 2-1      Force Hub, 09e8:5040 (USB5537B), HS
   ├─ 2-1.1    USB2.0 HUB, 2148:7022, HS
   │  ├─ 2-1.1.2    Arturia KeyStep 32, FS
   │  └─ 2-1.1.4    USB2.0 HUB, 2148:7022, HS
   │     └─ 2-1.1.4.1  USB Single Serial, 1a86:55d3, FS (cdc_acm)
   ├─ 2-1.2    memoria USB "Disk 2.0", HS
   ├─ 2-1.3    lector SD interno "Akai MPC Card Reader", HS
   ├─ 2-1.4    puente SATA JMicron (SSD interno), HS
   └─ 2-1.5    superficie de control "Akai Pro Force", FS
dwc2 ff580000.usb (bus 1): sin dispositivos (el puerto del ordenador)
```

Consecuencias para rpi-audio:
- La Pi (gadget High-Speed) entrará por el hub de la Force y compartirá los 480 Mbit/s del EHCI con el SSD, el lector SD y la superficie de control. Su isócrono tiene reserva periódica.
- Conectarla a un USB-A de la Force, **no** detrás de un hub externo como el 2-1.1.4.
- Con el gadget conectado se repite el probe: la tarjeta nueva, su `stream0`, y los `hw_params` y el log "N-in; N-out" de MPC.
