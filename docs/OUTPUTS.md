# Salidas locales, USB y de red

Implementación · 3 de noviembre de 2026. El [manual ilustrado en inglés](MANUAL.md) explica el uso paso a paso; [NETWORK_RESEARCH.md](NETWORK_RESEARCH.md) conserva la investigación de proyectos.

## Funcionamiento implementado

El modo `hub` usa el pHAT como reloj local a 48 kHz. El grafo JACK continúa aunque se desconecte el host USB. Los modos anteriores `host` y `standalone` siguen disponibles. La selección se guarda con `rpi-audiod engine hub|host|standalone` o desde OLED → Outputs → Audio mode; cambiarla pide confirmar el corte de audio.

| Destino | Adaptador | Estado |
|---|---|---|
| pHAT DAC | Puertos JACK `system:playback_N` | Salida local del motor Hub/Standalone |
| Host USB | `zita-j2a`; retorno independiente `zita-a2j` | Puentes por sentido y frecuencia del gadget; conservan su número de canales |
| Network RTP | Adaptador nativo JACK → RTP L16 estéreo | Envío UDP, RTCP y descripción SDP; desactivado inicialmente |
| Link Audio | Adaptador nativo con SDK oficial Ableton Link 4.1.1 fijado por commit | Envío estéreo con descubrimiento y suscripción; desactivado inicialmente |

El host USB se representa como origen/destino estable `usb-host`. Los otros destinos son `local-dac`, `network-rtp` y `network-link`. Pueden combinarse mediante rutas. Apagar una salida corta sus rutas; el puente de envío USB mantiene silencio para no dejar al host sin alimentación de audio. Apagar una salida de red detiene solo su proceso. No se cambia el reloj automáticamente al conectar equipos.

La primera entrada en Hub convierte una sola vez los mapas USB guardados en rutas explícitas. Se pueden borrar después sin que reaparezcan. Los dispositivos nuevos se enrutan desde Send audio. Los mapas y el comportamiento automático del modo host original se conservan.

Las escenas guardan rutas, niveles, mute y activación de salidas. El modo de motor y los parámetros de transporte no cambian al cargar una escena.

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
  Outputs          DAC / USB host / Network RTP / Link Audio → Enabled / Details
                   Audio mode → Hub / USB host clock / Standalone DAC
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
