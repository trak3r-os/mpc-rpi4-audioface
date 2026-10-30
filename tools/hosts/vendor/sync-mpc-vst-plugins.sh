#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Refresh the vendored copy of sd88me/mpc-vst-plugins (MIT) from a checkout of upstream, unmodified.
# The rpi-audio Panel builds on its VST2 wrapper and packages with release.py; the internal I/O add-on packages with
# release_addin.py.
#
#   tools/hosts/vendor/sync-mpc-vst-plugins.sh [UPSTREAM_CHECKOUT]
#
# Without an argument it clones upstream's default branch into a temporary folder. It records the commit in
# VENDORED.md; review the diff, rebuild the panel (build.sh all) and run its tests before committing.

set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dst=$here/mpc-vst-plugins
url=https://github.com/sd88me/mpc-vst-plugins.git
files=(
  LICENSE
  wrapper/engine.h wrapper/plugin_dir.h wrapper/popup.h wrapper/vst2_wrap.c
  tools/gen_vst.py tools/params.py tools/release.py tools/release_addin.py tools/catalog_check.py
  tools/skin_compat.py tools/skin_roles_2x.json
  tools/release/install.sh tools/release/uninstall.sh tools/release/plugin_list.awk
  tools/release/addin/install.sh tools/release/addin/uninstall.sh tools/release/addin/addin-lib.sh
)

src=${1:-}
if [[ -z $src ]]; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  git clone -q --depth 1 "$url" "$tmp/up"
  src=$tmp/up
fi
commit=$(git -C "$src" rev-parse HEAD)
date=$(git -C "$src" log -1 --format=%cs)

for f in "${files[@]}"; do [[ -f $src/$f ]] || { echo "sync: upstream has no $f" >&2; exit 1; }; done
find "$dst" -mindepth 1 -maxdepth 1 ! -name VENDORED.md -exec rm -rf {} +
for f in "${files[@]}"; do install -D -m "$(stat -c %a "$src/$f")" "$src/$f" "$dst/$f"; done

cat > "$dst/VENDORED.md" <<EOF
# Vendored: sd88me/mpc-vst-plugins (MIT)

Upstream: $url, commit \`$commit\` ($date).
Copied unmodified by \`tools/hosts/vendor/sync-mpc-vst-plugins.sh\`; run it again to update. Nothing here is edited
by hand.

Files: $(printf '`%s` ' "${files[@]}")

Used by \`tools/hosts/akai-force-panel/\` (the VST2 wrapper, \`gen_vst.py\`, \`release.py\`) and
\`tools/hosts/akai-force-internal-io/\` (\`release_addin.py\` and the shared addin installer).
EOF
echo "sync: $dst at ${commit:0:7} ($date)"
