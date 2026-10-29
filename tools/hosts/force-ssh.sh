# SPDX-License-Identifier: GPL-3.0-or-later
#
# Sourced by the tools/hosts/akai-force-* scripts: sets up `force_ssh`.
#
# FORCE_HOST is required. FORCE_PASS is optional: when set, ssh reads it through
# a temporary askpass helper that takes it from the environment, so it never
# lands in a file. Without it, ssh uses your key or asks interactively.

host="${FORCE_HOST:?set FORCE_HOST, e.g. root@force.local}"

ssh_opts=(-o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
if [[ -n "${FORCE_PASS:-}" ]]; then
  askdir="$(mktemp -d)"
  trap 'rm -f "$askdir/askpass"; rmdir "$askdir"' EXIT
  printf '#!/bin/sh\nprintf "%%s\\n" "$FORCE_PASS"\n' > "$askdir/askpass"
  chmod 700 "$askdir/askpass"
  export FORCE_PASS SSH_ASKPASS="$askdir/askpass" SSH_ASKPASS_REQUIRE=force
  ssh_opts+=(-o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive)
fi

force_ssh() { ssh "${ssh_opts[@]}" "$host" "$@"; }
