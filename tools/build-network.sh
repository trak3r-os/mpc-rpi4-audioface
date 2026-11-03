#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build RTP and, by default, Link Audio. The SDK is pinned and kept in the ignored out/ directory.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
build="$root/out/network"
sdk="${RPI_LINK_DIR:-$root/out/ableton-link}"
revision=5ba907ae027a8c2ec8824463e37296dcefc5e9be
mkdir -p "$build"
link=1
if [[ ${1:-} == --rtp-only ]]; then link=0; fi
flags=()
if ((link)); then
  if [[ ! -d $sdk/.git ]]; then
    git clone --no-checkout https://github.com/Ableton/link.git "$sdk"
    git -c safe.directory="$sdk" -C "$sdk" checkout "$revision"
    git -c safe.directory="$sdk" -C "$sdk" submodule update --init --recursive
  fi
  [[ $(git -c safe.directory="$sdk" -C "$sdk" rev-parse HEAD) == "$revision" ]] || {
    echo "build-network: SDK must be at $revision (set RPI_LINK_DIR to a matching checkout)" >&2
    exit 1
  }
  flags=(-DWITH_LINK -DLINK_PLATFORM_LINUX=1 -DLINK_PLATFORM_UNIX=1 -DASIO_STANDALONE
         -isystem "$sdk/include" -isystem "$sdk/modules/asio-standalone/asio/include")
fi
# GCC diagnoses moves of the SDK's partially-filled byte buffer; retain that warning without failing the build.
g++ -std=c++17 -O2 -Wall -Wextra -Werror -Wno-error=uninitialized -Wno-error=maybe-uninitialized \
  "${flags[@]}" "$root/bridge/network/network.cpp" \
  -ljack -pthread -latomic -o "$build/rpi-audio-network"
"$build/rpi-audio-network" --capabilities > "$build/capabilities.json"
if ((link)); then
  cp "$sdk/LICENSE.md" "$sdk/GNU-GPL-v2.0.md" "$build/"
fi
echo "build-network: $build/rpi-audio-network"
