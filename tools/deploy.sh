#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copy rpi-audio to the Pi and install it. Idempotent: run it after every change.
#
#   PI_HOST=no3z@192.168.1.106 tools/deploy.sh [--enable] [--host NAME]
#
# --enable also enables rpi-audio-gadget.service and rpi-audiod.service at boot
# (and disables rpi-audio-keepalive.service, which rpi-audiod replaces). Without
# it they are started by hand (`sudo systemctl start rpi-audio-gadget rpi-audiod`).
# --host NAME installs tools/hosts/NAME.toml as /etc/rpi-audio/rpi-audio.d/NAME.toml
# (rpi-audiod settings for that host, e.g. akai-force).
# A running rpi-audiod is restarted so it runs the new code: the host hears a gap.
# Needs passwordless sudo for the SSH user on the Pi (see docs/STATUS.md).
# Installs the Debian packages in $packages when missing (mode A engine, docs/PLAN.md).
# PipeWire must not be installed alongside: it would grab the gadget and steer its pitch.

set -euo pipefail

host="${PI_HOST:-no3z@192.168.1.106}"
root="$(cd "$(dirname "$0")/.." && pwd)"
stage=rpi-audio-stage
packages="jackd2 jack-example-tools zita-ajbridge"
enable=0 hostconf=
while (($#)); do
  case $1 in
    --enable) enable=1 ;;
    --host) hostconf=${2:?--host needs a name}; shift ;;
    *) echo "usage: $0 [--enable] [--host NAME]" >&2; exit 2 ;;
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

rsync -a --delete "$root/gadget" "$root/systemd" "$root/config" "$root/tools" "$root/bridge" "$host:$stage/"

ssh "$host" "sudo -n sh -s" <<EOF
set -e
export LC_ALL=C.UTF-8
if dpkg -s pipewire >/dev/null 2>&1; then echo "deploy: pipewire is installed; remove it first" >&2; exit 1; fi
missing=""
for p in $packages; do dpkg -s \$p >/dev/null 2>&1 || missing="\$missing \$p"; done
# jackd2 asks whether to allow realtime scheduling for the audio group: yes.
echo "jackd2 jackd/tweak_rt_limits boolean true" | debconf-set-selections
if [ -n "\$missing" ]; then
  echo "deploy: installing\$missing"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \$missing
fi
if [ ! -f /etc/security/limits.d/audio.conf ]; then
  DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive jackd2
fi
# rpi-audiod runs as a system user in the audio group (realtime limits for jackd).
id rpi-audio >/dev/null 2>&1 || useradd --system --gid audio --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin rpi-audio
install -d /usr/local/lib/rpi-audio /etc/rpi-audio /etc/rpi-audio/rpi-audio.d /etc/rpi-audio/devices.d
install -m 755 $stage/gadget/rpi-audio-gadget $stage/gadget/rpi-audio-keepalive /usr/local/lib/rpi-audio/
install -m 755 $stage/tools/tonegen.py $stage/bridge/rpi-audiod/rpi-audiod /usr/local/lib/rpi-audio/
install -m 644 $stage/bridge/rpi-audiod/audiod.py $stage/bridge/rpi-audiod/midi.py $stage/bridge/rpi-audiod/presets.py $stage/bridge/rpi-audiod/usb.py /usr/local/lib/rpi-audio/
# The ALSA sequencer, for the gadget's MIDI ports and the devices' (docs/MIDI.md).
printf 'snd-seq\nsnd-seq-midi\n' > /etc/modules-load.d/rpi-audio.conf
modprobe snd-seq
modprobe snd-seq-midi
# A persistent journal (capped), so a shutdown can be read after the next boot: journalctl -b -1.
mkdir -p /etc/systemd/journald.conf.d /var/log/journal
printf '[Journal]\nStorage=persistent\nSystemMaxUse=64M\n' > /etc/systemd/journald.conf.d/rpi-audio.conf
if ! ls /var/log/journal/*/system.journal >/dev/null 2>&1; then
  systemd-tmpfiles --create --prefix /var/log/journal
  systemctl restart systemd-journald
  journalctl --flush
fi
ln -sf /usr/local/lib/rpi-audio/rpi-audiod /usr/local/bin/rpi-audiod
install -m 644 $stage/config/gadget.env $stage/config/rpi-audio.toml /etc/rpi-audio/
# Device profiles: added or replaced, never removed (others may have put theirs there).
for f in $stage/config/devices.d/*.toml; do
  [ -e "\$f" ] && install -m 644 "\$f" /etc/rpi-audio/devices.d/
done
if [ -n "$hostconf" ]; then install -m 644 $stage/tools/hosts/$hostconf.toml /etc/rpi-audio/rpi-audio.d/; fi
install -m 644 $stage/systemd/rpi-audio-gadget.service $stage/systemd/rpi-audio-keepalive.service \
  $stage/systemd/rpi-audiod.service /etc/systemd/system/
systemctl daemon-reload
if [ $enable = 1 ]; then
  systemctl disable rpi-audio-keepalive.service
  systemctl enable rpi-audio-gadget.service rpi-audiod.service
fi
systemctl try-restart rpi-audiod.service
for u in rpi-audio-gadget rpi-audiod rpi-audio-keepalive; do
  echo "deploy: \$u is \$(systemctl is-enabled \$u.service), \$(systemctl is-active \$u.service)"
done
EOF
