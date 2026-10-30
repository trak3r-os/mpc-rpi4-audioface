#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Package the armhf build for sd88me's installer: dist/<zip> and the unpacked dist/rpi-audio-Panel-<version>/ with
# install.sh, uninstall.sh and portable/'rpi-audio - VST - rpi-audio Panel'/ (the .so, plugin-meta.xml, version.xml,
# Plugin Skins/, panel.conf, notices/). Run build.sh arm first.
set -euo pipefail
cd "$(dirname "$0")"
SO=build/arm/rpi_audio_panel.so
[[ -f $SO ]] || { echo 'Run build.sh arm first' >&2; exit 1; }
python3 skin.py build >/dev/null
FOLDER="build/skin/rpi-audio - VST - rpi-audio Panel"
V="$(python3 -c 'import json; v = json.load(open("vst.json"))["version"]; print("%d.%d.%d" % (v // 1000, v % 1000 // 100, v % 100))')"

rm -rf build/notices dist
mkdir -p build/notices dist
cp ../../../LICENSE build/notices/LICENSE-GPL-3.0
cp vendor/mpc-vst-plugins/LICENSE build/notices/LICENSE-mpc-vst-plugins-MIT.txt
cp fonts/OFL.txt build/notices/OFL-TitilliumWeb.txt
cp ../../../THIRD_PARTY.md build/notices/THIRD_PARTY.md

python3 vendor/mpc-vst-plugins/tools/release.py \
  --so "$SO" --skin "$FOLDER" --entry build/pluginlist-entry.xml --version "$V" \
  --id rpi-audio-panel --repo trak3r-os/mpc-rpi4-audioface --license GPL-3.0-or-later \
  --about 'Shows and controls an rpi-audio hub (USB audio and MIDI hub on a Raspberry Pi) from the touchscreen.' \
  --extra panel.conf:panel.conf --user-data panel.conf --extra build/notices:notices \
  -o dist

python3 - "dist/rpi-audio-Panel-$V-mpc-armv7.zip" dist <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY
chmod +x "dist/rpi-audio-Panel-$V/install.sh" "dist/rpi-audio-Panel-$V/uninstall.sh"
echo "Installable folder: dist/rpi-audio-Panel-$V/portable/rpi-audio - VST - rpi-audio Panel/"
(cd "dist/rpi-audio-Panel-$V" && sha256sum -c SHA256SUMS | grep -vc ': OK$' || true) | sed 's/^/files failing the checksum: /'
