#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sends an rpi-audiod command over the gadget's MIDI control port and prints the reply.

  tools/midictl.py [--port hw:rpiaudio,0,0] [--wait SECONDS] COMMAND...

Runs on a Linux USB host with alsa-utils (amidi). The port is the host's rawmidi device for
the gadget's control port (port 1 is subdevice 0). Commands and replies: docs/MIDI.md, e.g.
`tools/midictl.py ping` or `tools/midictl.py status`.
"""

import argparse
import json
import re
import subprocess
import sys

HEAD = bytes([0xF0, 0x7D, 0x52, 0x41])    # a command
REPLY = bytes([0xF0, 0x7D, 0x52, 0x42])   # a reply


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--port", default="hw:rpiaudio,0,0")
    p.add_argument("--wait", type=float, default=1.0, help="seconds to wait for the reply")
    p.add_argument("command", nargs="+")
    args = p.parse_args()
    text = " ".join(args.command)
    if not all(0x20 <= ord(c) <= 0x7E for c in text):
        sys.exit("midictl: the command must be plain ASCII")
    msg = " ".join(f"{b:02X}" for b in HEAD + text.encode() + b"\xF7")
    out = subprocess.run(["amidi", "-p", args.port, "-S", msg, "-d", "-t", str(args.wait)],
                         capture_output=True, text=True)
    data = bytes(int(h, 16) for h in re.findall(r"\b[0-9A-F]{2}\b", out.stdout))
    replies = [m[len(REPLY):-1].decode("ascii", "replace")
               for m in re.findall(rb"\xF0\x7D\x52\x42[\x20-\x7E]*\xF7", data)]
    if not replies:
        why = f" ({out.stderr.strip()})" if out.stderr.strip() else ""
        sys.exit(f"midictl: no reply on {args.port} within {args.wait} s{why}")
    for r in replies:
        if r.startswith("{"):
            print(json.dumps(json.loads(r), indent=1, sort_keys=True))
        else:
            print(r)
    sys.exit(1 if any(r.startswith("error") for r in replies) else 0)


if __name__ == "__main__":
    main()
