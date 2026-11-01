#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prints what the encoder and the three buttons do: the raw edges of each line and the events the panel logic makes
of them. Runs on the Pi, next to bridge/rpi-audio-ui/inputs.py (the service must not be using the lines).

  panel-test.py [--seconds N] [--invert]"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audio-ui"))
import inputs  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--seconds", type=float, default=30.0)
    p.add_argument("--invert", action="store_true", help="swap the encoder's direction")
    args = p.parse_args()
    reader, panel = inputs.GpioReader(), inputs.Panel(invert=args.invert)
    panel.sync(reader.levels())
    print("levels at start:", " ".join(f"{n}={v}" for n, v in panel.level.items()), flush=True)
    end = time.monotonic() + args.seconds
    counts = {}
    while (left := end - time.monotonic()) > 0:
        for name, level in reader.read(min(left, 0.5)):
            events = panel.edge(name, level, time.monotonic())
            for event in events:
                counts[event] = counts.get(event, 0) + 1
            stamp = time.monotonic() - end + args.seconds
            print(f"{stamp:6.2f}s  {name:7} -> {level}" + (f"   EVENT {events}" if events else ""), flush=True)
    reader.close()
    print("events:", counts or "none")


if __name__ == "__main__":
    main()
