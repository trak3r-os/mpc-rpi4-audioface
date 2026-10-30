#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Package the add-on as an sd88me addin zip (dist/rpi-audio-Internal-IO-<version>-mpc-armv7.zip): its shared installer
# puts it in /data/mpc-addins/rpi-audio-internal-io/ and adds it to MPC's LD_PRELOAD, MockbaMod's list included. Run
# build.sh first. Checks the zip with sd88me's catalog_check.py.
#
#   tools/hosts/akai-force-internal-io/package.sh VERSION

set -euo pipefail
cd "$(dirname "$0")"
version=${1:?usage: $0 VERSION (X.Y.Z)}
tools=../vendor/mpc-vst-plugins/tools
[[ -f build/mpc_internal_io.so ]] || { echo "package: build it first (./build.sh)" >&2; exit 1; }

stage=build/addin
rm -rf "$stage" dist
mkdir -p "$stage"
cp addin.manifest build/mpc_internal_io.so mpc_internal_io.conf "$stage/"
cp ../../../LICENSE "$stage/LICENSE"
python3 "$tools/release_addin.py" --dir "$stage" --version "$version" \
  --repo trak3r-os/mpc-rpi4-audioface --license GPL-3.0-or-later \
  --about 'Keeps the device'"'"'s own audio inputs and outputs working while MPC uses an rpi-audio hub (USB audio and MIDI hub on a Raspberry Pi) as its audio interface.' \
  --requires 'An rpi-audio hub on the USB host port, chosen as the audio device in MPC. Tested on the Akai Force (MPC 3.9).' \
  -o dist
python3 "$tools/catalog_check.py" dist/*.zip --catalog
