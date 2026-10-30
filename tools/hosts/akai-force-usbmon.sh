#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Read-only: stream the Akai Force's usbmon text for the rpi-audio device to this computer, one file per minute,
# keeping the last KEEP files (default 10). Nothing is written on the Force: it reads
# /sys/kernel/debug/usb/usbmon/<bus>u (the Force's kernel has usbmon built in and debugfs mounted) and filters it to
# the gadget's address there. For catching what the USB link did just before an MPC audio error: stop it right after
# the error and the last minutes are on disk.
#
#   FORCE_HOST=root@force.local FORCE_PASS=... tools/hosts/akai-force-usbmon.sh OUT_DIR [KEEP]
#
# The device number changes when the gadget enumerates again: restart this afterwards.

set -euo pipefail
out=${1:?usage: $0 OUT_DIR [KEEP]}
keep=${2:-10}
mkdir -p "$out"
out=$(cd "$out" && pwd)
cd "$(dirname "$0")"
. ./force-ssh.sh

addr=$(force_ssh 'for d in /sys/bus/usb/devices/*; do
  [ "$(cat "$d/product" 2>/dev/null)" = rpi-audio ] && { printf "%s %03d\n" "$(cat "$d/busnum")" "$(cat "$d/devnum")"; break; }
done' 2>/dev/null)
[[ -n $addr ]] || { echo "usbmon: no rpi-audio device on the Force" >&2; exit 1; }
read -r bus dev <<<"$addr"
echo "usbmon: bus $bus, device $dev -> $out (last $keep minutes)" >&2

force_ssh "grep ':$bus:$dev:' /sys/kernel/debug/usb/usbmon/${bus}u" 2>/dev/null |
  python3 -u -c '
import os, sys, time
out, keep = sys.argv[1], int(sys.argv[2])
cur, f = None, None
for line in sys.stdin:
    name = time.strftime("usbmon-%Y%m%d-%H%M.txt")
    if name != cur:
        if f:
            f.close()
        cur, f = name, open(os.path.join(out, name), "a")
        old = sorted(n for n in os.listdir(out) if n.startswith("usbmon-"))[:-keep]
        for n in old:
            os.remove(os.path.join(out, n))
    f.write(line)
' "$out" "$keep"
