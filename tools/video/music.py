"""Procedural background music for the overview video.

A calm ambient loop built from nothing but numpy: soft additive pads on a slow chord progression, a warm sub
bass, a light eighth-note pluck arpeggio with a stereo echo, and a faint low pulse. A synthetic reverb ties
it together. Nothing here is sampled or downloaded; the output is deterministic (seeded noise).

Public entry point: write_wav(path, seconds).
"""
import wave

import numpy as np

SR = 48000
BPM = 70.0
BEAT = 60.0 / BPM
CHORD_S = 8 * BEAT          # two bars of 4/4 per chord

# (root note, pad voicing) as MIDI numbers. A minor-ish, open voicings, nothing harsh.
PROGRESSION = [
    (45, [57, 60, 64, 67, 71]),   # Am9
    (41, [53, 57, 60, 64, 69]),   # Fmaj7
    (48, [52, 55, 59, 62, 67]),   # Cmaj9
    (43, [50, 55, 59, 62, 64]),   # G6/9
    (38, [53, 57, 60, 64, 69]),   # Dm9
    (41, [53, 57, 60, 64, 69]),   # Fmaj7
    (40, [55, 59, 62, 67, 69]),   # Em7(11)
    (45, [57, 60, 64, 67, 71]),   # Am9
]


def hz(note, cents=0.0):
    return 440.0 * 2.0 ** ((note - 69 + cents / 100.0) / 12.0)


def smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def pad_chord(notes, dur, rng):
    """One chord of detuned, softly filtered additive voices. Returns a stereo array (2, n)."""
    tail = 3.5
    n = int((dur + tail) * SR)
    t = np.arange(n) / SR
    env = smooth(t / 2.2) * (1.0 - smooth((t - dur) / tail))
    out = np.zeros((2, n))
    for i, note in enumerate(notes):
        for cents, pan in ((-5.0, -0.55), (5.0, 0.55)):
            pan = pan * (1 if i % 2 == 0 else -1)
            f = hz(note, cents)
            ph = rng.uniform(0, 2 * np.pi)
            wob = 1.0 + 0.0015 * np.sin(2 * np.pi * rng.uniform(0.08, 0.2) * t + ph)
            voice = np.zeros(n)
            for h in range(1, 6):                       # few partials: warm, no brightness
                voice += np.sin(2 * np.pi * f * h * wob * t + ph * h) / h ** 1.8
            tremolo = 0.8 + 0.2 * np.sin(2 * np.pi * rng.uniform(0.05, 0.12) * t + ph)
            voice *= env * tremolo * 0.5 / len(notes)
            out[0] += voice * np.cos((pan + 1) * np.pi / 4)
            out[1] += voice * np.sin((pan + 1) * np.pi / 4)
    return out


def bass_note(root, dur):
    n = int((dur + 1.5) * SR)
    t = np.arange(n) / SR
    env = smooth(t / 0.6) * (1.0 - smooth((t - dur) / 1.5))
    f = hz(root)
    v = (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)) * env * 0.35
    return np.vstack([v, v])


def pluck(note, vel):
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    f = hz(note)
    body = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) * np.exp(-t / 0.12) \
        + 0.1 * np.sin(6 * np.pi * f * t) * np.exp(-t / 0.06)
    return body * np.exp(-t / 0.28) * smooth(t / 0.006) * vel


def thump(vel):
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    f = 46.0 + 50.0 * np.exp(-t / 0.05)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(phase) * np.exp(-t / 0.16) * smooth(t / 0.004) * vel


def add(dst, src, start, pan=0.0):
    """Mix a mono or stereo clip into dst (2, N) at sample `start`."""
    if start >= dst.shape[1]:
        return
    n = min(src.shape[-1], dst.shape[1] - start)
    if src.ndim == 1:
        dst[0, start:start + n] += src[:n] * np.cos((pan + 1) * np.pi / 4)
        dst[1, start:start + n] += src[:n] * np.sin((pan + 1) * np.pi / 4)
    else:
        dst[:, start:start + n] += src[:, :n]


def echo(x, delay_s, feedback, taps=5):
    """Ping-pong echo: each repeat swaps channels."""
    d = int(delay_s * SR)
    out = x.copy()
    cur = x
    for k in range(1, taps + 1):
        cur = cur[::-1] * feedback
        sh = d * k
        if sh >= x.shape[1]:
            break
        out[:, sh:] += cur[:, :x.shape[1] - sh]
    return out


def reverb(x, rng, rt=3.0):
    """Convolve with a synthetic, darkened noise tail."""
    n_ir = int(rt * SR)
    t = np.arange(n_ir) / SR
    size = 1 << int(np.ceil(np.log2(x.shape[1] + n_ir)))
    out = np.zeros_like(x)
    for c in range(2):
        ir = rng.standard_normal(n_ir) * np.exp(-6.9 * t / rt)
        k = np.ones(24) / 24                           # crude lowpass: soft, dark tail
        ir = np.convolve(ir, k, mode="same")
        ir[: int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))
        wet = np.fft.irfft(np.fft.rfft(x[c], size) * np.fft.rfft(ir, size), size)[: x.shape[1]]
        out[c] = wet * 0.02
    return out


def render(seconds):
    rng = np.random.default_rng(20261108)
    total = int(seconds * SR)
    pads = np.zeros((2, total + int(6 * SR)))
    plucks = np.zeros_like(pads)
    low = np.zeros_like(pads)
    cache = {}
    n_chords = int(np.ceil(seconds / CHORD_S)) + 1
    for c in range(n_chords):
        root, notes = PROGRESSION[c % len(PROGRESSION)]
        start = int(c * CHORD_S * SR)
        key = c % len(PROGRESSION)
        if key not in cache:
            cache[key] = pad_chord(notes, CHORD_S + 1.0, rng)   # overlap chords for a seamless wash
        add(pads, cache[key], start)
        add(low, bass_note(root, CHORD_S), start)
        t0 = c * CHORD_S
        pattern = [0, 2, 1, 3, 2, 4, 3, 1]
        for e in range(16):                                     # sixteen eighth notes in two bars
            when = t0 + e * BEAT / 2
            idx = pattern[e % 8]
            note = notes[idx % len(notes)] + 12
            vel = 0.55 if e % 4 == 0 else 0.32
            add(plucks, pluck(note, vel), int(when * SR), pan=-0.45 if e % 2 else 0.45)
        if c >= 2:                                              # a faint pulse enters after the first chords
            for b in range(8):
                if b % 2 == 0:
                    add(low, thump(0.5 if b % 4 == 0 else 0.28), int((t0 + b * BEAT) * SR))

    tt = np.arange(pads.shape[1]) / SR
    pluck_gain = 0.0 + 0.9 * smooth((tt - 9.0) / 10.0)          # arpeggio fades in after ~9 s
    plucks *= pluck_gain * 0.20
    plucks = echo(plucks, BEAT * 0.75, 0.42)
    dry = pads * 0.9 + plucks + low * 0.55
    mix = dry + reverb(dry, rng) * 1.0
    mix = mix[:, :total]
    mix = np.tanh(mix * 1.1)
    rms = np.sqrt(np.mean(mix ** 2))
    mix *= 10 ** (-26.0 / 20) / rms                             # quiet bed: about -26 dBFS RMS
    t = np.arange(total) / SR
    fade = smooth(t / 4.0) * smooth((seconds - t) / 5.0)
    mix *= fade
    peak = np.max(np.abs(mix))
    if peak > 0.5:
        mix *= 0.5 / peak
    return mix


def write_wav(path, seconds):
    mix = render(seconds)
    data = (np.clip(mix.T, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


if __name__ == "__main__":
    import sys
    write_wav(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 60.0)
