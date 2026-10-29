#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copy rpi-audio to the Pi and install it. Idempotent: run it after every change.
#
#   PI_HOST=no3z@192.168.1.106 tools/deploy.sh [--enable]
#
# --enable also enables rpi-audio-gadget.service and rpi-audio-keepalive.service
# at boot. Without it they are started by hand (`sudo systemctl start rpi-audio-gadget
# rpi-audio-keepalive`).
# Needs passwordless sudo for the SSH user on the Pi (see docs/STATUS.md).

set -euo pipefail

host="${PI_HOST:-no3z@192.168.1.106}"
root="$(cd "$(dirname "$0")/.." && pwd)"
stage=rpi-audio-stage
enable=0
[[ ${1:-} == --enable ]] && enable=1

# Refuse a gadget configuration the kernel would reject, before touching the Pi.
(set -a; . "$root/config/gadget.env"; "$root/gadget/rpi-audio-gadget" check)

ssh -o BatchMode=yes "$host" 'sudo -n true' 2>/dev/null || {
  echo "deploy: $host has no passwordless sudo; see docs/STATUS.md" >&2
  exit 1
}

rsync -a --delete "$root/gadget" "$root/systemd" "$root/config" "$root/tools" "$host:$stage/"

ssh "$host" "sudo -n sh -s" <<EOF
set -e
install -d /usr/local/lib/rpi-audio /etc/rpi-audio
install -m 755 $stage/gadget/rpi-audio-gadget $stage/gadget/rpi-audio-keepalive /usr/local/lib/rpi-audio/
install -m 755 $stage/tools/tonegen.py /usr/local/lib/rpi-audio/
install -m 644 $stage/config/gadget.env /etc/rpi-audio/gadget.env
install -m 644 $stage/systemd/rpi-audio-gadget.service $stage/systemd/rpi-audio-keepalive.service /etc/systemd/system/
systemctl daemon-reload
if [ $enable = 1 ]; then systemctl enable rpi-audio-gadget.service rpi-audio-keepalive.service; fi
for u in rpi-audio-gadget rpi-audio-keepalive; do
  echo "deploy: \$u is \$(systemctl is-enabled \$u.service), \$(systemctl is-active \$u.service)"
done
EOF
