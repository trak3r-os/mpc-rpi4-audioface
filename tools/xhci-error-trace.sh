#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Record the xHCI events on the Pi whose completion code is not Success or
# Short Packet, for SECONDS seconds, on every xHCI controller. Tells apart
# what usbmon folds into one isochronous status: -EXDEV/0 B can be a Missed
# Service Error (23) or a TD skipped after a Ring Overrun/Underrun (21/14);
# a bus error would be a USB Transaction Error (4, -EPROTO) instead.
#
# Diagnostic only: it enables one tracepoint with a filter and puts the trace
# state back as it found it. Needs passwordless sudo on the Pi. Start the
# stream you want to observe first; this script does not touch audio.
#
#   PI_HOST=no3z@raspberrypi.local tools/xhci-error-trace.sh 20 > out/xhci-errors-$(date +%F-%H%M%S).txt

set -euo pipefail

host="${PI_HOST:-no3z@raspberrypi.local}"
seconds="${1:-20}"
[[ "$seconds" =~ ^[0-9]+$ ]] || { echo "usage: $0 [seconds]" >&2; exit 2; }
ssh_opts=(-o BatchMode=yes -o ConnectTimeout=8)
[[ -n "${PI_SSH_HOST_KEY_ALIAS:-}" ]] && ssh_opts+=(-o "HostKeyAlias=$PI_SSH_HOST_KEY_ALIAS")

echo "# xhci-error-trace $(date -Is) host=${host#*@} seconds=$seconds"

ssh "${ssh_opts[@]}" "$host" "sudo -n sh -s $seconds" <<'REMOTE'
set -eu
seconds="$1"
t=/sys/kernel/tracing
[ -d "$t/events" ] || mount -t tracefs nodev "$t"
ev="$t/events/xhci-hcd/xhci_handle_event"
[ -e "$ev/enable" ] || { echo "no xhci_handle_event tracepoint" >&2; exit 1; }

old_on=$(cat "$t/tracing_on"); old_en=$(cat "$ev/enable")
restore() {
    echo 0 > "$ev/enable"; echo 0 > "$ev/filter"
    echo "$old_en" > "$ev/enable"; echo "$old_on" > "$t/tracing_on"
}
trap restore EXIT INT TERM

echo "## controllers"
for b in /sys/bus/usb/devices/usb*; do
    printf '%s %s %s\n' "${b##*/}" "$(readlink -f "$b" | sed 's#/usb[0-9]*$##; s#.*/##')" "$(cat "$b/speed")M"
done
echo "## topology"; lsusb -t

# Completion code is field2[31:24]. Keep everything except 1 (Success) and 13 (Short Packet).
echo '(field2 < 0x01000000) || (field2 >= 0x02000000 && field2 < 0x0d000000) || field2 >= 0x0e000000' > "$ev/filter"
echo > "$t/trace"
echo 1 > "$ev/enable"; echo 1 > "$t/tracing_on"
sleep "$seconds"
echo 0 > "$ev/enable"

echo "## events"
grep -v '^#' "$t/trace" || true
echo "## completion codes"
grep -v '^#' "$t/trace" | grep -oE "status '[^']*'.*slot [0-9]+ ep [0-9]+" \
    | sed -E "s/ len [0-9]+//" | sort | uniq -c | sort -rn || true
echo "## dropped events: $(cat "$t/per_cpu/cpu0/stats" 2>/dev/null | awk '$1 == "overrun:" {print $2}')"
REMOTE
