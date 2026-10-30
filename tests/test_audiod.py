# SPDX-License-Identifier: GPL-3.0-or-later
"""rpi-audiod's pure logic (bridge/rpi-audiod/audiod.py), on outputs taken from the Pi."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"))
import audiod  # noqa: E402
from audiod import IN, OUT  # noqa: E402

# /proc/asound/GP150/stream0, trimmed to one altset per direction (2026-10-29).
GP150_STREAM = """Valeton GP-150 at usb-0000:01:00.0-1.1, high speed : USB Audio

Playback:
  Status: Stop
  Interface 2
    Altset 2
    Format: S32_LE
    Channels: 4
    Endpoint: 0x01 (1 OUT) (ASYNC)
    Rates: 48000
    Data packet interval: 125 us
    Bits: 24
    Channel map: FL FR FC LFE

Capture:
  Status: Stop
  Interface 1
    Altset 2
    Format: S32_LE
    Channels: 6
    Endpoint: 0x81 (1 IN) (ASYNC)
    Rates: 48000
    Data packet interval: 125 us
    Bits: 24
    Channel map: FL FR FC LFE RL RR
"""

# The PCM2902 of a Behringer mixer, trimmed: playback at three rates, capture one rate per altset.
PCM2902_STREAM = """Burr-Brown from TI USB Audio CODEC at usb-0000:01:00.0-1.3, full speed : USB Audio

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S16_LE
    Channels: 2
    Endpoint: 0x02 (2 OUT) (ADAPTIVE)
    Rates: 32000, 44100, 48000
    Bits: 16
    Channel map: FL FR
  Interface 1
    Altset 2
    Format: S16_LE
    Channels: 1
    Endpoint: 0x02 (2 OUT) (ADAPTIVE)
    Rates: 32000, 44100, 48000
    Bits: 16
    Channel map: MONO

Capture:
  Status: Stop
  Interface 2
    Altset 1
    Format: S16_LE
    Channels: 2
    Endpoint: 0x84 (4 IN) (ASYNC)
    Rates: 48000
    Bits: 16
    Channel map: FL FR
  Interface 2
    Altset 3
    Format: S16_LE
    Channels: 2
    Endpoint: 0x84 (4 IN) (ASYNC)
    Rates: 44100
    Bits: 16
    Channel map: FL FR
  Interface 2
    Altset 4
    Format: S16_LE
    Channels: 1
    Endpoint: 0x84 (4 IN) (ASYNC)
    Rates: 44100
    Bits: 16
    Channel map: MONO
"""

GADGET_CONTENTS = """numid=1,iface=PCM,name='Capture Pitch 1000000'
  ; type=INTEGER,access=rw------,values=1,min=750000,max=1005000,step=1
  : values=1000000
numid=4,iface=PCM,name='Capture Rate'
  ; type=INTEGER,access=r--v----,values=1,min=44100,max=44100,step=0
  : values=44100
numid=2,iface=PCM,name='Playback Pitch 1000000'
  ; type=INTEGER,access=rw------,values=1,min=750000,max=1005000,step=1
  : values=1000000
numid=3,iface=PCM,name='Playback Rate'
  ; type=INTEGER,access=r--v----,values=1,min=44100,max=44100,step=0
  : values=0
"""

GP150_SCONTENTS = """Simple mixer control 'PCM',0
  Capabilities: pvolume pswitch
  Playback channels: Front Left - Front Right - Rear Left - Rear Right
  Limits: Playback 0 - 99
  Mono:
  Front Left: Playback 0 [0%] [0.00dB] [on]
  Front Right: Playback 0 [0%] [0.00dB] [on]
  Rear Left: Playback 0 [0%] [0.00dB] [on]
  Rear Right: Playback 0 [0%] [0.00dB] [on]
Simple mixer control 'PCM',1
  Capabilities: pvolume pvolume-joined pswitch pswitch-joined
  Playback channels: Mono
  Limits: Playback 0 - 99
  Mono: Playback 0 [0%] [0.00dB] [on]
Simple mixer control 'Mic',0
  Capabilities: cvolume cswitch
  Capture channels: Front Left - Front Right
  Limits: Capture 0 - 99
  Front Left: Capture 0 [0%] [0.39dB] [on]
  Front Right: Capture 0 [0%] [0.39dB] [on]
"""

CODEC_SCONTENTS = """Simple mixer control 'PCM',0
  Capabilities: pvolume pswitch pswitch-joined
  Playback channels: Front Left - Front Right
  Limits: Playback 0 - 128
  Mono:
  Front Left: Playback 108 [84%] [-20.00dB] [on]
  Front Right: Playback 0 [0%] [-20.00dB] [on]
"""


def test_parse_stream_and_plan():
    gp = audiod.parse_stream(GP150_STREAM)
    assert audiod.plan_direction(gp["capture"], [48000, 44100]) == (48000, 6)
    assert audiod.plan_direction(gp["playback"], [44100]) == (48000, 4)  # not offered: its highest
    mixer = audiod.parse_stream(PCM2902_STREAM)
    assert audiod.plan_direction(mixer["capture"], [48000, 44100]) == (48000, 2)
    assert audiod.plan_direction(mixer["capture"], [44100]) == (44100, 2)
    assert audiod.plan_direction(mixer["playback"], [44100]) == (44100, 2)
    assert audiod.plan_direction([], [48000]) is None


def test_continuous_rates():
    found = audiod.parse_stream("Capture:\n  Channels: 8\n  Rates: 8000 - 96000 (continuous)\n")
    assert audiod.plan_direction(found["capture"], [44100]) == (44100, 8)


def test_identity():
    assert audiod.identity("84ef", "0186", "A1B2C3", "1-1.1") == "usb-84ef:0186-A1B2C3"
    assert audiod.identity("08bb", "2902", "", "1-1.3") == "usb-1-1.3-08bb:2902"
    assert audiod.identity("1935", "000c", "000000000001", "1-1.2") == "usb-1-1.2-1935:000c"
    assert audiod.identity("0582", "0001", "  RL123  ", "1-1.4") == "usb-0582:0001-RL123"
    for filler in ("12", "aaaa", "0000", "1"):
        assert audiod.identity("aaaa", "bbbb", filler, "1-2") == "usb-1-2-aaaa:bbbb"
    assert audiod.dedupe(["a", "b", "a", "a"]) == ["a", "b", "a#2", "a#3"]


def test_client_name():
    assert audiod.client_name("GP150", IN) == "gp150_in"
    assert audiod.client_name("Audio-2", OUT) == "audio_2_out"


def test_free_start_keeps_pairs_aligned():
    assert audiod.free_start(2, 26, set()) == 1
    assert audiod.free_start(2, 26, {1}) == 3
    assert audiod.free_start(3, 26, {3}) == 5
    assert audiod.free_start(2, 26, {25, 26}) == 1
    assert audiod.free_start(2, 4, {1, 3}) is None


def test_free_start_any_channel_with_align_1():
    assert audiod.free_start(1, 4, {1}, align=1) == 2
    assert audiod.free_start(2, 6, {1, 4}, align=1) == 2
    assert audiod.free_start(1, 3, {1, 2, 3}, align=1) is None


def test_allocate_align_1():
    assigned, _, _ = audiod.allocate({"a": 1, "b": 2}, {}, {}, 8, [1], align=1)
    assert assigned == {"a": 2, "b": 3}


def test_allocate_sticky_reserved_and_parked():
    # New devices take the first free blocks in the order they appeared, around reserved channels.
    assigned, parked, saved = audiod.allocate({"gp": 6, "mix": 2}, {}, {}, 26, [1, 2])
    assert assigned == {"gp": 3, "mix": 9} and not parked
    # Plugged in the other way round later: each gets its block back.
    assigned, _, _ = audiod.allocate({"mix": 2, "gp": 6}, saved, {"gp": 6, "mix": 2}, 26, [1, 2])
    assert assigned == {"mix": 9, "gp": 3}
    # An absent device keeps its block while there is room elsewhere...
    assigned, _, saved2 = audiod.allocate({"new": 2}, saved, {"gp": 6, "mix": 2}, 26, [1, 2])
    assert assigned == {"new": 11} and saved2["gp"] == 3
    # ...and gives it up when there is not.
    assigned, parked, saved3 = audiod.allocate({"big": 6}, saved, {"gp": 6, "mix": 2}, 8, [])
    assert assigned == {"big": 1} and "gp" not in saved3 and not parked
    # No room at all: parked.
    assigned, parked, _ = audiod.allocate({"a": 4, "b": 4}, {}, {}, 6, [])
    assert assigned == {"a": 1} and parked == ["b"]
    # A pinned (saved) start that no longer fits is replaced.
    assigned, _, _ = audiod.allocate({"gp": 6}, {"gp": 25}, {}, 26, [])
    assert assigned == {"gp": 1}


def test_routes():
    assert audiod.routes("gp150_in", IN, 9, 2) == [
        ("gp150_in:capture_1", "system:playback_9"), ("gp150_in:capture_2", "system:playback_10")]
    assert audiod.routes("gp150_out", OUT, 5, 2) == [
        ("system:capture_5", "gp150_out:playback_1"), ("system:capture_6", "gp150_out:playback_2")]


def test_feeder():
    assert audiod.feeder(44100, 44100) == "jack"
    assert audiod.feeder(44100, 0) == "silence"
    assert audiod.feeder(0, 44100) is None
    assert audiod.feeder(0, 0) is None


def test_parse_controls():
    assert audiod.parse_controls(GADGET_CONTENTS) == {
        "Capture Pitch 1000000": 1000000, "Capture Rate": 44100,
        "Playback Pitch 1000000": 1000000, "Playback Rate": 0}


def test_silent_volumes():
    assert audiod.silent_volumes(GP150_SCONTENTS) == ["PCM,0", "PCM,1"]  # capture controls are left alone
    assert audiod.silent_volumes(CODEC_SCONTENTS) == []  # one channel up is enough


def test_volume_controls():
    assert audiod.volume_controls(GP150_SCONTENTS, OUT) == ["PCM,0", "PCM,1"]
    assert audiod.volume_controls(GP150_SCONTENTS, IN) == ["Mic,0"]
    assert audiod.volume_controls(CODEC_SCONTENTS, OUT) == ["PCM,0"]
    assert audiod.volume_controls(CODEC_SCONTENTS, IN) == []
    joined = "Simple mixer control 'X',0\n  Capabilities: pvolume-joined cvolume-joined\n"
    assert audiod.volume_controls(joined, OUT) == [] and audiod.volume_controls(joined, IN) == []


def test_parse_connections():
    text = "system:capture_1\n   gp150_out:playback_1\nsystem:playback_9\ngp150_out:playback_1\n   system:capture_1\n"
    ports, pairs = audiod.parse_connections(text)
    assert ports == {"system:capture_1", "system:playback_9", "gp150_out:playback_1"}
    assert pairs == {frozenset(("system:capture_1", "gp150_out:playback_1"))}


def test_pcm_status():
    assert audiod.pcm_status("closed\n") == ("closed", None)
    text = "state: RUNNING\nowner_pid   : 1\ntrigger_time: 1.0\ntstamp      : 0.0\ndelay       : 1\n" \
           "avail       : 1\navail_max   : 1\n-----\nhw_ptr      : 1585187\nappl_ptr    : 1585536\n"
    assert audiod.pcm_status(text) == ("RUNNING", 1585187)


def test_identity_is_one_word():
    assert audiod.identity("1234", "5678", "AB 12/3", "1-1.2") == "usb-1234:5678-AB_12_3"
