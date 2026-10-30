#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The gadget's audio core (u_audio) with u_audio-idle-silence.patch, built on the Pi against its own kernel headers.
#
#   tools/kernel/u_audio/build.sh build    fetch the pinned sources, check them, patch, build build/u_audio.ko
#   sudo tools/kernel/u_audio/build.sh load     use the patched module until the next reboot
#   sudo tools/kernel/u_audio/build.sh unload   back to the kernel's own module
#   tools/kernel/u_audio/build.sh status   which one is loaded
#
# load and unload stop rpi-audiod and the gadget, swap the module and start them again: one rebind, and the host
# sees the device go away and come back. Nothing is installed: a reboot always comes back with the kernel's module.
# The sources are raspberrypi/linux at a fixed commit (rpi-6.18.y); build refuses a kernel that is not 6.18.

set -euo pipefail
cd "$(dirname "$0")"
COMMIT=4e747c864a88537e18b1ffc19a1954c9686bb8e1
BASE=https://raw.githubusercontent.com/raspberrypi/linux/$COMMIT/drivers/usb/gadget/function
SOURCES="u_audio.c:effa3bb5414e660532c21f4e44082c2b9311054f401760be0ef677671c4a2c5b
u_audio.h:a40d04b8e8d9573303af8d1b0dbbb13c141f15b0b64bfd3666273cbd60293c11
uac_common.h:0d268a8c31c61302bfdf2a9708b657a097371d22c0ec3aad3d2fc03f6bf2fab4"
KO=build/u_audio.ko

die() { echo "u_audio: $*" >&2; exit 1; }

build() {
  local kver src=build/src name sum
  kver=$(uname -r)
  [[ $kver == 6.18.* ]] || die "the sources are for 6.18; this kernel is $kver"
  [[ -d /lib/modules/$kver/build ]] || die "no headers for $kver (linux-headers-rpi-v8 or -2712)"
  rm -rf build && mkdir -p "$src"
  while IFS=: read -r name sum; do
    curl -fsSL -o "$src/$name" "$BASE/$name"
    echo "$sum  $src/$name" | sha256sum -c --quiet - || die "$name is not the expected file"
  done <<<"$SOURCES"
  patch -s -d "$src" -p5 < u_audio-idle-silence.patch
  echo 'obj-m := u_audio.o' > "$src/Kbuild"
  make -s -C "/lib/modules/$kver/build" M="$PWD/$src" modules
  cp "$src/u_audio.ko" "$KO"
  echo "u_audio: built $KO for $kver (srcversion $(/sbin/modinfo -F srcversion "$KO"))"
}

swap() {   # swap MODULE_PATH|stock
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "run as root"
  local was=0
  systemctl is-active --quiet rpi-audiod && was=1
  systemctl stop rpi-audiod rpi-audio-gadget
  modprobe -r usb_f_uac2 u_audio
  if [[ $1 == stock ]]; then modprobe u_audio; else insmod "$1"; fi
  systemctl start rpi-audio-gadget
  if ((was)); then systemctl start rpi-audiod; fi
  status
}

status() {
  local loaded mine=""
  loaded=$(cat /sys/module/u_audio/srcversion 2>/dev/null || echo "not loaded")
  [[ -f $KO ]] && mine=$(/sbin/modinfo -F srcversion "$KO")
  if [[ $loaded == "$mine" ]]; then
    echo "u_audio: the patched module is loaded ($loaded)"
  else
    echo "u_audio: srcversion $loaded (the kernel's own, or another build)"
  fi
}

case "${1:-}" in
  build) build ;;
  load) [[ -f $KO ]] || die "build it first"; swap "$PWD/$KO" ;;
  unload) swap stock ;;
  status) status ;;
  *) echo "usage: $0 build|load|unload|status" >&2; exit 2 ;;
esac
