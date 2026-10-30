#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
#
# MockbaMod add-on script (rpi-audio): adds mpc_internal_io.so to MPC's
# LD_PRELOAD, so the Force keeps its own audio I/O while MPC uses the rpi-audio
# gadget. It is enabled while this file sits in AddOns/, and takes effect the
# next time MPC starts.
#
# MockbaMod's boot.sh starts every AddOns/*.sh at once, and each one rewrites
# the list in $mmLD_PRELOAD_VAR without a lock, so they can overwrite one
# another. On 2026-10-29 that left MidiLoop's library as a broken path (MPC lost
# its control surface), and on another boot this script started too late for a
# fixed delay. So for the first 5 s it checks the list every 0.1 s, and rewrites
# it only when it needs it: one path per library that exists, every library
# seen in the list since this script started, no duplicates. boot.sh reads the
# list after remounter.sh and a 1 s sleep; the other scripts write once, as soon
# as they start. Our own rewrites can drop an entry another script writes in
# between (on 2026-10-30 MidiLoop's, and MPC started without its control
# surface), so from 0.3 s on it also puts back the library of every enabled
# add-on, read from the LD_LIB line of its AddOns/run_*.sh.

mmPath=$(cat /dev/shm/.mmPath)
. "$mmPath/MockbaMod/env.sh"

LD_LIB="$mmPath/AddOns/mpcInternalIO/mpc_internal_io.so"

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
