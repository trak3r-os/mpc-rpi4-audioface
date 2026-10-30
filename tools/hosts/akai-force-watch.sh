#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Read-only: poll, on the Akai Force, the state and pointers of the gadget's
# ALSA streams as MPC drives them, plus MPC's audio log lines. Nothing is
# written on the Force.
#
# Usage:
#   FORCE_HOST=root@force.local [FORCE_PASS=...] tools/hosts/akai-force-watch.sh SECONDS > out/force-watch-$(date +%F-%H%M%S).txt
#
# GADGET_CARD (default rpiaudio) is the ALSA card id of the gadget on the Force.
# Each line: wall time, uptime (s), then per stream (c = Pi -> Force, p = Force -> Pi)
# its state and hw_ptr, or "closed".

set -euo pipefail

# shellcheck source=force-ssh.sh
. "$(dirname "$0")/force-ssh.sh"
seconds="${1:?usage: $0 SECONDS}"
card="${GADGET_CARD:-rpiaudio}"

echo "# force-watch $(date -Is) host=${host#*@} card=$card seconds=$seconds"

force_ssh "CARD=$card SECONDS_=$seconds sh -s" <<'REMOTE'
stream() {
  s=/proc/asound/$CARD/$1/sub0/status
  [ -r "$s" ] || { printf '%s=absent' "$1"; return; }
  awk -v n="$1" '/^closed/ {printf "%s=closed", n; exit}
                 /^state:/ {st=$2} /^hw_ptr/ {hp=$3}
                 END {if (st != "") printf "%s=%s@%s", n, st, hp}' "$s"
}
start=$(date +%s)
end=$(( start + SECONDS_ ))
while [ "$(date +%s)" -lt "$end" ]; do
  printf '%s up=%s %s %s\n' "$(date +%T)" "$(cut -d' ' -f1 /proc/uptime)" "$(stream pcm0c)" "$(stream pcm0p)"
  sleep 0.5 2>/dev/null || sleep 1
done
# Nothing is left running on the Force: the log is read once, at the end.
journalctl --since "@$start" --no-pager 2>/dev/null | grep -E '\*\*\*\*' | sed 's/^/log: /'
REMOTE
