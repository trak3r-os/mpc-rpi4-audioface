#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install rpi-audio on this Raspberry Pi, from a clone of the repository.
#
#   git clone https://github.com/trak3r-os/rpi5-audioface.git
#   cd rpi5-audioface && sudo ./install.sh
#
#   sudo ./install.sh [--host NAME] [--no-enable] [--force-config] [--no-boot-config] [--tune-boot] [--hat] [--network]
#                     [--read-only] [--hw-watchdog SECONDS|off] [--volatile] [-y]
#   sudo ./install.sh --uninstall [--purge]
#
#   --host NAME        make host profile NAME (config/hosts.d/) the default one, or install tools/hosts/NAME.toml
#                      as /etc/rpi-audio/rpi-audio.d/NAME.toml (e.g. standalone). All profiles are always installed.
#                      (rpi-audiod settings for that host, e.g. akai-force)
#   --no-enable        leave the boot enable state of the units as it is (by default
#                      rpi-audio-gadget, rpi-audiod and rpi-audio-cpu are enabled,
#                      rpi-audio-keepalive disabled)
#   --force-config     overwrite /etc/rpi-audio/gadget.env and rpi-audio.toml even if they differ
#                      (by default an existing, different file is kept and the repo's version is
#                      written next to it as *.new)
#   --no-boot-config   do not look at the boot config (dtoverlay=dwc2,dr_mode=peripheral)
#   --tune-boot        also tune the boot for audio: threadirqs in cmdline.txt and
#                      dtparam=audio=off (the Pi's own analogue audio) in config.txt, with backups.
#                      Never done without this option, -y included; takes effect after a reboot
#   --hat              also set up a display and a DAC on the 40-pin header: dtparam=i2c_arm=on (the I2C bus
#                      of an OLED) and dtoverlay=hifiberry-dac (a PCM5102A board such as the Pimoroni pHAT
#                      DAC), with a backup, and enable rpi-audio-ui.service (the OLED and its encoder; its
#                      files are always installed, it only runs with this option). Never done without it;
#                      the boot changes take effect after a reboot
#   --network          build RTP/PCM and Ableton Link Audio output adapters (downloads a pinned Link SDK)
#   --read-only        make the Pi an appliance that survives power cuts: the root filesystem becomes a RAM overlay
#                      (the overlayroot package, as raspi-config's "Overlay File System": overlayroot=tmpfs in
#                      cmdline.txt) and /boot/firmware is mounted read-only (",ro" in /etc/fstab, as raspi-config's
#                      boot partition write-protection), both with backups. What rpi-audio changes at runtime
#                      (channel slots, presets, saved host profiles, the display's settings) is saved on every change
#                      to /boot/firmware/rpi-audio/ (two alternating slots with a CRC) and put back at boot, by
#                      rpi-audio-persist-restore.service and rpi-audio-persist.path, which this enables. The journal
#                      is kept in RAM. Never done without this option; takes effect after a reboot. To change the
#                      installation later, turn the overlay off first (the summary prints how, and how to undo it all)
#   --hw-watchdog S    have systemd arm the SoC's hardware watchdog with a timeout of S seconds (5-300), or "off"
#                      to disarm it (RuntimeWatchdogSec in /etc/systemd/system.conf.d/60-rpi-audio-watchdog.conf).
#                      Raspberry Pi OS already arms it at 1 min (raspberrypi-sys-mods). RISK: a watchdog reset
#                      skips the gadget's orderly shutdown (rpi-audio-gadget down), and a Pi that vanished from the
#                      bus while a host streamed once took down that host's whole internal USB hub
#                      (docs/hw/2026-10-30-boot-soak.md). Never changed without this option; takes effect after a reboot
#   --volatile         install even though the root is a RAM overlay (--read-only active): everything but the boot
#                      config edits is lost at the next reboot. For a quick test only
#   -y                 answer yes to the question about the boot config (the gadget overlay)
#   --uninstall        remove what this script installed; /etc/rpi-audio and /var/lib/rpi-audio stay
#   --purge            with --uninstall: remove those two as well, and the saved state in /boot/firmware/rpi-audio
#
# Idempotent: run it again after every `git pull`. A running rpi-audiod is restarted so it
# runs the new code (the host hears a gap); the gadget only when its settings changed.
# The boot config is touched only to add the USB gadget overlay, after asking, and with
# --tune-boot, always with a backup; the Pi is never rebooted by this script.
# rpi-audio-cpu.service keeps the CPU governor at "performance" (disable it to go back to "ondemand").
# PipeWire must not be installed alongside: it would grab the gadget and steer its pitch.
# On a Pi 4 (VIA VL805 USB host) it also installs dkms and the kernel headers, and builds and loads
# fs_isoc_pad (tools/kernel/fs-isoc-pad/), so full-speed multichannel capture does not drop packets.
#
# For tests only: RPI_AUDIO_ROOT=/some/dir puts every path under that prefix and skips
# everything that is not a file operation (root and Pi checks, apt, useradd, systemctl, ...).

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
R="${RPI_AUDIO_ROOT:-}"
staging=0
[[ -n $R ]] && staging=1
tag="${RPI_AUDIO_TAG:-install}"

LIB=$R/usr/local/lib/rpi-audio
BIN=$R/usr/local/bin
ETC=$R/etc/rpi-audio
UNITDIR=$R/etc/systemd/system
MODULES=$R/etc/modules-load.d/rpi-audio.conf
JOURNALD=$R/etc/systemd/journald.conf.d/rpi-audio.conf
WATCHDOG_CONF=$R/etc/systemd/system.conf.d/60-rpi-audio-watchdog.conf
FSTAB=$R/etc/fstab
CMDLINE=$R/boot/firmware/cmdline.txt
PERSIST_STORE=$R/boot/firmware/rpi-audio
STATE=$R/var/lib/rpi-audio
POWER_POLICY=$R/etc/sudoers.d/rpi-audio-power
UDCDIR=$R/sys/class/udc
OVERLAY='dtoverlay=dwc2,dr_mode=peripheral'
units="rpi-audio-gadget rpi-audiod rpi-audio-keepalive rpi-audio-cpu rpi-audio-ui"
# --read-only's units: always installed, only enabled with --read-only.
persist_units="rpi-audio-persist-restore.service rpi-audio-persist.path rpi-audio-persist.service"
packages="jackd2 jack-example-tools zita-ajbridge gcc libjack-jackd2-dev libasound2-dev sudo"

say() { echo "$tag: $*"; }
warn() { echo "$tag: $*" >&2; }
die() { warn "$*"; exit 1; }
usage() {
  cat >&2 <<'EOF'
usage: sudo ./install.sh [--host NAME] [--no-enable] [--force-config] [--no-boot-config] [--tune-boot] [--hat] [--network]
                         [--read-only] [--hw-watchdog SECONDS|off] [--volatile] [-y]
       sudo ./install.sh --uninstall [--purge]
EOF
  exit 2
}

# Commands that act on the running system: skipped under RPI_AUDIO_ROOT.
sysrun() { if ((staging)); then say "(test root) skipped: $*"; else "$@"; fi; }
# Queries about units: nothing to ask under RPI_AUDIO_ROOT.
unit_active() { ((! staging)) && systemctl is-active --quiet "$1.service"; }

enable=1 force=0 bootcfg=1 tuneboot=0 hat=0 network=0 yes=0 uninstall=0 purge=0 hostconf=
ro_root=0 hwwd= volatile=0
while (($#)); do
  case $1 in
    --host) hostconf=${2:?--host needs a name}; shift ;;
    --no-enable) enable=0 ;;
    --force-config) force=1 ;;
    --no-boot-config) bootcfg=0 ;;
    --tune-boot) tuneboot=1 ;;
    --hat) hat=1 ;;
    --network) network=1 ;;
    --read-only) ro_root=1 ;;
    --hw-watchdog) hwwd=${2:?--hw-watchdog needs a number of seconds or off}; shift ;;
    --volatile) volatile=1 ;;
    -y|--yes) yes=1 ;;
    --uninstall) uninstall=1 ;;
    --purge) purge=1 ;;
    -h|--help) usage ;;
    *) warn "unknown option: $1"; usage ;;
  esac
  shift
done
if ((purge && !uninstall)); then warn "--purge only makes sense with --uninstall"; usage; fi
if ((uninstall)) && [[ -n $hostconf ]]; then warn "--host does not go with --uninstall"; usage; fi
if ((tuneboot && !bootcfg)); then warn "--tune-boot does not go with --no-boot-config"; usage; fi
if ((hat && !bootcfg)); then warn "--hat does not go with --no-boot-config"; usage; fi
if ((ro_root && !bootcfg)); then warn "--read-only does not go with --no-boot-config"; usage; fi
if ((uninstall && (ro_root || volatile))) || { ((uninstall)) && [[ -n $hwwd ]]; }; then
  warn "--read-only, --hw-watchdog and --volatile do not go with --uninstall"; usage
fi
if [[ -n $hwwd && $hwwd != off ]] && { [[ ! $hwwd =~ ^[0-9]{1,3}$ ]] || ((10#$hwwd < 5 || 10#$hwwd > 300)); }; then
  warn "--hw-watchdog takes a number of seconds from 5 to 300, or off"; usage
fi
if ((hat)); then packages="$packages python3-smbus2 python3-libgpiod"; fi
if ((network)); then packages="$packages g++ git libjack-jackd2-dev"; fi
if ((ro_root)); then packages="$packages overlayroot"; fi
if [[ -n $hostconf ]]; then
  [[ $hostconf =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid host name: $hostconf"
  [[ -f $here/tools/hosts/$hostconf.toml || -f $here/config/hosts.d/$hostconf.toml ]] \
    || die "no tools/hosts/$hostconf.toml or config/hosts.d/$hostconf.toml in this clone"
fi

# --- Where we are -----------------------------------------------------------

if ((! staging)); then
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "run as root: sudo ./install.sh"
  model=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)
  [[ $model == *"Raspberry Pi"* ]] || die "this is not a Raspberry Pi (model: ${model:-unknown}); rpi-audio needs a Pi's USB gadget port"
  if dpkg -s pipewire >/dev/null 2>&1; then
    die "pipewire is installed; remove it first (it would grab the gadget and steer its pitch)"
  fi
  export LC_ALL=C.UTF-8
fi

# The root as a RAM overlay (--read-only, or raspi-config's Overlay File System): what is installed now would be
# gone at the next boot. A test root has its own proc/cmdline when a test wants one.
overlayroot_now() { grep -qw 'overlayroot=tmpfs' "$R/proc/cmdline" 2>/dev/null; }
overlayroot_conf() { grep -qw 'overlayroot=tmpfs' "$CMDLINE" 2>/dev/null; }
bootro_conf() { grep -Eq '^[^#]*/boot/firmware.*defaults.*,ro([[:space:],]|$)' "$FSTAB" 2>/dev/null; }
if overlayroot_now && ((! volatile)); then
  warn "the root filesystem is a RAM overlay (overlayroot=tmpfs, install.sh --read-only): what this script"
  warn "installs would be gone at the next boot. Turn the overlay off, reboot, then run this again with --read-only:"
  warn "  sudo raspi-config nonint disable_overlayfs && sudo reboot"
  die "(--volatile installs anyway, for a test that the next reboot undoes)"
fi
if ((ro_root)); then
  [[ -f $CMDLINE ]] || die "--read-only needs $CMDLINE (Raspberry Pi OS Bookworm or later)"
  [[ -f $FSTAB ]] || die "--read-only needs $FSTAB"
  if ((! staging)) && (($(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo) <= 262144)); then
    die "--read-only keeps every write to the root in RAM; this Pi has 256 MB or less"
  fi
fi

# A read-only boot partition (--read-only) is made writable for this run's edits, and read-only again at the end.
boot_rw=
boot_writable() {
  local mnt
  if ((staging)) || [[ -n $boot_rw ]]; then return 0; fi
  mnt=$(findmnt -n -o TARGET --target "$1" 2>/dev/null) || return 0
  [[ ,$(findmnt -n -o OPTIONS --target "$1"), == *,ro,* ]] || return 0
  mount -o remount,rw "$mnt" || die "cannot make $mnt writable for $1"
  boot_rw=$mnt
  trap 'sync; mount -o remount,ro "$boot_rw" || warn "could not make $boot_rw read-only again (it is, from the next boot)"' EXIT
  say "$mnt is mounted read-only (--read-only): writable for the changes of this run"
}

# Where the boot config lives: Bookworm and later, or older images.
boot_config() {
  local f
  for f in "$R/boot/firmware/config.txt" "$R/boot/config.txt"; do
    [[ -f $f ]] && { echo "$f"; return; }
  done
  return 1
}

udc_exists() { compgen -G "$UDCDIR/*" >/dev/null; }

# The VIA VL805 xHCI of the Pi 4 (PCI 1106:3483).
has_vl805() {
  local d
  for d in /sys/bus/pci/devices/*; do
    [[ $(cat "$d/vendor" 2>/dev/null) == 0x1106 && $(cat "$d/device" 2>/dev/null) == 0x3483 ]] && return 0
  done
  return 1
}

# The fs_isoc_pad module through DKMS: its source in /usr/src/fs-isoc-pad-VERSION, built for the running kernel
# (DKMS rebuilds it for the next ones). Reloaded when the source changed: the cards behind the VL805 come back once.
FSIP=fs-isoc-pad
install_fs_isoc_pad() {
  local src=$here/tools/kernel/$FSIP v dst f changed=0
  v=$(sed -n 's/^PACKAGE_VERSION="\(.*\)"/\1/p' "$src/dkms.conf")
  dst=/usr/src/$FSIP-$v
  local headers=linux-headers-$(uname -r) missing=""
  dpkg -s dkms >/dev/null 2>&1 || missing="dkms"
  [[ -e /lib/modules/$(uname -r)/build ]] || missing="$missing $headers"
  if [[ -n $missing ]]; then
    say "installing $missing (for $FSIP)"
    # shellcheck disable=SC2086
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $missing
  fi
  for f in dkms.conf Kbuild Makefile fs_isoc_pad.c; do
    cmp -s "$src/$f" "$dst/$f" || changed=1
  done
  if ((changed)); then
    dkms remove -m "$FSIP" -v "$v" --all >/dev/null 2>&1 || true
    rm -rf "$dst"
    install -d "$dst"
    install -m 644 "$src"/{dkms.conf,Kbuild,Makefile,fs_isoc_pad.c} "$dst/"
    dkms add -m "$FSIP" -v "$v"
  fi
  if ! dkms status -m "$FSIP" -v "$v" -k "$(uname -r)" | grep -q installed; then
    dkms install -m "$FSIP" -v "$v" -k "$(uname -r)"
    changed=1
  fi
  if ((changed)) && grep -q '^fs_isoc_pad ' /proc/modules; then modprobe -r fs_isoc_pad; fi
  modprobe fs_isoc_pad
  say "$FSIP $v loaded"
}
uninstall_fs_isoc_pad() {
  local d
  command -v dkms >/dev/null || return 0
  modprobe -r fs_isoc_pad 2>/dev/null || true
  for d in /usr/src/$FSIP-*; do
    [[ -d $d ]] || continue
    dkms remove -m "$FSIP" -v "${d##*/$FSIP-}" --all >/dev/null 2>&1 || true
    rm -rf "$d"
  done
}

# How to leave --read-only, step by step (the summary and --uninstall print it).
readonly_undo() {
  say "to undo --read-only: sudo raspi-config nonint disable_overlayfs && sudo reboot"
  say "  (or put back the backup $CMDLINE.rpi-audio-*), then: sudo raspi-config nonint disable_bootro"
  say "  (or put back $FSTAB.rpi-audio-*), sudo systemctl disable rpi-audio-persist-restore.service rpi-audio-persist.path,"
  say "  run install.sh again without --read-only (the journal goes back to disk) and reboot."
  say "  $PERSIST_STORE/ may stay: nothing reads it then."
}
readonly_conf() {
  overlayroot_conf || bootro_conf
}

# --- Uninstall --------------------------------------------------------------

if ((uninstall)); then
  for u in $units; do
    sysrun systemctl stop "$u.service" 2>/dev/null || true
    sysrun systemctl disable "$u.service" 2>/dev/null || true
    rm -f "$UNITDIR/$u.service"
  done
  for u in $persist_units; do
    sysrun systemctl stop "$u" 2>/dev/null || true
    sysrun systemctl disable "$u" 2>/dev/null || true
    rm -f "$UNITDIR/$u"
  done
  sysrun systemctl daemon-reload
  rm -rf "$LIB"
  for b in rpi-audiod rpi-audio-persist; do
    if [[ -L $BIN/$b ]]; then rm -f "$BIN/$b"; fi
  done
  rm -f "$MODULES" "$JOURNALD" "$POWER_POLICY" "$WATCHDOG_CONF"
  if ((! staging)); then uninstall_fs_isoc_pad; fi
  say "removed the units, $LIB, the rpi-audiod link, the modules-load, journald and watchdog drop-ins and the $FSIP module"
  if ((purge)); then
    rm -rf "$ETC" "$STATE"
    say "purged $ETC and $STATE"
    if [[ -d $PERSIST_STORE ]]; then
      boot_writable "$PERSIST_STORE"
      rm -rf "$PERSIST_STORE"
      say "purged $PERSIST_STORE (the state saved by --read-only)"
    fi
  else
    say "kept $ETC and $STATE (add --purge to remove them)"
  fi
  if readonly_conf; then
    echo
    say "the read-only root (--read-only) is still configured, and without rpi-audio-persist nothing saves the state."
    readonly_undo
  fi
  echo
  say "left alone: the installed packages ($packages), the rpi-audio user and the boot config."
  if cfg=$(boot_config); then
    say "to turn the USB gadget overlay off, remove the line '$OVERLAY' from $cfg"
    say "(a backup of the file as it was before install.sh is next to it, config.txt.rpi-audio-*, if one was made), then reboot."
  fi
  say "the persistent journal setting applies until the next boot of systemd-journald."
  exit 0
fi

# --- Packages, user, realtime limits ----------------------------------------

install_packages() {
  local p missing=""
  for p in $packages; do dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"; done
  # jackd2 asks whether to allow realtime scheduling for the audio group: yes.
  echo "jackd2 jackd/tweak_rt_limits boolean true" | debconf-set-selections
  if [[ -n $missing ]]; then
    say "installing$missing"
    # shellcheck disable=SC2086
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $missing
  fi
  if [[ ! -f /etc/security/limits.d/audio.conf ]]; then
    DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive jackd2
  fi
  # rpi-audiod runs as a system user in the audio group (realtime limits for jackd).
  id rpi-audio >/dev/null 2>&1 ||
    useradd --system --gid audio --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin rpi-audio
}
if ((staging)); then say "(test root) skipped: packages and the rpi-audio user"; else install_packages; fi

if ((network)) && ((!staging)); then bash "$here/tools/build-network.sh"; fi

# --- Files ------------------------------------------------------------------

install -d "$LIB" "$ETC" "$ETC/rpi-audio.d" "$ETC/devices.d" "$ETC/hosts.d" "$BIN" "$UNITDIR" \
  "$(dirname "$MODULES")" "$(dirname "$JOURNALD")"
# Runtime setups belong to the user/service, never to the deployed configuration tree.
install -d "$STATE"
sysrun chown rpi-audio:audio "$STATE"
chmod 2775 "$STATE"
# Update existing data through descriptors so user-created links cannot redirect root's permission changes.
python3 - "$STATE" "$staging" <<'PY_STATE_PERMISSIONS'
import errno
import grp
import os
from pathlib import Path
import stat
import sys

folder, staged = Path(sys.argv[1]), sys.argv[2] == "1"
group = None if staged else grp.getgrnam("audio").gr_gid
for path in folder.iterdir():
    if path.suffix != ".json" and path.name != "slots.lock":
        continue
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOENT):
            continue
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            continue
        if group is not None:
            os.fchown(fd, -1, group)
        os.fchmod(fd, (info.st_mode & 0o666) | 0o060)
    finally:
        os.close(fd)
PY_STATE_PERMISSIONS
install -m 755 "$here/gadget/rpi-audio-gadget" "$here/gadget/rpi-audio-keepalive" "$LIB/"
install -m 755 "$here/tools/tonegen.py" "$here/bridge/rpi-audiod/rpi-audiod" "$here/bridge/rpi-audiod/rpi-audio-persist" \
  "$LIB/"
install -m 644 "$here/bridge/rpi-audiod/audiod.py" "$here/bridge/rpi-audiod/midi.py" \
  "$here/bridge/rpi-audiod/presets.py" "$here/bridge/rpi-audiod/routing.py" "$here/bridge/rpi-audiod/midiroute.py" \
  "$here/bridge/rpi-audiod/usb.py" "$here/bridge/rpi-audiod/outputs.py" \
  "$here/bridge/rpi-audiod/sdpserver.py" "$here/bridge/rpi-audiod/incidents.py" \
  "$here/bridge/rpi-audiod/readiness.py" "$here/bridge/rpi-audiod/sdnotify.py" "$here/bridge/rpi-audiod/persist.py" \
  "$LIB/"
ln -sf /usr/local/lib/rpi-audio/rpi-audiod "$BIN/rpi-audiod"
ln -sf /usr/local/lib/rpi-audio/rpi-audio-persist "$BIN/rpi-audio-persist"
# The display service: its own folder, since its module names (ui, inputs, render...) are generic.
sysrun /usr/sbin/visudo -cf "$here/config/rpi-audio-power.sudoers"
install -d "$(dirname "$POWER_POLICY")"
install -m 440 "$here/config/rpi-audio-power.sudoers" "$POWER_POLICY"
install -d "$LIB/ui"
install -m 755 "$here/bridge/rpi-audio-ui/rpi-audio-ui" "$LIB/ui/"
install -m 644 "$here"/bridge/rpi-audio-ui/{font5x7,health,inputs,meters,notices,render,sh1106,telemetry,ui,uiservice}.py "$LIB/ui/"
install -m 644 "$here/bridge/rpi-audio-ui/meter.c" "$LIB/ui/"
if ((!staging)) && { ((hat)) || [[ -x $LIB/ui/rpi-audio-meter ]]; }; then
  cc -O2 -std=c11 -Wall -Wextra -Werror "$here/bridge/rpi-audio-ui/meter.c" -ljack -lm -o "$LIB/ui/rpi-audio-meter.new"
  chmod 755 "$LIB/ui/rpi-audio-meter.new"
  mv -f "$LIB/ui/rpi-audio-meter.new" "$LIB/ui/rpi-audio-meter"
fi
install -d "$LIB/audio"
install -m 644 "$here/bridge/audio/gain.c" "$LIB/audio/"
if ((!staging)); then
  cc -O2 -std=c11 -Wall -Wextra -Werror "$here/bridge/audio/gain.c" -ljack -lm -o "$LIB/audio/rpi-audio-gain.new"
  chmod 755 "$LIB/audio/rpi-audio-gain.new"
  mv -f "$LIB/audio/rpi-audio-gain.new" "$LIB/audio/rpi-audio-gain"
fi
# The hub's native bridge to the gadget ([usb] host_bridge = "native"). -O3: its filter loop is vectorised.
install -m 644 "$here"/bridge/audio/{hostbridge.c,hostbridge_core.h} "$LIB/audio/"
if ((!staging)); then
  cc -O3 -std=c11 -Wall -Wextra -Werror "$here/bridge/audio/hostbridge.c" -lasound -ljack -lm -o "$LIB/audio/rpi-audio-hostbridge.new"
  chmod 755 "$LIB/audio/rpi-audio-hostbridge.new"
  mv -f "$LIB/audio/rpi-audio-hostbridge.new" "$LIB/audio/rpi-audio-hostbridge"
fi
install -d "$LIB/network"
install -m 644 "$here/bridge/network/network.cpp" "$LIB/network/"
if ((network)) && ((!staging)); then
  install -m 755 "$here/out/network/rpi-audio-network" "$LIB/network/rpi-audio-network.new"
  mv -f "$LIB/network/rpi-audio-network.new" "$LIB/network/rpi-audio-network"
  install -m 644 "$here/out/network/"{capabilities.json,LICENSE.md,GNU-GPL-v2.0.md} "$LIB/network/"
fi
# The version, for `rpi-audiod --version`, `ping` and `status`: the release, then the commit when known
# (deploy.sh passes it; a clone has its own).
commit=${RPI_AUDIO_COMMIT:-$(git -c safe.directory="$here" -C "$here" describe --always --dirty 2>/dev/null || true)}
printf '%s%s\n' "$(tr -d '[:space:]' < "$here/VERSION")" "${commit:+ ($commit)}" > "$LIB/VERSION"

# The ALSA sequencer, for the gadget's MIDI ports and the devices' (docs/MIDI.md).
modules='snd-seq\nsnd-seq-midi\n'
# i2c-dev gives /dev/i2c-N to a display on the header's I2C bus (--hat); once asked for, it stays.
if ((hat)) || grep -qx i2c-dev "$MODULES" 2>/dev/null; then modules+='i2c-dev\n'; fi
# fs_isoc_pad keeps the Pi 4's VL805 from dropping full-speed isochronous IN packets
# (tools/kernel/fs-isoc-pad/), built by DKMS so a kernel update rebuilds it. Only where there is a VL805.
if ((! staging)) && has_vl805; then modules+='fs_isoc_pad\n'; fi
printf "$modules" > "$MODULES"
sysrun modprobe snd-seq
sysrun modprobe snd-seq-midi
if [[ $modules == *i2c-dev* ]]; then sysrun modprobe i2c-dev; fi
if [[ $modules == *fs_isoc_pad* ]]; then install_fs_isoc_pad; fi

# A persistent journal (capped), so a shutdown can be read after the next boot: journalctl -b -1.
# On a read-only root (--read-only) /var/log is in RAM anyway: the journal stays in /run, capped, and is lost
# at every boot (from the next start of systemd-journald).
if ((ro_root)) || overlayroot_conf; then
  printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=32M\n' > "$JOURNALD"
else
  printf '[Journal]\nStorage=persistent\nSystemMaxUse=64M\n' > "$JOURNALD"
fi
if ((! staging)) && ! ((ro_root)) && ! overlayroot_conf; then
  mkdir -p /var/log/journal
  if ! ls /var/log/journal/*/system.journal >/dev/null 2>&1; then
    systemd-tmpfiles --create --prefix /var/log/journal
    systemctl restart systemd-journald
    journalctl --flush
  fi
fi

# Settings the user may have edited: written only when missing. A different version in the repo
# lands next to the file as *.new, unless --force-config. Sets $config_changed when an existing
# file was overwritten with different content.
config_changed=0
install_config() {
  local src=$1 dst
  dst=$ETC/$(basename "$1")
  if [[ ! -e $dst ]]; then
    install -m 644 "$src" "$dst"
    say "installed $dst"
  elif cmp -s "$src" "$dst"; then
    rm -f "$dst.new"
  elif ((force)); then
    install -m 644 "$src" "$dst"
    rm -f "$dst.new"
    config_changed=1
    say "overwrote $dst"
  else
    install -m 644 "$src" "$dst.new"
    say "$dst differs from this version of rpi-audio: kept yours, new version in $dst.new"
    say "  see the difference with: diff $dst $dst.new   (--force-config overwrites)"
  fi
}
install_config "$here/config/gadget.env"
gadget_env_changed=$config_changed
install_config "$here/config/rpi-audio.toml"

# Device profiles: added or replaced, never removed (others may have put theirs there).
for f in "$here"/config/devices.d/*.toml; do
  [[ -e $f ]] && install -m 644 "$f" "$ETC/devices.d/"
done
# Host profiles (chosen at runtime: `rpi-audiod host NAME`): added or replaced, never removed.
for f in "$here"/config/hosts.d/*.toml; do
  [[ -e $f ]] && install -m 644 "$f" "$ETC/hosts.d/"
done
if [[ -n $hostconf ]]; then
  if [[ -f $here/tools/hosts/$hostconf.toml ]]; then
    install -m 644 "$here/tools/hosts/$hostconf.toml" "$ETC/rpi-audio.d/"
  else
    # --host NAME of a profile: the one used until the display or `rpi-audiod host` picks another.
    rm -f "$ETC/rpi-audio.d/$hostconf.toml"   # where earlier versions put its [slots]
    printf '[host]\nprofile = "%s"\n' "$hostconf" > "$ETC/rpi-audio.d/host.toml"
  fi
fi

install -m 644 "$here/systemd/rpi-audio-gadget.service" "$here/systemd/rpi-audio-keepalive.service" \
  "$here/systemd/rpi-audiod.service" "$here/systemd/rpi-audio-cpu.service" "$here/systemd/rpi-audio-ui.service" \
  "$UNITDIR/"
for u in $persist_units; do install -m 644 "$here/systemd/$u" "$UNITDIR/"; done
sysrun systemctl daemon-reload

# --- Boot config: the USB gadget overlay ------------------------------------

overlay_added=0
overlay_pending=0   # in the file but not active yet (needs a reboot), or not added
backup=
# The config.txt model filters that match this board ([pi4], [pi5], ...), from the device tree.
# Unknown boards and staging roots without a device tree match none: only [all] then counts.
board_filters() {
  local model
  model=$(tr -d '\0' < "$R/proc/device-tree/model" 2>/dev/null) || return 0
  case $model in
    *"Compute Module 5"*) echo "pi5 cm5" ;;
    *"Pi 500"*) echo "pi5 pi500" ;;
    *"Pi 5"*) echo "pi5" ;;
    *"Compute Module 4S"*) echo "pi4 cm4s" ;;
    *"Compute Module 4"*) echo "pi4 cm4" ;;
    *"Pi 400"*) echo "pi4 pi400" ;;
    *"Pi 4"*) echo "pi4" ;;
    *"Zero 2"*) echo "pi02" ;;
    *"Zero W"*) echo "pi0 pi0w" ;;
    *"Zero"*) echo "pi0" ;;
    *"Pi 3"*Plus*) echo "pi3 pi3+" ;;
    *"Pi 3"*) echo "pi3" ;;
  esac
}
# The lines of a config.txt that apply to this board: before any section, under [all], or under a
# model filter of this board. A line under [cm5] or [pi4] on a Pi 5, or under any other kind of
# filter ([gpio4=1], [tryboot], ...), may not apply, so it does not count.
board_lines() {
  awk -v filters=" $(board_filters) " '
    BEGIN { on = 1 }
    /^[[:space:]]*\[[^]]*\][[:space:]]*$/ {
      s = tolower($0); gsub(/[][[:space:]]/, "", s)
      on = s == "all" || index(filters, " " s " ") > 0
      next
    }
    on' "$1"
}
overlay_active() {
  board_lines "$1" | grep -Eq '^[[:space:]]*dtoverlay=dwc2,([^#]*,)?dr_mode=peripheral([[:space:],]|$)'
}
last_section() { grep -E '^\[[^]]*\][[:space:]]*$' "$1" | tail -n 1 | tr -d '[:space:]' || true; }

add_overlay() {
  local cfg=$1 ts
  ts=$(date +%Y%m%d-%H%M%S)
  backup=$cfg.rpi-audio-$ts
  boot_writable "$cfg"
  cp -p "$cfg" "$backup"
  {
    # A file that does not end in a newline would swallow the first line we add.
    [[ -s $cfg && -n $(tail -c 1 "$cfg") ]] && echo
    [[ $(last_section "$cfg") == "[all]" ]] || echo "[all]"
    echo "$OVERLAY"
  } >> "$cfg"
  overlay_added=1
}

if ((bootcfg)); then
  if ! cfg=$(boot_config); then
    warn "no boot config found (/boot/firmware/config.txt or /boot/config.txt); the gadget needs $OVERLAY in it"
  elif overlay_active "$cfg"; then
    if ! udc_exists; then overlay_pending=1; fi   # set in an earlier run, no reboot since
  elif udc_exists; then
    say "a USB device controller is present already: leaving $cfg alone"
  elif board_lines "$cfg" | grep -Eq '^[[:space:]]*dtoverlay=dwc2([,[:space:]]|$)'; then
    warn "$cfg has a dwc2 overlay without dr_mode=peripheral; not editing it."
    warn "change that line to '$OVERLAY' by hand, then reboot."
    overlay_pending=1
  else
    say "the USB gadget needs '$OVERLAY' in $cfg (under [all]); it is not there."
    answer=n
    if ((yes)); then
      answer=y
    elif [[ -t 0 ]]; then
      read -r -p "$tag: add it now? A backup of the file is made first. [y/N] " answer || answer=n
    else
      warn "not a terminal and no -y: not adding it."
    fi
    case $answer in
      y|Y|yes|YES)
        add_overlay "$cfg"
        say "added '$OVERLAY' to $cfg (backup: $backup)"
        ;;
      *)
        warn "left $cfg alone; add the line '$OVERLAY' under [all] yourself, or run again with -y."
        overlay_pending=1
        ;;
    esac
  fi
fi

# --- Boot tuning: only with --tune-boot -------------------------------------

tuned=0
backup_boot() {   # one backup per file per run, named like the overlay's
  boot_writable "$1"
  [[ -e $1.rpi-audio-$ts ]] || cp -p "$1" "$1.rpi-audio-$ts"
}
if ((tuneboot)); then
  ts=$(date +%Y%m%d-%H%M%S)
  if ! cfg=$(boot_config); then
    warn "no boot config found: --tune-boot changes nothing"
  else
    # Interrupt handlers in threads, so that jackd and the bridges (realtime) come before the network's and the SD
    # card's handlers.
    cmdline=$(dirname "$cfg")/cmdline.txt
    if [[ ! -f $cmdline ]]; then
      warn "no $cmdline: threadirqs not added"
    elif ! grep -qw threadirqs "$cmdline"; then
      backup_boot "$cmdline"
      sed -i '1 s/[[:space:]]*$/ threadirqs/' "$cmdline"
      say "added threadirqs to $cmdline (backup: $cmdline.rpi-audio-$ts)"
      tuned=1
    fi
    # The Pi's own analogue audio: unused here, one card and one interrupt source fewer.
    if grep -Eq '^[[:space:]]*dtparam=audio=on' "$cfg"; then
      backup_boot "$cfg"
      sed -i -E 's/^([[:space:]]*)dtparam=audio=on/\1dtparam=audio=off/' "$cfg"
      say "changed dtparam=audio=on to off in $cfg (backup: $cfg.rpi-audio-$ts)"
      tuned=1
    elif ! grep -Eq '^[[:space:]]*dtparam=audio=off' "$cfg"; then
      backup_boot "$cfg"
      {
        [[ -s $cfg && -n $(tail -c 1 "$cfg") ]] && echo
        [[ $(last_section "$cfg") == "[all]" ]] || echo "[all]"
        echo "dtparam=audio=off"
      } >> "$cfg"
      say "added dtparam=audio=off to $cfg (backup: $cfg.rpi-audio-$ts)"
      tuned=1
    fi
  fi
fi

# --- The 40-pin header's I2C bus and a DAC: only with --hat -----------------

if ((hat)); then
  ts=${ts:-$(date +%Y%m%d-%H%M%S)}
  if ! cfg=$(boot_config); then
    warn "no boot config found: --hat changes nothing"
  else
    for line in dtparam=i2c_arm=on dtoverlay=hifiberry-dac; do
      if ! grep -Eq "^[[:space:]]*${line//./\\.}([,[:space:]]|\$)" "$cfg"; then
        backup_boot "$cfg"
        {
          [[ -s $cfg && -n $(tail -c 1 "$cfg") ]] && echo
          [[ $(last_section "$cfg") == "[all]" ]] || echo "[all]"
          echo "$line"
        } >> "$cfg"
        say "added $line to $cfg (backup: $cfg.rpi-audio-$ts)"
        tuned=1
      fi
    done
  fi
fi

# --- Read-only root: only with --read-only ----------------------------------

ro_changed=0
if ((ro_root)); then
  ts=${ts:-$(date +%Y%m%d-%H%M%S)}
  # The state as it is now goes to the store first: if that cannot be written, the root stays writable.
  "$LIB/rpi-audio-persist" --store "$PERSIST_STORE" --root "$R/var/lib" --lock "$R/run/rpi-audio-persist.lock" \
    save --now || die "cannot save the state to $PERSIST_STORE: the root is left writable"
  if ((! staging)); then
    # overlayroot is mounted by the initramfs: the firmware must load one (auto_initramfs=1, the default since
    # Bookworm), and it must have overlayroot's script, which installing the package normally adds.
    if ! grep -Eq '^[[:space:]]*auto_initramfs=1' "$R/boot/firmware/config.txt"; then
      warn "no auto_initramfs=1 in $R/boot/firmware/config.txt: without an initramfs the root stays writable"
    fi
    initrd=/boot/initrd.img-$(uname -r)
    if ! lsinitramfs "$initrd" 2>/dev/null | grep overlayroot >/dev/null; then
      boot_writable "$CMDLINE"   # update-initramfs copies the new image to /boot/firmware
      update-initramfs -u -k "$(uname -r)"
      lsinitramfs "$initrd" | grep overlayroot >/dev/null || die "$initrd has no overlayroot: the root is left writable"
    fi
  fi
  # The same edits as raspi-config's enable_overlayfs and enable_bootro, so its disable_* undo them.
  if overlayroot_conf; then
    say "$CMDLINE has overlayroot=tmpfs already"
  else
    backup_boot "$CMDLINE"
    sed -i -e 's/^/overlayroot=tmpfs /' "$CMDLINE"
    say "added overlayroot=tmpfs to $CMDLINE (backup: $CMDLINE.rpi-audio-$ts)"
    ro_changed=1
  fi
  if bootro_conf; then
    say "$FSTAB mounts /boot/firmware read-only already"
  elif overlayroot_now; then
    warn "the overlay is active, so $FSTAB cannot be changed now: /boot/firmware stays writable"
  elif grep -q '/boot/firmware.*defaults' "$FSTAB"; then
    backup_boot "$FSTAB"
    sed -i -e 's#\(.*/boot/firmware.*\)defaults\(.*\)#\1defaults,ro\2#' "$FSTAB"
    say "made /boot/firmware read-only in $FSTAB (backup: $FSTAB.rpi-audio-$ts)"
    ro_changed=1
  else
    warn "no '/boot/firmware ... defaults' line in $FSTAB: /boot/firmware stays writable (the state is saved either way)"
  fi
  # From now on: the restore finds the state just saved (nothing to do), and every change is saved.
  sysrun systemctl enable rpi-audio-persist-restore.service rpi-audio-persist.path
  sysrun systemctl start rpi-audio-persist-restore.service rpi-audio-persist.path
  say "enabled rpi-audio-persist-restore.service and rpi-audio-persist.path: every change of the state is saved"
  say "  to $PERSIST_STORE/ and put back at boot (rpi-audio-persist status shows the slots)"
fi

# --- The hardware watchdog: only with --hw-watchdog -------------------------

if [[ -n $hwwd ]]; then
  if [[ $hwwd == off ]]; then wd_value=off; else wd_value="$((10#$hwwd))s"; fi
  install -d "$(dirname "$WATCHDOG_CONF")"
  printf '# install.sh --hw-watchdog %s (docs/MANUAL.md). Remove this file to go back to the default of the OS.\n[Manager]\nRuntimeWatchdogSec=%s\n' \
    "$hwwd" "$wd_value" > "$WATCHDOG_CONF"
  wd_now=
  if ((! staging)); then wd_now=" (now: $(systemctl show -p RuntimeWatchdogUSec --value 2>/dev/null || echo unknown))"; fi
  say "hardware watchdog: RuntimeWatchdogSec=$wd_value in $WATCHDOG_CONF, from the next reboot$wd_now"
  say "  undo: sudo rm $WATCHDOG_CONF and reboot (Raspberry Pi OS arms it at 1 min by itself)"
  if [[ $hwwd != off ]]; then
    warn "a watchdog reset skips the gadget's orderly shutdown (rpi-audio-gadget down); see docs/MANUAL.md"
  fi
fi

# --- Enable, restart --------------------------------------------------------

if ((enable)); then
  sysrun systemctl disable rpi-audio-keepalive.service
  sysrun systemctl enable rpi-audio-gadget.service rpi-audiod.service rpi-audio-cpu.service
  sysrun systemctl restart rpi-audio-cpu.service
  if ((hat)); then sysrun systemctl enable rpi-audio-ui.service; fi
fi
# The display service runs the new code at once; it has no audio to interrupt, and without a display it only waits.
if ((enable && hat)); then
  sysrun systemctl restart rpi-audio-ui.service || warn "could not start rpi-audio-ui: systemctl status rpi-audio-ui"
else
  sysrun systemctl try-restart rpi-audio-ui.service
fi

# The gadget is rebound only when its settings changed (one rebind: docs/STATUS.md). rpi-audiod
# is bound to it, so it goes down and up with it; otherwise it is only restarted for the new code.
audiod_was_active=0
if unit_active rpi-audiod; then audiod_was_active=1; fi
if ((gadget_env_changed)) && unit_active rpi-audio-gadget; then
  say "gadget settings changed: restarting rpi-audio-gadget (the host hears the device reconnect)"
  sysrun systemctl restart rpi-audio-gadget.service
  if ((audiod_was_active)); then sysrun systemctl start rpi-audiod.service; fi
else
  sysrun systemctl try-restart rpi-audiod.service
fi
# A fresh install that enables the units also starts them, if there is a UDC to bind to.
if ((enable && !overlay_added)) && udc_exists; then
  sysrun systemctl start rpi-audio-gadget.service rpi-audiod.service ||
    warn "could not start the units: systemctl status rpi-audio-gadget rpi-audiod"
fi

# --- Summary ----------------------------------------------------------------

echo
for u in $units; do
  if ((staging)); then
    say "$u is (not checked)"
  else
    say "$u is $(systemctl is-enabled "$u.service" 2>&1 || true), $(systemctl is-active "$u.service" 2>&1 || true)"
  fi
done
if udc_exists; then
  for f in "$UDCDIR"/*; do say "gadget (UDC ${f##*/}): $(cat "$f/state" 2>/dev/null || echo unknown)"; done
else
  say "gadget: no UDC (the USB gadget overlay is not active)"
fi
if ((tuned)); then say "the boot changes take effect at the next reboot."; fi
if ((ro_root)); then
  if ((ro_changed)); then say "the read-only root takes effect at the next reboot (sudo reboot)."; fi
  readonly_undo
elif overlayroot_now; then
  warn "installed into the RAM overlay (--volatile): all but the boot config edits are gone at the next reboot."
elif ((! staging)) && ! overlayroot_conf && systemctl is-enabled --quiet rpi-audio-persist-restore.service 2>/dev/null; then
  say "the state is still saved to $PERSIST_STORE/, but the root is writable (no overlayroot=tmpfs in $CMDLINE):"
  say "  run install.sh --read-only to make it read-only again, or see docs/MANUAL.md to leave read-only mode."
fi
if ((overlay_added)); then
  say "next: reboot the Pi (sudo reboot) so the USB gadget overlay takes effect, then connect its USB-C to the host."
elif ((overlay_pending)); then
  say "next: fix the boot config as said above, reboot, then connect the Pi's USB-C to the host."
else
  say "next: connect the Pi's USB-C to the host."
fi
