#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lights the SH1106 OLED (I2C bus 1, address 0x3C) and draws a pattern that shows if the picture is turned
or mirrored: a frame, a big F in the top-left corner, a filled triangle in the bottom-right one and a
diagonal. Runs on the Pi, next to bridge/rpi-audio-ui/sh1106.py.

  oled-test.py [--flip] [--hold SECONDS] [--address 0x3C] [--bus 1]"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audio-ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sh1106  # noqa: E402


def pattern():
    c = sh1106.Canvas()
    c.rect(0, 0, 127, 63)
    c.rect(3, 3, 124, 60)
    c.rect(10, 8, 14, 38, fill=True)       # the F: stem, top bar, middle bar
    c.rect(10, 8, 30, 12, fill=True)
    c.rect(10, 21, 24, 25, fill=True)
    for row in range(14):                  # the triangle, right angle in the corner
        c.rect(120 - row * 2, 56 - row, 120, 56 - row, fill=True)
    c.line(34, 58, 90, 14)
    for x in range(40, 100, 6):            # ticks along the top, to see the left-right direction
        c.rect(x, 6, x, 6 + (x - 40) // 6, fill=True)
    return c


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--flip", action="store_true", help="turn the picture 180 degrees")
    p.add_argument("--hold", type=float, default=8.0)
    p.add_argument("--address", type=lambda v: int(v, 0), default=0x3C)
    p.add_argument("--bus", type=int, default=1)
    args = p.parse_args()
    link = sh1106.I2C(args.bus, args.address)
    screen = sh1106.Display(link, flip=args.flip)
    screen.all_on()
    print("every pixel on for 1.5 s")
    time.sleep(1.5)
    screen.all_on(False)
    screen.show(pattern())
    print(f"pattern for {args.hold:g} s: frame, F top-left, triangle bottom-right")
    time.sleep(args.hold)
    blank = sh1106.Canvas()
    screen.show(blank)
    print("cleared")


if __name__ == "__main__":
    main()
