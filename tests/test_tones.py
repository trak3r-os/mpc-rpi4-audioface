# SPDX-License-Identifier: GPL-3.0-or-later
"""tonegen.py and tonecheck.py: tones, channel identification, glitch detection."""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import tonecheck  # noqa: E402
import tonegen  # noqa: E402

RATE = 8000  # small, to keep the tests fast; nothing depends on the real 44100


def tones(channels, seconds, fmt="S32_LE"):
    raw = tonegen.one_second(channels, RATE, fmt) * seconds
    dtype = tonecheck.DTYPES[fmt]
    return tonecheck._scale(np.frombuffer(raw, dtype), dtype, channels)


def blocks(x, size=RATE):
    for i in range(0, len(x), size):
        yield x[i:i + size]


def run(x, expect_order=True):
    return tonecheck.check(blocks(x), x.shape[1], RATE, skip_s=0.5, expect_order=expect_order)


def events(x):
    """Glitch events per channel, as indices into x."""
    skip = RATE // 2
    out = []
    for c, f in enumerate(tonegen.tone_frequencies(x.shape[1])):
        g = tonecheck.GlitchCounter(f, RATE)
        for b in blocks(x[skip:]):
            g.feed(b[:, c])
        out.append([n + skip for n in g.events])
    return out


def test_channel_k_carries_k_times_110_hz():
    assert tonegen.tone_frequencies(4) == [110, 220, 330, 440]


def test_clean_capture_passes_and_loops_without_seam():
    lines, ok = run(tones(4, 4))
    assert ok, "\n".join(lines)
    assert events(tones(4, 4)) == [[], [], [], []]


def test_single_channel():
    lines, ok = run(tones(1, 3))
    assert ok, "\n".join(lines)


def test_16_bit_quantisation_is_not_a_glitch():
    lines, ok = run(tones(4, 3, "S16_LE"))
    assert ok, "\n".join(lines)


def test_swapped_channels_are_reported():
    x = tones(4, 3)[:, [1, 0, 2, 3]]
    lines, ok = run(x)
    assert not ok
    row = lines[2].split()  # channel 1
    assert row[0] == "1" and row[1] == "220" and row[2] == "2"
    _, ok = run(x, expect_order=False)
    assert ok  # without --expect-order a different order is reported, not failed


def test_dropped_sample_is_a_glitch():
    x = np.delete(tones(3, 3), 13600, axis=0)
    _, ok = run(x)
    assert not ok
    found = [e for ch in events(x) for e in ch]
    assert found and all(abs(e - 13600) <= 2 for e in found)


def test_zeroed_block_is_one_glitch_event_per_edge():
    x = tones(2, 3)
    x[12000:12100] = 0
    for ch in events(x):
        assert 1 <= len(ch) <= 2
        assert all(11990 <= e <= 12110 for e in ch)


def test_silence_before_and_after_the_tones_is_not_a_glitch():
    silence = np.zeros((int(2.3 * RATE), 3), np.float32)
    x = np.concatenate([silence, tones(3, 3), silence])
    lines, ok = run(x)
    assert ok, "\n".join(lines)
    assert "tones from 2.300 s to 5.300 s" in lines[0]


def test_gap_in_the_middle_is_a_glitch_even_with_trailing_silence():
    x = np.concatenate([tones(2, 4), np.zeros((RATE, 2), np.float32)])
    x[20000:20100] = 0
    lines, ok = run(x)
    assert not ok
    assert all(int(row.split()[5]) >= 1 for row in lines[2:])


def test_glitch_while_the_player_drains_is_ignored():
    x = np.concatenate([tones(2, 4), np.zeros((RATE, 2), np.float32)])
    x[4 * RATE - RATE // 20] = 0  # 50 ms before the tones stop
    lines, ok = run(x)
    assert ok, "\n".join(lines)


def test_too_short_capture_fails():
    lines, ok = run(tones(2, 1))
    assert not ok and "too short" in lines[0]
    lines, ok = run(np.zeros((3 * RATE, 2), np.float32))
    assert not ok and "no signal" in lines[0]


def test_reads_raw_and_wav(tmp_path):
    x = tones(2, 2, "S16_LE")
    raw = tonegen.one_second(2, RATE, "S16_LE") * 2
    (tmp_path / "c.raw").write_bytes(raw)
    with wave.open(str(tmp_path / "c.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(raw)
    for name in ("c.raw", "c.wav"):
        got = np.concatenate(list(tonecheck.read_blocks(str(tmp_path / name), 2, "S16_LE", 3000)))
        np.testing.assert_array_equal(got, x)
