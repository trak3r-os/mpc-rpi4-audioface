#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check a multichannel capture of tonegen.py tones.

    arecord -D hw:CARD -t raw -f S32_LE -c 16 -r 44100 -d 600 | tonecheck.py -c 16 -f S32_LE -
    tonecheck.py -c 16 capture.wav            (the format comes from the WAV header)

For every captured channel it reports which tone it carries, so the channel
order is checked end to end, its level, and its glitches.

A clean sine obeys x[n+1] = 2 cos(w) x[n] - x[n-1]. Wherever that residual
jumps far above its own median, a sample was lost, repeated or zeroed. Nearby
hits are merged into one event.

Silence before the tones start and after they stop is skipped: the player and
the recorder never start and stop at the same instant. So is the last 0.1 s of
tones before such silence, where a player pads and drains its last period. A
gap anywhere else is a glitch.

The capture is read in blocks, so a long soak can be piped straight from arecord.
Needs numpy. The exit status is 1 when the order is wrong (with --expect-order)
or when any channel has a glitch.
"""

import argparse
import sys
import wave

import numpy as np

from tonegen import tone_frequencies

DTYPES = {"S16_LE": np.dtype("<i2"), "S32_LE": np.dtype("<i4")}
LSB16 = 1 / 32768
MERGE = 64  # glitch hits closer than this many samples are one event
SILENCE = 1e-4  # a frame below about -80 dBFS on every channel is silent
END_GUARD_S = 0.1  # glitches this close to the stop of the tones are the player draining


def read_blocks(path, channels, fmt, block_frames):
    """Yield float32 blocks of shape (frames, channels), scaled to [-1, 1)."""
    if path.endswith(".wav"):
        with wave.open(path, "rb") as w:
            if w.getnchannels() != channels:
                raise SystemExit(f"{path}: {w.getnchannels()} channels, expected {channels}")
            dtype = {2: DTYPES["S16_LE"], 4: DTYPES["S32_LE"]}[w.getsampwidth()]
            while chunk := w.readframes(block_frames):
                yield _scale(np.frombuffer(chunk, dtype), dtype, channels)
        return
    dtype = DTYPES[fmt]
    stream = sys.stdin.buffer if path == "-" else open(path, "rb")
    with stream:
        size = block_frames * channels * dtype.itemsize
        while chunk := stream.read(size):
            usable = len(chunk) - len(chunk) % (channels * dtype.itemsize)
            yield _scale(np.frombuffer(chunk[:usable], dtype), dtype, channels)


def _scale(raw, dtype, channels):
    return (raw.astype(np.float32) / float(1 << (8 * dtype.itemsize - 1))).reshape(-1, channels)


def identify(x, rate, freqs):
    """Which candidate tone each channel carries, from one second of audio.

    Returns, per channel: the index of the strongest candidate, its level in
    dBFS, and how far (dB) it stands above the next candidate.
    """
    spectrum = np.abs(np.fft.rfft(x[:rate], axis=0)) * 2 / rate
    bins = np.array(freqs)  # with exactly one second, bin i is i Hz
    levels = spectrum[bins, :]
    best = levels.argmax(axis=0)
    ordered = np.sort(levels, axis=0)
    runner_up = ordered[-2] if len(freqs) > 1 else np.zeros_like(ordered[-1])
    lead = 20 * np.log10(np.maximum(ordered[-1], 1e-12) / np.maximum(runner_up, 1e-12))
    return best, 20 * np.log10(np.maximum(ordered[-1], 1e-12)), lead


class GlitchCounter:
    """Streaming glitch detector for one channel holding a sine of known frequency."""

    def __init__(self, freq, rate, threshold=None):
        self.k = 2 * np.cos(2 * np.pi * freq / rate)
        self.threshold = threshold
        self.tail = np.zeros(0, np.float32)
        self.offset = 0  # index of tail[0] in the whole stream
        self.events = []
        self._last_hit = -10 * MERGE

    def feed(self, block):
        x = np.concatenate([self.tail, block])
        if len(x) >= 3:
            r = np.abs(x[2:] - self.k * x[1:-1] + x[:-2])
            if self.threshold is None:
                # Calibrate on the first block: 50x the median residual, at least 8 LSB of 16 bit.
                self.threshold = max(50 * float(np.median(r)), 8 * LSB16)
            for i in np.flatnonzero(r > self.threshold):
                n = self.offset + int(i) + 1
                if n - self._last_hit > MERGE:
                    self.events.append(n)
                self._last_hit = n
        keep = min(2, len(x))
        self.offset += len(x) - keep
        self.tail = x[len(x) - keep:]


def check(blocks, channels, rate, skip_s=0.5, expect_order=False):
    """Run identify + glitch detection over a block stream. Returns (report lines, ok)."""
    freqs = tone_frequencies(channels)
    skip = int(skip_s * rate)
    head = np.zeros((0, channels), np.float32)
    counters = None
    frames = 0        # frames read
    start = None      # first frame with signal
    fed = 0           # frames given to the counters; their index 0 is frame start + skip
    last_sound = -1   # last fed frame with signal, in the counters' index
    lines, ok = [], True
    for block in blocks:
        frames += len(block)
        if start is None:
            loud = np.flatnonzero(np.abs(block).max(axis=1) > SILENCE)
            if not len(loud):
                continue
            start = frames - len(block) + int(loud[0])
            block = block[loud[0]:]
        if counters is None:
            head = np.concatenate([head, block])
            if len(head) < skip + rate:
                continue
            best, level, lead = identify(head[skip:], rate, freqs)
            counters = [GlitchCounter(freqs[b], rate) for b in best]
            block = head[skip:]
        loud = np.flatnonzero(np.abs(block).max(axis=1) > SILENCE)
        if len(loud):
            last_sound = fed + int(loud[-1])
        for c, counter in enumerate(counters):
            counter.feed(block[:, c])
        fed += len(block)
    if start is None:
        return [f"no signal in {frames} frames"], False
    if counters is None:
        return [f"capture too short: {frames - start} frames of signal, need {skip + rate}"], False

    t0 = start + skip  # stream frame of the counters' index 0
    trailing = last_sound < fed - 1
    lines.append(f"{frames} frames ({frames / rate:.1f} s), {channels} channels, {rate} Hz; "
                 f"tones from {start / rate:.3f} s to {(t0 + last_sound) / rate:.3f} s")
    lines.append(" ch  tone(Hz)  source  level(dBFS)  lead(dB)  glitches  first at (s)")
    for c in range(channels):
        src = int(best[c]) + 1
        # When the tones stop before the capture does, that stop is not a glitch.
        events = [n for n in counters[c].events if not (trailing and n >= last_sound - END_GUARD_S * rate)]
        wrong = expect_order and src != c + 1
        ok &= not wrong and not events
        first = ", ".join(f"{(t0 + n) / rate:.3f}" for n in events[:5])
        lines.append(f"{c + 1:3d}  {freqs[best[c]]:8d}  {src:6d}{' !' if wrong else '  '}"
                     f"  {level[c]:11.1f}  {lead[c]:8.1f}  {len(events):8d}  {first}")
    return lines, ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("capture", help="raw PCM file, a .wav, or - for stdin")
    p.add_argument("-c", "--channels", type=int, required=True)
    p.add_argument("-r", "--rate", type=int, default=44100)
    p.add_argument("-f", "--format", choices=sorted(DTYPES), default="S32_LE")
    p.add_argument("--skip", type=float, default=0.5, help="seconds ignored at the start (stream start-up)")
    p.add_argument("--expect-order", action="store_true", help="fail unless channel k carries tone k")
    args = p.parse_args()

    blocks = read_blocks(args.capture, args.channels, args.format, block_frames=args.rate)
    lines, ok = check(blocks, args.channels, args.rate, args.skip, args.expect_order)
    print("\n".join(lines))
    print("OK" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
