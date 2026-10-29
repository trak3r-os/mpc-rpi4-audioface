#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Duplex soak between this machine (the USB host) and the Pi (the gadget):
# tones both ways at once, each direction checked with tonecheck.py here.
#
#   tools/soak.sh CHANNELS SECONDS
#
# HOST_CARD (default rpiaudio) is the gadget's ALSA card on this machine,
# PI_CARD (default UAC2Gadget) the gadget's card on the Pi, PI_HOST as for
# deploy.sh. Results go to out/soak-<date>-<N>ch/.
#
# The host opens its streams first: the gadget's PCM only moves while the
# host streams, and a Pi-side aplay started earlier fails with EIO.

set -euo pipefail

ch=${1:?usage: soak.sh CHANNELS SECONDS}
secs=${2:?usage: soak.sh CHANNELS SECONDS}
host=${PI_HOST:-no3z@192.168.1.106}
hcard=${HOST_CARD:-rpiaudio}
pcard=${PI_CARD:-UAC2Gadget}
format=${FORMAT:-S32_LE}   # must match GADGET_SSIZE: S32_LE for 4, S16_LE for 2
prio=${PI_PRIO:-}           # e.g. "sudo -n chrt -f 70": runs the Pi's aplay/arecord as realtime
tools=$(cd "$(dirname "$0")" && pwd)
out=$tools/../out/soak-$(date +%F-%H%M%S)-${ch}ch
mkdir -p "$out"
fmt="-t raw -f $format -c $ch -r 44100"

pi() { ssh -o BatchMode=yes "$host" "$@"; }
# Sum of the gadget controller's interrupt counters over all CPUs (dwc2 is fe980000.usb on a Pi 4).
dwc2_irqs() { pi "awk '/fe980000\\.usb/ { for (i = 2; i <= NF && \$i ~ /^[0-9]+\$/; i++) s += \$i } END { print s + 0 }' /proc/interrupts"; }

irq0=$(dwc2_irqs); t0=$(date +%s)

# Every player and recorder writes its xrun messages to its own log.
# Host side: play to the Pi for longer than the test, record from the Pi.
# shellcheck disable=SC2086
python3 "$tools/tonegen.py" -c "$ch" -f "$format" -s $((secs + 20)) |
  aplay -q -D "hw:CARD=$hcard" $fmt 2> "$out/host-aplay.log" &
# shellcheck disable=SC2086
arecord -q -D "hw:CARD=$hcard" $fmt -d $((secs + 10)) 2> "$out/host-arecord.log" |
  python3 "$tools/tonecheck.py" -c "$ch" -f "$format" --expect-order - > "$out/pi-to-host.txt" 2>&1 &
sleep 2

# Pi side: record what the host plays (analysed here), play tones to the host.
pi "$prio arecord -q -D hw:CARD=$pcard $fmt -d $secs" 2> "$out/pi-arecord.log" |
  python3 "$tools/tonecheck.py" -c "$ch" -f "$format" --expect-order - > "$out/host-to-pi.txt" 2>&1 &
pi "/usr/local/lib/rpi-audio/tonegen.py -c $ch -f $format -s $secs | $prio aplay -q -D hw:CARD=$pcard $fmt" \
  2> "$out/pi-aplay.log" &

sleep $((secs / 2))
pi 'uptime; top -b -n 1 -o %CPU | head -n 15' > "$out/pi-top.txt" 2>&1 || true
wait

irq1=$(dwc2_irqs); t1=$(date +%s)
{
  echo "soak: $ch ch, $format, $secs s, duplex, Pi priority: ${prio:-normal}, $(date -Is)"
  echo "dwc2 interrupts: $(( (irq1 - irq0) / (t1 - t0) ))/s"
  echo "Pi -> host: $(tail -n 1 "$out/pi-to-host.txt")"
  echo "host -> Pi: $(tail -n 1 "$out/host-to-pi.txt")"
  for f in host-aplay host-arecord pi-aplay pi-arecord; do
    if [[ -s $out/$f.log ]]; then echo "$f: $(tr '\n' ' ' < "$out/$f.log")"; fi
  done
} | tee "$out/summary.txt"
grep -q '^OK$' "$out/pi-to-host.txt" && grep -q '^OK$' "$out/host-to-pi.txt"
