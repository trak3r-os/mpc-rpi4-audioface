#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Builds build/mpc_internal_io.so for the Akai Force in a Docker container and
# checks it only needs what the Force has (glibc <= 2.39, ARM EABI5 hard-float).
#
#   tools/hosts/akai-force-internal-io/build.sh

set -euo pipefail
cd "$(dirname "$0")"
image=rpi-audio-force-xbuild

docker build -q -t "$image" . >/dev/null
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/src" "$image" make so
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/src" "$image" sh -c '
  arm-linux-gnueabihf-readelf -h build/mpc_internal_io.so | grep -E "Class|Machine|Flags"
  echo "needs:"; arm-linux-gnueabihf-readelf -d build/mpc_internal_io.so | grep NEEDED
  echo "newest glibc symbol: $(arm-linux-gnueabihf-objdump -T build/mpc_internal_io.so | grep -o "GLIBC_[0-9.]*" | sort -uV | tail -n 1)"
  echo "exported:"; arm-linux-gnueabihf-objdump -T build/mpc_internal_io.so | awk "\$4 == \".text\" {print \"  \" \$NF}"'
