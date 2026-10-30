#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Installs, enables or disables the mpc_internal_io add-on on the Akai Force.
#
#   FORCE_HOST=root@force.local FORCE_PASS=... tools/hosts/akai-force-internal-io/install.sh enable|disable|status
#   FORCE_HOST=root@force.local FORCE_PASS=... tools/hosts/akai-force-internal-io/install.sh conf FILE
#
# It writes only under /media/662522, MockbaMod's SD card: the one place on the
# Force where writing is allowed (CLAUDE.md). Never use it while a test runs.
# MPC reads LD_PRELOAD when it starts, and MockbaMod rebuilds that list in RAM
# (/dev/shm/.LD_PRELOAD) at every boot, so enable and disable take effect at
# the Force's next restart. `enable` keeps an existing mpc_internal_io.conf;
# `conf FILE` replaces it, and MPC reads it the next time it starts.

set -euo pipefail
cd "$(dirname "$0")"
. ../force-ssh.sh

sd=/media/662522
dir=$sd/AddOns/mpcInternalIO
run=$sd/AddOns/run_mpcInternalIO.sh

case "${1:-}" in
enable)
	[[ -f build/mpc_internal_io.so ]] || { echo "install: build it first (./build.sh)" >&2; exit 1; }
	force_ssh "mkdir -p $dir"
	force_ssh "cat > $dir/mpc_internal_io.so.new && mv $dir/mpc_internal_io.so.new $dir/mpc_internal_io.so" \
		< build/mpc_internal_io.so
	force_ssh "test -f $dir/mpc_internal_io.conf || cat > $dir/mpc_internal_io.conf" < mpc_internal_io.conf
	force_ssh "cat > $run && chmod 755 $run" < run_mpcInternalIO.sh
	echo "install: enabled; it takes effect when the Force restarts"
	;;
conf)
	[[ -f "${2:-}" ]] || { echo "usage: $0 conf FILE" >&2; exit 2; }
	force_ssh "cat > $dir/mpc_internal_io.conf.new && mv $dir/mpc_internal_io.conf.new $dir/mpc_internal_io.conf" < "$2"
	echo "install: settings replaced; MPC reads them the next time it starts"
	;;
disable)
	force_ssh "rm -f $run"
	echo "install: disabled; MPC runs without it after the Force restarts ($dir is kept)"
	;;
status)
	force_ssh "ls -l $dir $run 2>&1
		echo '--- LD_PRELOAD list for the next start:'; cat /dev/shm/.LD_PRELOAD 2>&1
		pid=\$(pidof MPC | cut -d' ' -f1)
		if [ -n \"\$pid\" ]; then
			echo '--- running MPC:'
			grep -c mpc_internal_io /proc/\$pid/maps | sed 's/^/mapped: /'
			journalctl -b --no-pager 2>/dev/null | grep mpc_internal_io | tail -n 8
		fi"
	;;
*)
	echo "usage: $0 enable|disable|status|conf FILE" >&2
	exit 2
	;;
esac
