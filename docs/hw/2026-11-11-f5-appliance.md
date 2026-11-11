# 2026-11-11: F5, el aparato: watchdogs y root de solo lectura (solo en el repo)

Trabajo en el repo, sin desplegar nada. De la Pi 5 solo se leyeron datos por SSH, sin `sudo` y sin escribir, mientras el usuario hacía pruebas de audio en ella. Las dos partes son opcionales: sin `--read-only` ni `--hw-watchdog`, la Pi queda como antes, salvo `rpi-audiod`, que pasa a avisar a systemd (`Type=notify` con watchdog).

## Lo que hay en la Pi

- [Pi] Pi 5, `MemTotal` 1 014 352 kB, kernel `6.18.50+rpt-rpi-2712`.
- [Pi] Arranque: `auto_initramfs=1` en `config.txt`; `initramfs_2712` e `initramfs8` en `/boot/firmware`, generados desde `/boot/initrd.img-6.18.50+rpt-rpi-2712` por los hooks `z50-raspi-firmware`. Tiene `initramfs-tools` 0.148.4+rpt2. **`overlayroot` no está instalado.**
- [Pi] `/proc/cmdline` sin `overlayroot`. En `fstab`, `/boot/firmware` es vfat con `defaults`, y el root ext4 con `defaults,noatime`. Los dos montados en escritura.
- [Pi] Estado vivo:
  - `/var/lib/rpi-audio`: `slots.json`, `presets.json`, `hosts.json`, copias `slots.json.bak-*` y `slots.lock`;
  - `/var/lib/rpi-audio-ui`: `settings.json`.
- [Pi] **El watchdog hardware ya está armado.** Lo arma `raspberrypi-sys-mods`, en `/usr/lib/systemd/system.conf.d/40-rpi-enable-watchdog.conf`, con `RuntimeWatchdogSec=1m` y `RebootWatchdogSec=2m`. `watchdog0` es el BCM2835, timeout 60, activo.
  - Si systemd se cuelga, la Pi ya hoy se resetea sin pasar por `rpi-audio-gadget down`.
- [Pi] El `raspi-config` de la Pi, leído:
  - `enable_overlayfs` pide más de 256 MB de RAM, instala `overlayroot` con apt y antepone `overlayroot=tmpfs ` a `cmdline.txt`;
  - `enable_bootro` añade `,ro` tras `defaults` en la línea de `/boot/firmware` de `fstab`, y se niega con el overlay activo;
  - `disable_*` deshace las dos ediciones con `sed`.

## Watchdog del servicio [repo]

- `bridge/rpi-audiod/sdnotify.py`, sin dependencias:
  - escribe el datagrama en `$NOTIFY_SOCKET`; una `@` inicial es el espacio abstracto;
  - comprueba `WATCHDOG_PID` y quita las tres variables del entorno, para que jackd y los puentes no las hereden;
  - si el socket falla, lo anota una vez y sigue.
- `rpi-audiod` manda `READY=1` en cuanto carga la configuración, y `WATCHDOG=1` en cada pasada del bucle, como mucho una vez por segundo.
  - En `rpi-audiod` son seis líneas: el import, un `heartbeat` que por defecto no hace nada y su llamada en el bucle, y en `main()` crear el `Notifier`, enganchar el `heartbeat` y mandar `READY=1`.
- **`WatchdogSec=30s`.** Una pasada normal tarda 0,1 s (`TICK`). Las más lentas tardan segundos:
  - cada orden externa tiene un timeout de 2 s;
  - un cambio de modo para cada hijo, y le da 1 s antes de matarlo;
  - las respuestas MIDI van en su propio hilo (`sender`) [código].

  30 s dejan sitio para unos 10 s de eso, tres veces. Si el bucle se para unos 29 s, el watchdog salta. Entonces systemd manda SIGABRT, `KillMode=mixed` mata el resto del grupo y `Restart=always` lo levanta. Test: 60 latidos en 6 s, incluido un reinicio de jackd atascado.
- **El gadget no tiene watchdog ni `Restart=`** (test que lo comprueba).
- **La UI no tiene watchdog, a propósito:**
  - haría falta copiar `sdnotify.py` a su carpeta, o importarlo de la de `rpi-audiod`, y cambiar `deploy --ui-only` y sus tests;
  - la UI ya saca la pantalla y las órdenes a hilos, y `Restart=always` cubre los cuelgues que matan el proceso;
  - una UI congelada no corta el audio.

## Watchdog hardware [repo]

- `install.sh --hw-watchdog S|off` (5–300 s) escribe `/etc/systemd/system.conf.d/60-rpi-audio-watchdog.conf`.
  - Los drop-ins de `system.conf.d` se ordenan por nombre entre directorios, así que el 60 gana al 40 del sistema [ext, systemd].
  - Vale desde el siguiente arranque.
  - Se deshace con `--uninstall` o borrando el fichero.
- Sin la opción, no se toca nada: se queda el minuto del sistema.
- **Riesgo, en la ayuda y en el manual:** un reset del hardware se salta `rpi-audio-gadget down`. Ese `down` primero quita el pull-up y luego desenlaza. Sin él, el host ve desaparecer el dispositivo a media transmisión, como en el incidente del 2026-10-30, que tiró el hub interno de la Force (`2026-10-30-boot-soak.md`).

## Root de solo lectura: diseño [repo]

**Alternativas:**

1. **`overlayroot`, el de `raspi-config` (elegida).** Protege todo el root, sin tener que saber qué escribe cada servicio del sistema. Lo mantiene la distribución, y el usuario puede quitarlo con el `raspi-config` que ya conoce.
   - `install.sh` hace exactamente las mismas ediciones que `raspi-config`, así que `raspi-config nonint disable_overlayfs` y `disable_bootro` las deshacen. Hay test que aplica esos `sed` y recupera los originales.
2. **`fstab` con el root `ro`, y tmpfs para las rutas que escriben.** Es la idea de raspimidihub [ext]. Hay que acertar con cada ruta que escribe: `/var/lib` de varios servicios, NetworkManager, el reloj, la semilla aleatoria… En una Pi de uso general con Raspberry Pi OS, eso se rompe con las actualizaciones.
3. **Una partición de estado en ext4.** Exige reparticionar, que es destructivo, y CLAUDE.md lo descarta sin preguntar.

Sin reparticionar, la única partición escribible que queda es `/boot/firmware` (FAT). El estado va en `/boot/firmware/rpi-audio/`.

**Qué se guarda:**
- `rpi-audio/{slots,presets,hosts}.json` y `rpi-audio-ui/settings.json`. Nada más: al restaurar se ignora cualquier otro nombre de la ranura.
- **`/etc/rpi-audio` no se guarda; se queda en la imagen.** Es lo que escribe `install.sh`, y cambiarlo exige apagar el overlay (lo dice `deploy.sh`). Si se restaurara, una copia vieja pisaría la de una instalación nueva.
  - Es un cambio respecto a F5 en `PLAN.md`, que ponía también la configuración en `/boot/firmware`.

**Formato y escritura** (`bridge/rpi-audiod/persist.py`, Python puro, con tests):
- Cada ranura es una cabecera (`RPAS`, versión, número de guardado, longitud), un CRC32, y un JSON gzip con los ficheros en base64.
- Hay dos ranuras, `slot0/state.bin` y `slot1/state.bin`, cada una en su carpeta.
- **Nunca se escribe la ranura válida más nueva.** Se escribe la otra, con el número siguiente. Al leer gana el número más alto con CRC bueno, así que una escritura cortada deja el estado anterior. El test corta en cada byte.
- **Se escribe en el sitio:** sin truncar, y rellenando hasta bloques de 4 KiB. Una vez creado el fichero, guardar no toca la FAT, solo los datos y la entrada de su propia carpeta (la fecha) [est]. Con una carpeta por ranura, una entrada de directorio a medio escribir no alcanza a la otra ranura.
- Si no ha cambiado nada, no escribe ni remonta.

**Remontar y cuándo se guarda** (`rpi-audio-persist`):
- Cada guardado remonta `/boot/firmware` en escritura, con un `flock` en `/run`, y luego hace `sync` y vuelve a `ro`.
- Lee los ficheros vivos con `O_NOFOLLOW`: solo ficheros normales de 1 MiB como mucho. Respeta el `flock` de `slots.lock` de `rpi-audiod`.
- `rpi-audio-persist-restore.service`:
  - arranca en `sysinit`, antes del gadget, `rpi-audiod` y la UI;
  - repone los ficheros con su dueño y sus permisos, por renombrado atómico;
  - si no hay ninguna ranura válida, deja los de la imagen;
  - su `ExecStop` guarda al apagar.
- `rpi-audio-persist.path` vigila las dos carpetas (`PathChanged=`) y lanza el guardado. El guardado espera 2 s sin cambios y repite hasta que el estado no cambia.
- **El diario va a RAM** (`Storage=volatile`, 32 MB): `journalctl -b -1` no muestra nada.

**raspimidihub:** se sigue el patrón (remontar con `flock` y `sync`, dos ranuras alternas con CRC), **sin copiar su código**. Por eso no hay entrada en `THIRD_PARTY.md`.

## `install.sh` y `deploy.sh` [repo]

**`install.sh --read-only`:**
- Pasos, en orden:
  1. Guarda primero el estado actual en el almacén; si falla, el root se queda escribible.
  2. Comprueba que el initramfs lleva `overlayroot` (`lsinitramfs`) y, si no, ejecuta `update-initramfs`.
  3. Edita `cmdline.txt` y `fstab` con copia de seguridad.
  4. Habilita la restauración y el `.path`.
- Imprime cómo deshacerlo.
- Con el overlay ya activo, se niega salvo con `--volatile`.
- Si `/boot/firmware` está en `ro`, lo remonta en escritura para sus ediciones y lo devuelve a `ro` al salir.
- Respeta `RPI_AUDIO_ROOT` (staging).

**`--uninstall`** quita las unidades y el drop-in del watchdog, pero deja el root de solo lectura y explica cómo quitarlo. `--purge` borra el almacén.

**`deploy.sh`:**
- Pasa las tres opciones a `install.sh`.
- Si la Pi ya arranca con overlay, para y da los pasos:
  1. `disable_overlayfs` y reiniciar;
  2. `deploy --read-only`;
  3. reiniciar.
- Con `--volatile`, despliega igualmente y avisa de que dura hasta el siguiente arranque.

## Pruebas [repo]

- `python3 -m pytest -q tests`, en el portátil:
  - antes de los cambios: 1 fallo, 471 correctas, 23 omitidas, 8 errores;
  - después: 1 fallo, 521 correctas, 23 omitidas, 8 errores.

  El fallo y los errores son los mismos de antes: el `tomllib` de este Python 3.10 no sirve (`test_supervisor` del renombrado, `test_uicommands`).
- Nuevos tests:
  - `test_sdnotify.py` (9) y `test_persist.py` (19);
  - `test_deploy.py` (7), con `ssh` y `rsync` falsos;
  - la sección F5 de `test_install.py`;
  - un test de latidos en `test_supervisor.py`.
- `flake8` limpio en los ficheros tocados, y `bash -n` en `install.sh` y `deploy.sh`.

## Lo que no se ha hecho, y por qué

- **Nada en la Pi:** el usuario estaba midiendo audio en ella.
- **Watchdog de la UI:** ver arriba.
- **Del resto de F5,** nada de esto entra en esta tarea:
  - el arranque en 15 s o menos;
  - la matriz web;
  - el `apt-mark hold` del kernel.
- **Borrados:** un fichero que se borre no se borra de la ranura nueva. Al arrancar, la imagen trae su versión y la restauración no la quita.

## Preguntas abiertas [?]

- **Con el overlay activo:**
  - qué hacen `fake-hwclock` y el swap (`rpi-swap`);
  - cuánta RAM come la capa tmpfs en 1 GB tras una sesión larga.
- `update-initramfs` en la Pi 5: si el hook copia a `/boot/firmware` una imagen que ya lleve `overlayroot` (`install.sh` lo comprueba con `lsinitramfs` sobre `/boot/initrd.img-*`, no sobre la copia del firmware).
- **Corte con `/boot/firmware` remontado en escritura:** el bit sucio de FAT y el `fsck` del arranque (passno 2). Habrá que ver si el `fsck` toca algo.
- Cuánto alarga el arranque el initramfs con overlay más la restauración.
- **Desgaste de la SD:**
  - `rpi-audiod` solo escribe `slots.json` cuando cambia [código];
  - mover un nivel con el encoder puede dar muchos guardados seguidos, aunque la espera de 2 s los agrupa [est].
- Si `PathChanged=` en una carpeta salta con el renombrado atómico (`moved_to`) que usan `rpi-audiod` y la UI.

## Lista para hardware

Sin el host transmitiendo, o aceptando el riesgo del hub (incidente del 2026-10-30):

1. **Instalar:** `tools/deploy.sh --read-only --enable` con el overlay apagado. Mirar:
   - que instala `overlayroot`;
   - que el initramfs lo lleva;
   - las copias `cmdline.txt.rpi-audio-*` y `fstab.rpi-audio-*`.
2. **Reiniciar y comprobar:**
   - `findmnt / /boot/firmware`: el root es `overlay` y `/boot/firmware` está en `ro`;
   - `rpi-audio-persist status`;
   - `systemctl show rpi-audiod -p WatchdogUSec,Type`.
3. **Persistencia:** cambiar un ajuste, por ejemplo la latencia USB baja en Outputs.
   - Ver el guardado en `journalctl -u rpi-audio-persist`.
   - Reiniciar y comprobar que sigue, y que el gadget sale con ese ajuste.
4. **Watchdog del servicio:** `kill -STOP` al proceso principal de `rpi-audiod`. A los 30 s systemd lo aborta y lo reinicia.
   - El gadget no se reenlaza.
   - Para ver los estados y los mensajes, `journalctl -u rpi-audiod`.
5. **20 cortes de corriente** en momentos al azar, varios durante un guardado (cambiar ajustes justo antes de cortar). Tras cada arranque, comprobar:
   - que el host enumera el gadget;
   - `rpi-audio-persist status`, con las dos ranuras;
   - `rpi-audiod status`;
   - `sudo fsck.vfat -n` de la partición de arranque;
   - si hubo vuelta a la ranura anterior, en `journalctl -u rpi-audio-persist-restore`.

   Aceptación: los 20 sin corrupción, y el host la encuentra en todos.
6. **Salir:**
   1. `raspi-config nonint disable_overlayfs` y reiniciar;
   2. `disable_bootro`;
   3. deshabilitar las unidades;
   4. `install.sh` sin `--read-only`.

   Comprobar que todo vuelve a como estaba.
