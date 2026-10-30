#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Read-only diagnostics of the Akai Force over SSH: what the Force sees on
# USB and ALSA, which hw_params MPC chose, and how MPC and the internal codec
# are set up (threads, preloads, clocks). Nothing is written on the Force.
#
# Usage:
#   FORCE_HOST=root@force.local [FORCE_PASS=...] tools/hosts/akai-force-probe.sh > out/force-probe-$(date +%F-%H%M%S).txt
#
# FORCE_PASS: see force-ssh.sh.
# GADGET_VIDPID (default 1d6b:0104) selects the device for `lsusb -v`.

set -euo pipefail

# shellcheck source=force-ssh.sh
. "$(dirname "$0")/force-ssh.sh"
gadget="${GADGET_VIDPID:-1d6b:0104}"

echo "# force-probe $(date -Is) host=${host#*@}"

# The remote side is plain POSIX sh and only reads.
force_ssh "GADGET=$gadget sh -s" <<'REMOTE'
section() { printf '\n## %s\n' "$1"; }

section "uname";      uname -a
section "os-release"; cat /etc/os-release 2>/dev/null
section "uptime";     uptime

section "/proc/asound/cards"; cat /proc/asound/cards
for c in /proc/asound/card[0-9]*; do
  [ -d "$c" ] || continue
  section "$c ($(cat "$c/id" 2>/dev/null))"
  for f in "$c"/usbid "$c"/usbbus "$c"/stream*; do
    [ -f "$f" ] && { printf '### %s\n' "$f"; cat "$f"; }
  done
  for s in "$c"/pcm*/sub*; do
    [ -d "$s" ] || continue
    for f in hw_params sw_params status; do
      printf '### %s/%s\n' "$s" "$f"; cat "$s/$f" 2>/dev/null
    done
  done
done

section "lsusb";   lsusb 2>/dev/null || echo "(no lsusb)"
section "lsusb -t"; lsusb -t 2>/dev/null || true
section "lsusb -v $GADGET"; lsusb -v -d "$GADGET" 2>/dev/null || echo "(gadget not present or no lsusb)"

section "MPC audio lines (this boot)"
journalctl -b --no-pager 2>/dev/null | grep -E '\*\*\*\*|[Aa]udio|ALSA|hw:' | tail -n 150

section "kernel: usb / snd"
dmesg 2>/dev/null | grep -iE 'usb|snd|audio' | tail -n 150

section "processes"
ps 2>/dev/null | grep -iE 'mpc|az01|acv' | grep -v grep | head -n 20

# How MPC and the internal codec are set up. BusyBox: always `head -n N`.
section "boot: cpu isolation"
tr ' ' '\n' < /proc/cmdline | grep -E '^(isolcpus|nohz_full|rcu_nocbs|irqaffinity)='

section "device tree: sound"
printf 'product-code: %s\n' "$(tr -d '\0' < /sys/firmware/devicetree/base/inmusic,product-code 2>/dev/null)"
for n in sound sound-codec; do
  [ -r "/proc/device-tree/$n/compatible" ] && printf '%s: %s\n' "$n" "$(tr '\0' ' ' < "/proc/device-tree/$n/compatible")"
done

section "/dev/snd/by-path"; ls -l /dev/snd/by-path 2>&1
section "/etc/asound.conf"; cat /etc/asound.conf 2>/dev/null || echo "(none)"

section "kernel config: audio and USB gadget"
zcat /proc/config.gz 2>/dev/null | grep -E 'SND_ALOOP|SND_USB_AUDIO=|INMUSIC|USB_DWC2_(HOST|PERIPHERAL|DUAL_ROLE)|USB_CONFIGFS_F_(UAC|MIDI)'

# Read only if debugfs is already mounted; never mount it.
section "clocks: I2S master clock and its sources"
if [ -r /sys/kernel/debug/clk/clk_summary ]; then
  grep -E 'xin24m|cpll|i2s|otgphy[0-9]_480m' /sys/kernel/debug/clk/clk_summary | head -n 20
else
  echo "(debugfs not mounted)"
fi

section "MPC version"
for f in /usr/share/Akai/*/VERSION; do [ -r "$f" ] && printf '%s: %s\n' "$f" "$(cat "$f")"; done
grep -a -o -E '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+ \([0-9a-f]{7,}\)' /usr/bin/MPC | head -n 1

pid=$(pidof MPC | cut -d' ' -f1)
if [ -n "$pid" ]; then

  section "MPC LD_PRELOAD"
  tr '\0' '\n' < "/proc/$pid/environ" | grep '^LD_PRELOAD='

  section "MPC open sound devices"
  ls -l "/proc/$pid/fd" 2>/dev/null | grep -o '/dev/snd/.*' | sort -u

  section "MPC real-time threads"
  for t in /proc/"$pid"/task/*; do
    # Fields after "pid (comm) ": 37 = last cpu, 38 = rt priority, 39 = policy.
    set -- $(sed 's/^.*) //' "$t/stat" | awk '{print $39, $38, $37}')
    case "$1" in 1) pol=FIFO ;; 2) pol=RR ;; *) continue ;; esac
    printf '%-16s %s %s, %s\n' "$(cat "$t/comm")" "$pol" "$2" "$(grep Cpus_allowed_list "$t/status" | tr -d '\t')"
  done

  section "MPC ALSA PCM symbols"
  grep -a -o 'snd_pcm_[a-z_0-9]*' /usr/bin/MPC | sort -u | tr '\n' ' '; echo
fi

# MockbaMod: an add-on is enabled when its run_<name>.sh is in AddOns/.
section "add-ons"
ls /media/*/boot.sh 2>/dev/null; ls -d /media/*/AddOns/* 2>/dev/null
REMOTE
