"""Procedural background music for the overview video.

An upbeat, quiet loop built from nothing but numpy: a soft kick and offbeat hat for a light beat, a plucky bass,
warm chord stabs, and a simple catchy pentatonic motif played by a bell-like synth with a stereo echo. Nothing is
sampled or downloaded; the output is deterministic (seeded noise). Fades in and out over the full length.

Public entry point: write_wav(path, seconds).
"""
import wave

import numpy as np

SR = 48000
BPM = 104.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT

# Four-bar chord loop in C major: C  G  Am  F. (bass root, triad notes) as MIDI numbers.
CHORDS = [(36, [60, 64, 67]), (43, [59, 62, 67]), (45, [57, 60, 64]), (41, [57, 60, 65])]

# The motif, two bars long, in C major pentatonic, as (step in eighths, scale degree semitone offset from C5, length).
# It is repeated with a small variation every other time so it stays catchy without getting dull.
MOTIF_A = [(0, 7, 1), (1, 9, 1), (2, 12, 2), (4, 9, 1), (5, 7, 1), (6, 4, 2), (8, 7, 1), (9, 9, 1), (10, 12, 1),
           (11, 14, 1), (12, 12, 3)]
MOTIF_B = [(0, 12, 1), (1, 14, 1), (2, 16, 2), (4, 14, 1), (5, 12, 1), (6, 9, 2), (8, 7, 1), (9, 9, 1), (10, 7, 1),
           (11, 4, 1), (12, 7, 3)]


def hz(note):
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def put(buf, start, sig, gain=1.0, pan=0.0):
    i = int(start * SR)
    if i >= buf.shape[1]:
        return
    n = min(len(sig), buf.shape[1] - i)
    buf[0, i:i + n] += sig[:n] * gain * np.cos((pan + 1) * np.pi / 4)
    buf[1, i:i + n] += sig[:n] * gain * np.sin((pan + 1) * np.pi / 4)


def kick(dur=0.28):
    t = np.arange(int(dur * SR)) / SR
    f = 45 + 90 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)


def hat(rng, dur=0.07):
    n = rng.standard_normal(int(dur * SR))
    n = np.diff(n, prepend=0.0)                      # crude high-pass
    return n * np.exp(-np.arange(len(n)) / SR * 70)


def clap(rng, dur=0.16):
    t = np.arange(int(dur * SR)) / SR
    n = rng.standard_normal(len(t))
    n = n - np.convolve(n, np.ones(8) / 8, "same")   # band-ish
    return n * np.exp(-t * 28)


def pluck(note, dur, bright=1.0):
    t = np.arange(int(dur * SR)) / SR
    f = hz(note)
    s = np.sin(2 * np.pi * f * t) + 0.35 * bright * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 9) + \
        0.12 * bright * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 14)
    return s * np.exp(-t * 4.5) * np.minimum(1.0, t / 0.004)


def bell(note, dur):
    t = np.arange(int(dur * SR)) / SR
    f = hz(note)
    s = np.sin(2 * np.pi * f * t) + 0.45 * np.sin(2 * np.pi * f * 2.01 * t) * np.exp(-t * 6) + \
        0.2 * np.sin(2 * np.pi * f * 3.98 * t) * np.exp(-t * 12)
    return s * np.exp(-t * 3.2) * np.minimum(1.0, t / 0.006)


def stab(notes, dur):
    t = np.arange(int(dur * SR)) / SR
    s = np.zeros_like(t)
    for nn in notes:
        for det in (0.997, 1.003):
            s += np.sin(2 * np.pi * hz(nn) * det * t) + 0.3 * np.sin(2 * np.pi * hz(nn) * 2 * det * t)
    return s / (len(notes) * 2) * np.exp(-t * 7) * np.minimum(1.0, t / 0.006)


def echo(buf, delay, fb=0.35, mix=0.35, taps=3):
    out = buf.copy()
    d = int(delay * SR)
    for k in range(1, taps + 1):
        sh = d * k
        out[0, sh:] += buf[1, :-sh] * mix * fb ** (k - 1)      # ping-pong between channels
        out[1, sh:] += buf[0, :-sh] * mix * fb ** (k - 1)
    return out


def reverb(buf, rng, tail=1.4, mix=0.18):
    n = int(tail * SR)
    ir = rng.standard_normal((2, n)) * np.exp(-np.arange(n) / SR * 3.2)
    ir[:, :int(0.012 * SR)] = 0
    out = buf.copy()
    from numpy.fft import irfft, rfft
    size = 1 << int(np.ceil(np.log2(buf.shape[1] + n)))
    for ch in range(2):
        wet = irfft(rfft(buf[ch], size) * rfft(ir[ch], size), size)[:buf.shape[1]]
        out[ch] += wet * mix * 0.02
    return out


def render(seconds):
    rng = np.random.default_rng(7)
    total = seconds + 2.0
    buf = np.zeros((2, int(total * SR)))
    motif = np.zeros_like(buf)
    nbars = int(total / BAR) + 1
    for bar in range(nbars):
        t0 = bar * BAR
        root, triad = CHORDS[bar % 4]
        lead_in = min(1.0, bar / 4)                       # a bit sparser at the start
        # drums: soft four on the floor, clap on 2 and 4 after the intro, offbeat hats
        for b in range(4):
            tb = t0 + b * BEAT
            put(buf, tb, kick(), 0.34 * (0.6 + 0.4 * lead_in))
            put(buf, tb + BEAT / 2, hat(rng), 0.05 * (0.5 + 0.5 * lead_in), pan=0.25)
            if bar >= 2 and b in (1, 3):
                put(buf, tb, clap(rng), 0.06)
        # bass: root on 1, a hop on the "and" of 2 and the fifth on 4
        for b, off in ((0, 0), (1.5, 0), (2.5, 7), (3.5, 12)):
            put(buf, t0 + b * BEAT, pluck(root + off, BEAT * 0.9, 0.5), 0.2)
        # chord stabs on the offbeats, from bar 2
        if bar >= 2:
            for b in (0.5, 1.5, 2.5, 3.5):
                put(buf, t0 + b * BEAT, stab(triad, BEAT * 0.4), 0.075, pan=-0.2)
        # motif: bars 4 and on, in pairs of bars
        if bar >= 4 and bar % 2 == 0:
            phrase = MOTIF_A if (bar // 2) % 2 == 0 else MOTIF_B
            for step, semis, ln in phrase:
                put(motif, t0 + step * BEAT / 2, bell(72 + semis - 12, ln * BEAT / 2 + 0.5), 0.13, pan=0.15)
    motif = echo(motif, BEAT * 0.75, 0.4, 0.35)
    buf += motif
    buf = reverb(buf, rng)
    buf = buf[:, :int(seconds * SR)]
    # fades: 1.5 s in, 3 s out; keep it quiet
    t = np.arange(buf.shape[1]) / SR
    env = np.minimum(1.0, t / 1.5) * np.minimum(1.0, np.maximum(0.0, (seconds - t) / 3.0))
    buf *= env
    peak = np.abs(buf).max()
    return buf * (0.30 / peak)            # peak at about -10 dBFS: background level


def write_wav(path, seconds):
    x = render(seconds)
    pcm = (np.clip(x.T, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
