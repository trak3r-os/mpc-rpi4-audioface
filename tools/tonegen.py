#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Multichannel test tones for checking channel order and dropouts.

Channel k (counting from 1) carries a sine at k x 110 Hz at -12 dBFS. Integer
frequencies repeat exactly every second, so one second is computed and then
repeated without a seam. The output is raw interleaved PCM on stdout:

    tonegen.py -c 16 -s 600 | aplay -D hw:CARD=UAC2Gadget -t raw -f S32_LE -c 16 -r 44100

Standard library only: it runs on the Pi as well as on a laptop.
"""

import argparse
import array
import math
import sys

BASE_HZ = 110
LEVEL = 0.25  # -12 dBFS

FORMATS = {"S16_LE": ("h", 16), "S32_LE": ("i", 32)}


def tone_frequencies(channels, base=BASE_HZ):
    """The tone of each channel, in Hz: channel k carries k x base."""
    return [base * (k + 1) for k in range(channels)]


def one_second(channels, rate, fmt):
    """One second of interleaved little-endian PCM; it loops without a seam."""
    typecode, bits = FORMATS[fmt]
    full = (1 << (bits - 1)) - 1
    steps = [2 * math.pi * f / rate for f in tone_frequencies(channels)]
    samples = array.array(typecode)
    assert samples.itemsize * 8 == bits
    for n in range(rate):
        samples.extend(round(LEVEL * full * math.sin(w * n)) for w in steps)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-c", "--channels", type=int, required=True)
    p.add_argument("-r", "--rate", type=int, default=44100)
    p.add_argument("-f", "--format", choices=sorted(FORMATS), default="S32_LE")
    p.add_argument("-s", "--seconds", type=int, default=0, help="0 = until the reader stops")
    args = p.parse_args()

    highest = tone_frequencies(args.channels)[-1]
    if highest >= args.rate / 2:
        p.error(f"{args.channels} channels need {highest} Hz, above Nyquist at {args.rate} Hz")
    block = one_second(args.channels, args.rate, args.format)
    out = sys.stdout.buffer
    try:
        n = 0
        while args.seconds == 0 or n < args.seconds:
            out.write(block)
            n += 1
        out.flush()
    except BrokenPipeError:
        pass  # the reader (aplay) stopped: that ends the test


if __name__ == "__main__":
    main()
