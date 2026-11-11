# Salidas locales, USB y de red

Implementación · 3 de noviembre de 2026. El [manual ilustrado en inglés](MANUAL.md) explica el uso paso a paso; [NETWORK_RESEARCH.md](NETWORK_RESEARCH.md) conserva la investigación de proyectos.

## Funcionamiento implementado

El modo `hub` usa el pHAT como reloj local a 48 kHz. El grafo JACK continúa aunque se desconecte el host USB. Los modos anteriores `host` y `standalone` siguen disponibles. La selección se guarda con `rpi-audiod engine hub|host|standalone` o desde OLED → Outputs → Audio mode; cambiarla pide confirmar el corte de audio.

| Destino | Adaptador | Estado |
|---|---|---|
| pHAT DAC | Puertos JACK `system:playback_N` | Salida local del motor Hub/Standalone |
| Host USB | `zita-j2a`; retorno independiente `zita-a2j`. Opcional: `rpi-audio-hostbridge` (`[usb] host_bridge = "native"`) | Puentes por sentido y frecuencia del gadget; conservan su número de canales |
| Network RTP | Adaptador nativo JACK → RTP L16 estéreo | Envío UDP, RTCP y descripción SDP; desactivado inicialmente |
| Link Audio | Adaptador nativo con SDK oficial Ableton Link 4.1.1 fijado por commit | Envío estéreo con descubrimiento y suscripción; desactivado inicialmente |

El host USB se representa como origen/destino estable `usb-host`. Los otros destinos son `local-dac`, `network-rtp` y `network-link`. Pueden combinarse mediante rutas. Apagar una salida corta sus rutas; el puente de envío USB mantiene silencio para no dejar al host sin alimentación de audio. Apagar una salida de red detiene solo su proceso. No se cambia el reloj automáticamente al conectar equipos.

En Hub, la reproducción de cada dispositivo USB físico se abre solo cuando alguna ruta guardada lo tiene como destino. Al quitar su última ruta entrante se cierra ese puente y se libera su presupuesto USB, conservando su captura y el reloj local. Las asignaciones USB guardadas sin ruta de retorno no requieren una reproducción activa para que un perfil esté Ready. Los modos host y standalone conservan su comportamiento anterior.

La primera entrada en Hub convierte una sola vez los mapas USB guardados en rutas explícitas. Se pueden borrar después sin que reaparezcan. Los dispositivos nuevos se enrutan desde Send audio. Los mapas y el comportamiento automático del modo host original se conservan.

Las escenas nuevas guardan mapas de canales, nombres, rutas, niveles, mute y activación de salidas. Las escenas antiguas sin nombres conservan los actuales. Los perfiles de host pueden guardar solo reservas, una copia completa independiente o un vínculo a una escena; los perfiles de usuario se conservan en hosts.json y los usuarios del grupo audio pueden editarlos sin root. El modo de motor y los parámetros de transporte no cambian al cargar una escena.

## Puente nativo del gadget (opcional)

Medido con un portátil como host, sin probar con la Force. Con el margen por defecto, la parte de la Pi en el viaje de ida y vuelta es unos 5–6 ms menor que con zita, y el puente usa unas 4 veces menos CPU. Detalle en [hw/2026-11-11-native-bridge.md](hw/2026-11-11-native-bridge.md).

`[usb] host_bridge = "native"` sustituye en Hub los dos zita del gadget por `rpi-audio-hostbridge` (`bridge/audio/hostbridge.c`, núcleo sin hardware en `hostbridge_core.h`), un proceso por sentido con los mismos clientes y puertos (`usb_host_in:capture_N`, `usb_host_out:playback_N`). Por defecto sigue `zita`; si el programa no está compilado, también.

- **Sin hilo ni cola propios.** Todo ocurre en la callback de tiempo real de JACK: lee o escribe el buffer ALSA del gadget en su sitio (mmap, sin bloquear) y remuestrea entre el reloj del host y el local. El único buffer es el de ALSA, mantenido en `host_margin_ms` (1,5 ms por defecto) ajustando la relación del remuestreador con un lazo PI de 0,1 Hz.
- **Retardo añadido por sentido:** el margen más el filtro (`host_quality` tramas; 32 = 0,7 ms y ~86 dB), además del periodo de JACK. zita añade ~5 ms por sentido (periodo ALSA + periodo JACK + filtro, y 4 periodos en reproducción).
- **Los streams no se paran por xrun** (umbral de parada en el límite, y silencio automático en reproducción): si un ciclo llega tarde, el host recibe silencio al ritmo correcto y el puente vuelve de un salto a su margen. Cada salto cuenta como «USB resyncs» en la sesión.
- **Para ajustarlo:** `rpi-audiod status` muestra por sentido el buffer mínimo/medio/máximo en tramas (referido al inicio del ciclo), la corrección en ppm, los resyncs y lo tarde que corre el puente dentro del ciclo. Se baja `host_margin_ms` mientras el mínimo quede lejos de 0.
- `host_period` no se aplica al puente nativo. El buffer del gadget tiene que dar para dos periodos de JACK más márgenes; si no, el puente lo dice y no arranca.

## Transporte y SDP

RTP usa RFC 3550 y PCM L16, dos canales, orden de red, paquetes nominales de 1 ms a 48 kHz. Las marcas de tiempo conservan los saltos de muestras causados por xruns. RTCP publica sender reports y CNAME. El hilo de audio escribe en una cola acotada; la red y los archivos se procesan fuera de la callback.

Configuración en `/etc/rpi-audio/rpi-audio.toml` o sus drop-ins:

```toml
[network]
address = "239.69.1.1"  # grupo multicast o IPv4 del receptor
port = 5004             # RTCP: 5005; debe ser par
ttl = 1
http_port = 8080        # 0 desactiva la descarga
```

El archivo activo está en `/run/rpi-audio/network-rtp.sdp` y se descarga desde `http://IP-DE-LA-PI:8080/network-rtp.sdp`. La raíz ofrece un enlace de descarga. Solo se sirve ese archivo; no hay listado de directorios ni acceso a configuración. El endpoint devuelve 503 si RTP está apagado o caído. El error del servidor HTTP se publica por separado y no detiene el audio.

`send` en RTP significa paquetes enviados, sin confirmación de un receptor. En Link Audio significa buffers entregados a una suscripción; el número de peers por sí solo no prueba recepción de audio. El canal anunciado es `Network mix`, peer `rpi-audio`.

## Menús

```text
Overview → menú
  Send audio       origen → marcar destinos; More output pairs... para pares concretos
  Outputs          DAC / USB host / Network RTP / Link Audio → Enabled / Level / Details
                   Audio mode → Hub / USB host clock / Standalone DAC
                   Host → perfiles de reservas USB / guardar reservas actuales
  Levels & mute    dispositivo físico → mute / nivel disponible
  MIDI             emisor → receptores
  Scenes           slot → Load / Save here... → confirmar
  Connections      USB, wifi y dispositivos físicos con capacidades y mapas
  Settings         pantalla y encoder
```

PUSH y CONFIRM tienen la misma acción. BACK vuelve o cancela. La pantalla no espera consultas de red ni comandos de audio. Los medidores siguen siendo taps pasivos de JACK.

## Compilación y validación

`sudo ./install.sh --network` instala las dependencias y compila el adaptador con el SDK fijado a `5ba907ae027a8c2ec8824463e37296dcefc5e9be`. `tools/build-network.sh --rtp-only` permite compilar solo RTP. El binario informa sus capacidades con `--capabilities`; los avisos de licencia se instalan junto a él. No se añaden módulos de kernel.

Pruebas automatizadas cubren navegación, migración, persistencia, frecuencias USB independientes, continuidad del reloj al retirar el host y aislamiento de fallos de red. Las pruebas nativas usan JACK dummy sin hardware: PCM estéreo conocido, secuencias/timestamps RTP, RTCP, SDP, cliente Link SDK receptor y ausencia de arranque involuntario de JACK. La sesión en la Pi también verifica el motor pHAT y la descarga HTTP.

## Límites y siguientes ensayos

Esta versión **solo envía audio por red**. No implementa AES67 completo, sincronización PTP, Dante, recepción de red, SonoBus/AOO ni tarjetas virtuales para Windows/macOS. RTP/PCM con SDP es un transporte estándar, no una certificación AES67. [RTP](https://www.rfc-editor.org/info/rfc3550/), [SDP](https://www.rfc-editor.org/rfc/rfc8866.html), [AES67](https://www.aes.org/publications/standards/preview.cfm?ID=96).

Link Audio se ha contrastado con otro proceso del SDK oficial. Quedan ensayos con Ableton Live físico, hosts USB en modo Hub y medición de latencia/pérdidas entre equipos y sistemas operativos. Las pruebas previas con Linux/Force corresponden al modo host original. Para uso estable, Ethernet es la referencia; wifi se evalúa por separado. [Documentación Link Audio](https://ableton.github.io/link/), [guía de Ableton](https://help.ableton.com/hc/en-us/articles/25425913328924-Link-Audio-FAQ).

## Disponibilidad, niveles e historial

El estado de cada perfil compara su configuración guardada con dispositivos, canales y puertos MIDI presentes. Ready indica requisitos disponibles; Partial explica dispositivos ausentes o recursos/stream pendientes; Error identifica escena inexistente o datos inválidos. No es una prueba de sonido audible ni de recepción RTP.

Cada salida principal tiene un proceso JACK nativo de ganancia independiente: DAC, envío USB, RTP y Link Audio. El nivel 0–100 se guarda en output_levels, se aplica después de sumar sus fuentes y cambia con rampa. La configuración se envía sin reiniciar el proceso ni JACK. Si falla una etapa, no se crea un bypass a volumen completo. Los perfiles/escenas antiguos que carecen de ese campo conservan los niveles actuales.

Un observador JACK sin puertos funciona mientras el motor esté activo y registra xruns fuera de la interfaz. El daemon registra desconexiones, fallos y cambios de rate/búfer. session.json vive en RAM, se conserva entre reinicios del servicio y se reinicia al cambiar el boot_id. History contiene como máximo 64 eventos agrupados, con contadores que conservan su total.
