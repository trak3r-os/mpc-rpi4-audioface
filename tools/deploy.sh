#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copy rpi-audio to the Pi and install it. Idempotent: run it after every change.
#
#   PI_HOST=no3z@raspberrypi.local tools/deploy.sh [--enable] [--host NAME] [--hat] [--network]
#                                                  [--read-only] [--hw-watchdog SECONDS|off] [--volatile]
#
# --enable also enables rpi-audio-gadget.service and rpi-audiod.service at boot
# (and disables rpi-audio-keepalive.service, which rpi-audiod replaces). Without
# it they are started by hand (`sudo systemctl start rpi-audio-gadget rpi-audiod`).
# --host NAME makes the host profile NAME (config/hosts.d/, e.g. akai-force) the default one; the display or
# `rpi-audiod host NAME` change it at runtime. NAME may also be a tools/hosts/NAME.toml (e.g. standalone).
# --hat also turns on the I2C bus and the hifiberry-dac overlay (a display and a DAC on the 40-pin header; install.sh --hat,
# with a backup of config.txt; takes effect after a reboot, which this script never does) and, with --enable,
# starts rpi-audio-ui.service (the OLED and its encoder).
# --read-only and --hw-watchdog S|off are install.sh's (the root as a RAM overlay, with the state saved on the boot
# partition; systemd's hardware watchdog timeout): see its header and docs/MANUAL.md, and the risks there.
# On a Pi whose root already is a RAM overlay (--read-only active) a deploy would be gone at the next boot,
# so this stops and says how to turn the overlay off first; --volatile deploys anyway (until the next reboot).
# --ui-only updates the Python display service and its restricted power policy, with a backup and UI restart;
# it preserves audio, configuration, the native meter helper and boot settings.
# --usb-c-bench host|restore only changes the Pi 4 USB-C boot role, with a checked
# backup. Requires explicit user approval; never reboots or runs the installer.
# A running rpi-audiod is restarted so it runs the new code: the host hears a gap.
# Needs passwordless sudo for the SSH user on the Pi (see docs/STATUS.md).
# This is a thin wrapper: it copies the repo to the Pi and runs install.sh there as root with
# --force-config -y (the repo's settings overwrite /etc/rpi-audio's, as always for development).
# Packages, PipeWire check, the boot overlay and the rest are install.sh's job.

set -euo pipefail

host="${PI_HOST:-no3z@raspberrypi.local}"
root="$(cd "$(dirname "$0")/.." && pwd)"
stage=rpi-audio-stage
enable=0 hat=0 network=0 ui_only=0 hostconf= usb_c_bench= ro_root=0 volatile=0 hwwd=
usage() {
  echo "usage: $0 [--enable] [--host NAME] [--hat] [--network] [--read-only] [--hw-watchdog SECONDS|off] [--volatile]" >&2
  echo "       $0 --ui-only [--volatile] | --usb-c-bench host|restore" >&2
  exit 2
}
while (($#)); do
  case $1 in
    --enable) enable=1 ;;
    --hat) hat=1 ;;
    --network) network=1 ;;
    --ui-only) ui_only=1 ;;
    --read-only) ro_root=1 ;;
    --volatile) volatile=1 ;;
    --hw-watchdog) hwwd=${2:?--hw-watchdog needs a number of seconds or off}; shift ;;
    --host) hostconf=${2:?--host needs a name}; shift ;;
    --usb-c-bench) usb_c_bench=${2:?--usb-c-bench needs host or restore}; shift ;;
    *) usage ;;
  esac
  shift
done
# It goes into a remote command line: only a number or off (install.sh checks the range).
if [[ -n $hwwd && $hwwd != off && ! $hwwd =~ ^[0-9]{1,3}$ ]]; then usage; fi
if [[ -n $usb_c_bench ]]; then
  if [[ $usb_c_bench != host && $usb_c_bench != restore ]] ||
     ((enable || hat || network || ui_only || ro_root || volatile)) || [[ -n $hostconf || -n $hwwd ]]; then
    echo "deploy: --usb-c-bench host|restore must be used alone" >&2
    exit 2
  fi
  bench_ssh=(-o BatchMode=yes -o StrictHostKeyChecking=yes)
  [[ -z ${PI_SSH_HOST_KEY_ALIAS:-} ]] || bench_ssh+=(-o "HostKeyAlias=$PI_SSH_HOST_KEY_ALIAS")
  ssh "${bench_ssh[@]}" "$host" "sudo -n python3 - $usb_c_bench" < "$root/tools/hosts/pi-usb-c-bench.py"
  exit 0
fi
if ((ui_only && (enable || hat || network || ro_root))) || { ((ui_only)) && [[ -n $hostconf || -n $hwwd ]]; }; then
  echo "deploy: --ui-only cannot be combined with audio/boot installation options" >&2
  exit 2
fi
if [[ -n $hostconf && ! -f $root/tools/hosts/$hostconf.toml && ! -f $root/config/hosts.d/$hostconf.toml ]]; then
  echo "deploy: no config/hosts.d/$hostconf.toml or tools/hosts/$hostconf.toml" >&2
  exit 2
fi

# Refuse a gadget configuration the kernel would reject, before touching the Pi.
if ((!ui_only)); then
  (set -a; . "$root/config/gadget.env"; "$root/gadget/rpi-audio-gadget" check)
fi

ssh -o BatchMode=yes "$host" 'sudo -n true' 2>/dev/null || {
  echo "deploy: $host has no passwordless sudo; see docs/STATUS.md" >&2
  exit 1
}

# A read-only root (install.sh --read-only): whatever is installed now would be gone at the next boot.
if ssh -o BatchMode=yes "$host" 'grep -qw overlayroot=tmpfs /proc/cmdline'; then
  if ((!volatile)); then
    echo "deploy: the root of $host is a RAM overlay (install.sh --read-only): a deploy would be gone at the next boot." >&2
    echo "  1. ssh $host 'sudo raspi-config nonint disable_overlayfs && sudo reboot'" >&2
    echo "  2. $0 --read-only [the other options]    (installs, and turns the read-only root back on)" >&2
    echo "  3. ssh $host 'sudo reboot'" >&2
    echo "  --volatile deploys into the overlay anyway, for a test that the next reboot undoes." >&2
    exit 1
  fi
  echo "deploy: the root of $host is a RAM overlay: this deploy lasts until the next reboot (--volatile)" >&2
fi

if ((ui_only)); then
  ssh "$host" "mkdir -p $stage/bridge/rpi-audio-ui $stage/config"
  rsync -a "$root/bridge/rpi-audio-ui/" "$host:$stage/bridge/rpi-audio-ui/"
  rsync -a "$root/config/rpi-audio-power.sudoers" "$host:$stage/config/"
  ssh "$host" "sudo -n bash -s -- $stage" <<'UI_INSTALL'
set -euo pipefail
source_dir="$PWD/$1/bridge/rpi-audio-ui"
lib=/usr/local/lib/rpi-audio/ui
[[ -d $lib ]] || { echo "deploy: install the display service first" >&2; exit 1; }
policy="$PWD/$1/config/rpi-audio-power.sudoers"
/usr/sbin/visudo -cf "$policy"
backup=$(mktemp -d /var/backups/rpi-audio-ui.XXXXXX)
cp -a "$lib" "$backup/ui"
if [[ -f /etc/sudoers.d/rpi-audio-power ]]; then
  cp -a /etc/sudoers.d/rpi-audio-power "$backup/power.sudoers"
fi
install -d /etc/sudoers.d
install -m 440 "$policy" /etc/sudoers.d/rpi-audio-power
install -m 644 "$source_dir/"*.py "$lib/"
install -m 755 "$source_dir/rpi-audio-ui" "$lib/"
if systemctl is-active --quiet rpi-audio-ui; then
  systemctl restart rpi-audio-ui
fi
echo "deploy: UI updated; backup: $backup/ui"
UI_INSTALL
  exit 0
fi

rsync -a --delete "$root/gadget" "$root/systemd" "$root/config" "$root/tools" "$root/bridge" "$root/install.sh" \
  "$root/VERSION" "$host:$stage/"

args=(--force-config -y)
((enable)) || args+=(--no-enable)
((hat)) && args+=(--hat)
((network)) && args+=(--network)
((ro_root)) && args+=(--read-only)
((volatile)) && args+=(--volatile)
[[ -z $hwwd ]] || args+=(--hw-watchdog "$hwwd")
[[ -z $hostconf ]] || args+=(--host "$hostconf")
# install.sh does the work on the Pi; RPI_AUDIO_TAG keeps its messages prefixed "deploy:". The copy has no .git, so
# the commit goes along for the version.
commit=$(git -C "$root" describe --always --dirty 2>/dev/null || echo unknown)
ssh "$host" "sudo -n env RPI_AUDIO_TAG=deploy RPI_AUDIO_COMMIT=$commit \"\$PWD/$stage/install.sh\" ${args[*]}"
