#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Summarise a usbmon text capture of the rpi-audio gadget, as seen from the host (tools/hosts/akai-force-usbmon.sh).

  tools/usbmon-check.py [--framesize 52] [--all] FILE...

One line per second of capture, or only the seconds with something odd unless --all: frames per second each way
(the gadget's IN data endpoint and the host's OUT), iso packets with an error status or a size that is not a whole
frame count, the longest gap between two completed IN URBs, the feedback value, and MIDI bytes each way. The last
line says where the audio stopped, if it did. Usbmon's microsecond clock is not wall time: files are cut per minute
of wall time by the capture script, which is how to find the right one.
"""
import argparse
import collections
import sys

WRAP = 1 << 32


def parse(lines):
    """Yields (t_us, kind, endpoint, fields) for completions (C lines) of iso and bulk URBs."""
    last, base = None, 0
    for line in lines:
        f = line.split()
        if len(f) < 5 or f[2] != "C":
            continue
        t = int(f[1])
        if last is not None and t + base < last - WRAP // 2:
            base += WRAP
        t += base
        last = t
        kind, _bus, _dev, ep = f[3].split(":")
        yield t, kind, int(ep), f[4:]


def iso_packets(fields):
    """From 'status:interval:start:errors N s:o:l ...' -> (errors, [(status, length)])."""
    errors = int(fields[0].split(":")[3]) if fields[0].count(":") == 3 else 0
    n = int(fields[1])
    pk = []
    for d in fields[2:2 + n]:
        s, _o, ln = d.split(":")
        pk.append((int(s), int(ln)))
    return errors, pk


def feedback_value(fields):
    """The 4-byte high-speed feedback as sent, 16.16 fixed point: frames per data packet interval as the gadget
    computes it (11.025 for 44100 Hz at bInterval 2)."""
    try:
        data = fields[fields.index("=") + 1]
    except (ValueError, IndexError):
        return None
    return int.from_bytes(bytes.fromhex(data[:8]), "little") / 65536


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--framesize", type=int, default=52, help="bytes per frame: channels x bytes per sample (26 x 2)")
    ap.add_argument("--all", action="store_true", help="print every second, not only the odd ones")
    a = ap.parse_args()

    def lines():
        for name in a.files:
            with open(name, errors="replace") as fh:
                yield from fh

    sec = collections.defaultdict(lambda: collections.Counter())
    gap = collections.defaultdict(int)
    fb = {}
    t0 = last_in = last_any_audio = None
    for t, kind, ep, fields in parse(lines()):
        if t0 is None:
            t0 = t
        s = (t - t0) // 1_000_000
        c = sec[s]
        if kind == "Zi" and ep == 2:
            errors, pk = iso_packets(fields)
            c["in_errors"] += errors
            for st, ln in pk:
                c["in_frames"] += ln // a.framesize
                c["in_bad"] += st != 0
                c["in_odd"] += ln % a.framesize != 0
                c["in_empty"] += ln == 0
            if last_in is not None:
                gap[s] = max(gap[s], t - last_in)
            last_in = last_any_audio = t
        elif kind == "Zo" and ep == 1:
            errors, pk = iso_packets(fields)
            c["out_errors"] += errors
            for st, ln in pk:
                c["out_frames"] += ln // a.framesize
                c["out_bad"] += st != 0
            last_any_audio = t
        elif kind == "Zi" and ep == 1:
            r = feedback_value(fields)
            if r:
                fb[s] = r
        elif kind == "Bi":
            c["midi_in"] += int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else 0
        elif kind == "Bo":
            c["midi_out"] += int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else 0
    if t0 is None:
        sys.exit("usbmon-check: no completions in the input")

    odd = 0
    seconds = sorted(sec)
    for s in seconds[1:-1]:   # the first and last seconds are partial
        c = sec[s]
        flags = []
        if c["in_frames"] and not 44000 <= c["in_frames"] <= 44200:
            flags.append(f"IN {c['in_frames']} frames/s")
        if c["out_frames"] and not 44000 <= c["out_frames"] <= 44200:
            flags.append(f"OUT {c['out_frames']} frames/s")
        for k in ("in_bad", "in_odd", "in_empty", "in_errors", "out_bad", "out_errors"):
            if c[k]:
                flags.append(f"{k} {c[k]}")
        if gap[s] > 3000:
            flags.append(f"IN gap {gap[s] / 1000:.1f} ms")
        odd += bool(flags)
        if flags or a.all:
            print(f"{s:6d} s  IN {c['in_frames']:6d}  OUT {c['out_frames']:6d}  gap {gap[s] / 1000:5.1f} ms"
                  f"  fb {fb.get(s, 0):8.5f}  midi {c['midi_in']}/{c['midi_out']} B"
                  + ("  <- " + ", ".join(flags) if flags else ""))
    span = (seconds[-1] - seconds[0]) if seconds else 0
    print(f"{span} s of capture, {odd} odd seconds")
    if last_any_audio is not None and last_in is not None:
        print(f"audio last seen at {(last_any_audio - t0) / 1e6:.3f} s (IN at {(last_in - t0) / 1e6:.3f} s)")


if __name__ == "__main__":
    main()
