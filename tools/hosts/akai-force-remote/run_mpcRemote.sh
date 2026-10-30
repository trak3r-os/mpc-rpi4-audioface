#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
#
# MockbaMod add-on script (rpi-audio): adds the MPC Remote addin to MPC's
# LD_PRELOAD (docs/hosts/akai-force-remote.md). It is enabled while this file
# sits in AddOns/, and takes effect the next time MPC starts. The list handling
# is the same as in run_mpcInternalIO.sh, which explains it: MockbaMod's add-on
# scripts race for that list.

# shellcheck disable=SC2154  # mmLD_PRELOAD_VAR comes from MockbaMod's env.sh, which is on the device
mmPath=$(cat /dev/shm/.mmPath)
# shellcheck source=/dev/null
. "$mmPath/MockbaMod/env.sh"

LD_LIB="$mmPath/AddOns/mpcRemote/mpc_remote_addin.so"

# Nothing runs in the background after the first 5 s, so there is nothing to kill.
[ "$1" = "kill" ] && exit 0

# The library of every enabled add-on: each AddOns/run_*.sh sets LD_LIB.
enabled=
for s in "$mmPath"/AddOns/run_*.sh; do
	line=$(sed -n '/^LD_LIB=/{p;q}' "$s")
	[ -n "$line" ] && enabled="$enabled $(eval "$line"; echo "$LD_LIB")"
done

seen="$LD_LIB"
i=0
while [ $i -lt 50 ]; do
	now=$(cat "$mmLD_PRELOAD_VAR" 2>/dev/null)
	# The other scripts write once, as soon as they start. From 0.3 s on, an enabled
	# add-on's library still missing was dropped by a rewrite: put it back at the end.
	extra=
	[ $i -ge 3 ] && extra=$enabled
	list=
	for f in $now $seen $extra; do
		[ -f "$f" ] || continue
		case " $list " in
		*" $f "*) ;;
		*) list="${list:+$list }$f" ;;
		esac
	done
	seen=$list
	[ "$now" = "$list" ] || echo "$list" >"$mmLD_PRELOAD_VAR"
	sleep 0.1
	i=$((i + 1))
done
