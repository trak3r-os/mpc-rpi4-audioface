#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Installs, enables or disables the MPC Remote addin (jacob-sabella/mpc-addin-remote,
# MIT) on the Akai Force, and opens the SSH tunnel to it (docs/hosts/akai-force-remote.md).
#
#   tools/hosts/akai-force-remote/install.sh fetch
#   FORCE_HOST=root@force.local FORCE_PASS=... tools/hosts/akai-force-remote/install.sh enable|disable|status|tunnel
#
# fetch downloads the pinned release into out/ and checks its checksum. enable copies
# the addin to MockbaMod's SD card, the one place on the Force where writing is
# allowed (CLAUDE.md), next to a MockbaMod add-on script, instead of running the
# release's own installer (which writes to /data, /etc and the root filesystem).
# Like any add-on, it takes effect when MPC next starts. `enable` keeps an existing
# mpc_remote_addin.conf, so the addin keeps listening on 127.0.0.1 only. tunnel
# forwards localhost:6720 to it and stays in the foreground.

set -euo pipefail
cd "$(dirname "$0")"

version=1.0.3
zip=MPC-Remote-addin-$version-mpc-armv7.zip
url=https://github.com/jacob-sabella/mpc-addin-remote/releases/download/remote-addin-v$version/$zip
sha256=1a9fc7ebb37817f51249273e59320a8963c80d44c74e34db29bd0c29d1bee766
out=../../../out/mpc-remote-$version
pkg=$out/MPC-Remote-addin-$version

sd=/media/662522
dir=$sd/AddOns/mpcRemote
run=$sd/AddOns/run_mpcRemote.sh

fetch() {
	[[ -f $pkg/mpc_remote_addin.so ]] && return
	mkdir -p "$out"
	curl -fsSL -o "$out/$zip" "$url"
	echo "$sha256  $out/$zip" | sha256sum -c --quiet
	unzip -q -o "$out/$zip" -d "$out"
	(cd "$pkg" && sha256sum -c --quiet SHA256SUMS)
	echo "install: MPC Remote $version in $pkg, checksums OK"
}

case "${1:-}" in
fetch)
	fetch
	;;
enable)
	fetch
	. ../force-ssh.sh
	force_ssh "mkdir -p $dir"
	force_ssh "cat > $dir/mpc_remote_addin.so.new && mv $dir/mpc_remote_addin.so.new $dir/mpc_remote_addin.so" \
		< "$pkg/mpc_remote_addin.so"
	force_ssh "test -f $dir/mpc_remote_addin.conf || cat > $dir/mpc_remote_addin.conf" < "$pkg/mpc_remote_addin.conf"
	force_ssh "cat > $run && chmod 755 $run" < run_mpcRemote.sh
	echo "install: enabled; it takes effect when MPC next starts"
	;;
disable)
	. ../force-ssh.sh
	force_ssh "rm -f $run"
	echo "install: disabled; MPC runs without it after the Force restarts ($dir is kept)"
	;;
status)
	. ../force-ssh.sh
	force_ssh "ls -l $dir $run 2>&1; grep -E '^(bind|port|mcp)=' $dir/mpc_remote_addin.conf
		echo '--- LD_PRELOAD list for the next start:'; cat /dev/shm/.LD_PRELOAD 2>&1
		pid=\$(pidof MPC | cut -d' ' -f1)
		if [ -n \"\$pid\" ]; then
			echo '--- running MPC:'
			grep -c mpc_remote_addin /proc/\$pid/maps | sed 's/^/mapped: /'
			wget -qO- http://127.0.0.1:6720/info 2>&1; echo
		fi"
	;;
tunnel)
	. ../force-ssh.sh
	ssh "${ssh_opts[@]}" -N -L 6720:127.0.0.1:6720 "$host"   # not exec: force-ssh.sh cleans up on exit
	;;
*)
	echo "usage: $0 fetch|enable|disable|status|tunnel" >&2
	exit 2
	;;
esac
