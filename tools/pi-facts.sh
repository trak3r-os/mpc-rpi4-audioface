#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Read-only inventory of the Pi: board, kernel, USB topology and TTs, ALSA,
# the gadget's state, CPU settings. Nothing is changed and no sudo is needed.
#
#   PI_HOST=no3z@192.168.1.106 tools/pi-facts.sh > out/pi-facts-$(date +%F-%H%M%S).txt

set -euo pipefail

host="${PI_HOST:-no3z@192.168.1.106}"
echo "# pi-facts $(date -Is) host=${host#*@}"

ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" 'sh -s' <<'REMOTE'
section() { printf '\n## %s\n' "$1"; }
export PATH="$PATH:/usr/sbin:/sbin"

section "board";   tr -d '\0' < /proc/device-tree/model; echo; free -h | head -2
section "os";      . /etc/os-release && echo "$PRETTY_NAME"; uname -a
section "power";   vcgencmd get_throttled 2>/dev/null; vcgencmd measure_temp 2>/dev/null
section "cpu";     cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
section "bootloader / VL805"; rpi-eeprom-update 2>&1 | grep -E 'BOOTLOADER|CURRENT|LATEST|VL805'
section "config.txt (non-comment)"; grep -vE '^\s*(#|$)' /boot/firmware/config.txt
section "cmdline";  cat /boot/firmware/cmdline.txt
section "kernel options"
# "is not set" lines matter too: without DYNAMIC_DEBUG the dwc2/u_audio iso errors cannot be enabled.
grep -E 'CONFIG_(PREEMPT|PREEMPT_RT|DYNAMIC_DEBUG|USB_CONFIGFS_F_UAC2|USB_CONFIGFS_F_MIDI|HZ)[= ]' \
  "/boot/config-$(uname -r)" 2>/dev/null
section "udc"
for u in /sys/class/udc/*; do [ -e "$u" ] && echo "${u##*/}: $(cat "$u/state")"; done
ls /sys/kernel/config/usb_gadget/ 2>/dev/null || echo "(no gadgets / configfs not loaded)"
section "modules"; lsmod | grep -E 'libcomposite|usb_f_|u_audio|snd_usb_audio|dwc2' || echo "(none loaded)"
section "lsusb";    lsusb
section "lsusb -t"; lsusb -t
section "hubs: transaction translators"
lsusb | awk '/[Hh]ub/ {print $6}' | sort -u | while read -r id; do
  printf '%s: ' "$id"; lsusb -v -d "$id" 2>/dev/null | grep -m1 bDeviceProtocol
done
section "ALSA cards"; cat /proc/asound/cards
section "audio packages"
dpkg-query -W -f='${Package} ${Version}\n' jackd2 zita-ajbridge pipewire wireplumber \
  python3-jack-client python3-pyudev alsa-utils 2>/dev/null
section "realtime limits (this user)"; ulimit -r; ulimit -l
section "rpi-audio"
systemctl is-enabled rpi-audio-gadget.service 2>/dev/null; systemctl is-active rpi-audio-gadget.service 2>/dev/null
if [ -r /etc/rpi-audio/gadget.env ]; then grep -v '^#' /etc/rpi-audio/gadget.env; else echo "(not installed)"; fi
REMOTE
