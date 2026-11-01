#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copy rpi-audio to the Pi and install it. Idempotent: run it after every change.
#
#   PI_HOST=no3z@192.168.1.106 tools/deploy.sh [--enable] [--host NAME] [--hat]
#
# --enable also enables rpi-audio-gadget.service and rpi-audiod.service at boot
# (and disables rpi-audio-keepalive.service, which rpi-audiod replaces). Without
# it they are started by hand (`sudo systemctl start rpi-audio-gadget rpi-audiod`).
# --host NAME installs tools/hosts/NAME.toml as /etc/rpi-audio/rpi-audio.d/NAME.toml
# (rpi-audiod settings for that host, e.g. akai-force).
# --hat also turns on the I2C bus and the hifiberry-dac overlay (a display and a DAC on the 40-pin header; install.sh --hat,
# with a backup of config.txt; takes effect after a reboot, which this script never does) and, with --enable,
# starts rpi-audio-ui.service (the OLED and its encoder).
# A running rpi-audiod is restarted so it runs the new code: the host hears a gap.
# Needs passwordless sudo for the SSH user on the Pi (see docs/STATUS.md).
# This is a thin wrapper: it copies the repo to the Pi and runs install.sh there as root with
# --force-config -y (the repo's settings overwrite /etc/rpi-audio's, as always for development).
# Packages, PipeWire check, the boot overlay and the rest are install.sh's job.

set -euo pipefail

host="${PI_HOST:-no3z@192.168.1.106}"
root="$(cd "$(dirname "$0")/.." && pwd)"
stage=rpi-audio-stage
enable=0 hat=0 hostconf=
while (($#)); do
  case $1 in
    --enable) enable=1 ;;
    --hat) hat=1 ;;
    --host) hostconf=${2:?--host needs a name}; shift ;;
    *) echo "usage: $0 [--enable] [--host NAME] [--hat]" >&2; exit 2 ;;
  esac
  shift
done
if [[ -n $hostconf && ! -f $root/tools/hosts/$hostconf.toml ]]; then
  echo "deploy: no tools/hosts/$hostconf.toml" >&2
  exit 2
fi

# Refuse a gadget configuration the kernel would reject, before touching the Pi.
(set -a; . "$root/config/gadget.env"; "$root/gadget/rpi-audio-gadget" check)

ssh -o BatchMode=yes "$host" 'sudo -n true' 2>/dev/null || {
  echo "deploy: $host has no passwordless sudo; see docs/STATUS.md" >&2
  exit 1
}

rsync -a --delete "$root/gadget" "$root/systemd" "$root/config" "$root/tools" "$root/bridge" "$root/install.sh" \
  "$root/VERSION" "$host:$stage/"

args=(--force-config -y)
((enable)) || args+=(--no-enable)
((hat)) && args+=(--hat)
[[ -z $hostconf ]] || args+=(--host "$hostconf")
# install.sh does the work on the Pi; RPI_AUDIO_TAG keeps its messages prefixed "deploy:". The copy has no .git, so
# the commit goes along for the version.
commit=$(git -C "$root" describe --always --dirty 2>/dev/null || echo unknown)
ssh "$host" "sudo -n env RPI_AUDIO_TAG=deploy RPI_AUDIO_COMMIT=$commit \"\$PWD/$stage/install.sh\" ${args[*]}"
