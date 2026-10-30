#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install rpi-audio on this Raspberry Pi, from a clone of the repository.
#
#   git clone https://github.com/trak3r-os/mpc-rpi4-audioface.git
#   cd mpc-rpi4-audioface && sudo ./install.sh
#
#   sudo ./install.sh [--host NAME] [--no-enable] [--force-config] [--no-boot-config] [--tune-boot] [-y]
#   sudo ./install.sh --uninstall [--purge]
#
#   --host NAME        also install tools/hosts/NAME.toml as /etc/rpi-audio/rpi-audio.d/NAME.toml
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
#   -y                 answer yes to the question about the boot config (the gadget overlay)
#   --uninstall        remove what this script installed; /etc/rpi-audio and /var/lib/rpi-audio stay
#   --purge            with --uninstall: remove those two as well
#
# Idempotent: run it again after every `git pull`. A running rpi-audiod is restarted so it
# runs the new code (the host hears a gap); the gadget only when its settings changed.
# The boot config is touched only to add the USB gadget overlay, after asking, and with
# --tune-boot, always with a backup; the Pi is never rebooted by this script.
# rpi-audio-cpu.service keeps the CPU governor at "performance" (disable it to go back to "ondemand").
# PipeWire must not be installed alongside: it would grab the gadget and steer its pitch.
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
STATE=$R/var/lib/rpi-audio
UDCDIR=$R/sys/class/udc
OVERLAY='dtoverlay=dwc2,dr_mode=peripheral'
units="rpi-audio-gadget rpi-audiod rpi-audio-keepalive rpi-audio-cpu"
packages="jackd2 jack-example-tools zita-ajbridge"

say() { echo "$tag: $*"; }
warn() { echo "$tag: $*" >&2; }
die() { warn "$*"; exit 1; }
usage() {
  cat >&2 <<'EOF'
usage: sudo ./install.sh [--host NAME] [--no-enable] [--force-config] [--no-boot-config] [--tune-boot] [-y]
       sudo ./install.sh --uninstall [--purge]
EOF
  exit 2
}

# Commands that act on the running system: skipped under RPI_AUDIO_ROOT.
sysrun() { if ((staging)); then say "(test root) skipped: $*"; else "$@"; fi; }
# Queries about units: nothing to ask under RPI_AUDIO_ROOT.
unit_active() { ((! staging)) && systemctl is-active --quiet "$1.service"; }

enable=1 force=0 bootcfg=1 tuneboot=0 yes=0 uninstall=0 purge=0 hostconf=
while (($#)); do
  case $1 in
    --host) hostconf=${2:?--host needs a name}; shift ;;
    --no-enable) enable=0 ;;
    --force-config) force=1 ;;
    --no-boot-config) bootcfg=0 ;;
    --tune-boot) tuneboot=1 ;;
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
if [[ -n $hostconf ]]; then
  [[ $hostconf =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid host name: $hostconf"
  [[ -f $here/tools/hosts/$hostconf.toml ]] || die "no tools/hosts/$hostconf.toml in this clone"
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

# Where the boot config lives: Bookworm and later, or older images.
boot_config() {
  local f
  for f in "$R/boot/firmware/config.txt" "$R/boot/config.txt"; do
    [[ -f $f ]] && { echo "$f"; return; }
  done
  return 1
}

udc_exists() { compgen -G "$UDCDIR/*" >/dev/null; }

# --- Uninstall --------------------------------------------------------------

if ((uninstall)); then
  for u in $units; do
    sysrun systemctl stop "$u.service" 2>/dev/null || true
    sysrun systemctl disable "$u.service" 2>/dev/null || true
    rm -f "$UNITDIR/$u.service"
  done
  sysrun systemctl daemon-reload
  rm -rf "$LIB"
  if [[ -L $BIN/rpi-audiod ]]; then rm -f "$BIN/rpi-audiod"; fi
  rm -f "$MODULES" "$JOURNALD"
  say "removed the units, $LIB, the rpi-audiod link and the modules-load and journald drop-ins"
  if ((purge)); then
    rm -rf "$ETC" "$STATE"
    say "purged $ETC and $STATE"
  else
    say "kept $ETC and $STATE (add --purge to remove them)"
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

# --- Files ------------------------------------------------------------------

install -d "$LIB" "$ETC" "$ETC/rpi-audio.d" "$ETC/devices.d" "$BIN" "$UNITDIR" \
  "$(dirname "$MODULES")" "$(dirname "$JOURNALD")"
install -m 755 "$here/gadget/rpi-audio-gadget" "$here/gadget/rpi-audio-keepalive" "$LIB/"
install -m 755 "$here/tools/tonegen.py" "$here/bridge/rpi-audiod/rpi-audiod" "$LIB/"
install -m 644 "$here/bridge/rpi-audiod/audiod.py" "$here/bridge/rpi-audiod/midi.py" \
  "$here/bridge/rpi-audiod/presets.py" "$here/bridge/rpi-audiod/usb.py" "$LIB/"
ln -sf /usr/local/lib/rpi-audio/rpi-audiod "$BIN/rpi-audiod"
# The version, for `rpi-audiod --version`, `ping` and `status`: the release, then the commit when known
# (deploy.sh passes it; a clone has its own).
commit=${RPI_AUDIO_COMMIT:-$(git -c safe.directory="$here" -C "$here" describe --always --dirty 2>/dev/null || true)}
printf '%s%s\n' "$(tr -d '[:space:]' < "$here/VERSION")" "${commit:+ ($commit)}" > "$LIB/VERSION"

# The ALSA sequencer, for the gadget's MIDI ports and the devices' (docs/MIDI.md).
printf 'snd-seq\nsnd-seq-midi\n' > "$MODULES"
sysrun modprobe snd-seq
sysrun modprobe snd-seq-midi

# A persistent journal (capped), so a shutdown can be read after the next boot: journalctl -b -1.
printf '[Journal]\nStorage=persistent\nSystemMaxUse=64M\n' > "$JOURNALD"
if ((! staging)); then
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
if [[ -n $hostconf ]]; then install -m 644 "$here/tools/hosts/$hostconf.toml" "$ETC/rpi-audio.d/"; fi

install -m 644 "$here/systemd/rpi-audio-gadget.service" "$here/systemd/rpi-audio-keepalive.service" \
  "$here/systemd/rpi-audiod.service" "$here/systemd/rpi-audio-cpu.service" "$UNITDIR/"
sysrun systemctl daemon-reload

# --- Boot config: the USB gadget overlay ------------------------------------

overlay_added=0
overlay_pending=0   # in the file but not active yet (needs a reboot), or not added
backup=
overlay_active() {
  grep -Eq '^[[:space:]]*dtoverlay=dwc2,([^#]*,)?dr_mode=peripheral([[:space:],]|$)' "$1"
}
last_section() { grep -E '^\[[^]]*\][[:space:]]*$' "$1" | tail -n 1 | tr -d '[:space:]' || true; }

add_overlay() {
  local cfg=$1 ts
  ts=$(date +%Y%m%d-%H%M%S)
  backup=$cfg.rpi-audio-$ts
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
  elif grep -Eq '^[[:space:]]*dtoverlay=dwc2([,[:space:]]|$)' "$cfg"; then
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

# --- Enable, restart --------------------------------------------------------

if ((enable)); then
  sysrun systemctl disable rpi-audio-keepalive.service
  sysrun systemctl enable rpi-audio-gadget.service rpi-audiod.service rpi-audio-cpu.service
  sysrun systemctl restart rpi-audio-cpu.service
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
if ((tuned)); then say "the boot tuning takes effect at the next reboot."; fi
if ((overlay_added)); then
  say "next: reboot the Pi (sudo reboot) so the USB gadget overlay takes effect, then connect its USB-C to the host."
elif ((overlay_pending)); then
  say "next: fix the boot config as said above, reboot, then connect the Pi's USB-C to the host."
else
  say "next: connect the Pi's USB-C to the host."
fi
