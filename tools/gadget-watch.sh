#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Watch the gadget on the Pi while a host opens and runs its streams: one line
# every 0.25 s with the UDC state, the host's stream rates, the dwc2 interrupt
# rate, the Pi's PCM pointers and the dwc2 registers of the audio endpoints
# (debugfs, needs sudo). Kernel messages are interleaved as they come.
#
#   tools/gadget-watch.sh SECONDS > out/gadget-watch-$(date +%F-%H%M%S).txt
#
# With PLAY=CHANNELS:FORMAT (e.g. PLAY=26:S16_LE), tonegen plays into the
# gadget whenever the host has the Pi -> host stream open, as a real engine
# must: some hosts (the Akai Force) lose that stream when the Pi does not play.
# PI_HOST as for deploy.sh, PI_CARD (default UAC2Gadget) the gadget's card on the Pi.

set -euo pipefail

secs=${1:?usage: gadget-watch.sh SECONDS}
host=${PI_HOST:-no3z@192.168.1.106}
pcard=${PI_CARD:-UAC2Gadget}
play=${PLAY:-}

echo "# gadget-watch $(date -Is) seconds=$secs play=${play:-no}"

ssh -o BatchMode=yes "$host" "sudo -n env SECS=$secs CARD=$pcard PLAY=$play bash -s" <<'REMOTE'
dbg=/sys/kernel/debug/usb/fe980000.usb
end=$(( $(date +%s) + SECS ))
timeout "$SECS" dmesg -W -T 2>&1 | grep --line-buffered -iE 'dwc2|gadget|uac|u_audio|usb' | sed -u 's/^/kernel: /' &

rate() { amixer -c "$CARD" cget iface=PCM,name="$1 Rate" 2>/dev/null | sed -n 's/.*: values=//p'; }
irqs() { awk '/fe980000\.usb/ { for (i = 2; i <= NF && $i ~ /^[0-9]+$/; i++) s += $i } END { print s + 0 }' /proc/interrupts; }
ptr() { awk '/^closed/ {print "closed"; exit} /^state:/ {st=$2} /^hw_ptr/ {print st "@" $3}' "/proc/asound/$CARD/$1/sub0/status" 2>/dev/null; }
# DxEPCTL (with USBActEP, bit 15), DxEPINT and DxEPTSIZ of one endpoint, and its queued requests.
ep() {
  sed 's/, /\n/g; s/\t//g' "$dbg/$1" | awk -v d="$2" '
    index($0, d "EPCTL=") == 1 {c = $0}
    index($0, d "EPINT=") == 1 {i = $0}
    index($0, d "EPTSIZ=") == 1 {t = $0}
    q != "" && NF {q++}
    /^request list/ {q = 0}
    END {printf "%s %s %s q=%d", c, i, t, q}'
}

player=""
prev_irq=$(irqs)
while [ "$(date +%s)" -lt "$end" ]; do
  p=$(rate Playback) c=$(rate Capture)
  if [ -n "$player" ] && ! kill -0 "$player" 2>/dev/null; then
    player=""
    echo "player: stopped"
  fi
  if [ -n "$PLAY" ] && [ -z "$player" ] && [ -n "$p" ] && [ "$p" != 0 ]; then
    /usr/local/lib/rpi-audio/tonegen.py -c "${PLAY%%:*}" -f "${PLAY#*:}" -s "$SECS" |
      aplay -q -D "hw:CARD=$CARD" -t raw -f "${PLAY#*:}" -c "${PLAY%%:*}" -r 44100 2>&1 | sed -u 's/^/aplay: /' &
    player=$!
    echo "player: started"
  fi
  now_irq=$(irqs)
  printf '%s %s rate(c,p)=%s,%s irq/0.25s=%d pcm(c,p)=%s,%s | ep1in %s | ep1out %s | ep2in %s\n' \
    "$(date +%T.%N | cut -c1-12)" "$(cat /sys/class/udc/fe980000.usb/state)" "$c" "$p" \
    $(( now_irq - prev_irq )) "$(ptr pcm0c)" "$(ptr pcm0p)" \
    "$(ep ep1in DI)" "$(ep ep1out DO)" "$(ep ep2in DI)"
  prev_irq=$now_irq
  sleep 0.25
done
[ -n "$player" ] && pkill -f "aplay -q -D hw:CARD=$CARD" 2>/dev/null
wait 2>/dev/null
REMOTE
