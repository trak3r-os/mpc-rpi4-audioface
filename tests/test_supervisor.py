# SPDX-License-Identifier: GPL-3.0-or-later
"""The supervision logic of rpi-audiod (bridge/rpi-audiod/rpi-audiod): the main loop, the choice of
what feeds the gadget, the bridges, device scans and slot assignment, and the MIDI control port.

The outside world is faked by replacing the daemon module's own functions and classes: run (amixer,
jack_*, aconnect), read (/proc files), Child (processes), scan (the USB cards), udc_state, time and
the few os.path calls that look at /proc. Nothing runs for real and no test sleeps: the clock is a
number that only the loop's own sleep() moves."""

import importlib.machinery
import importlib.util
import json
import signal
import subprocess
import sys
import time as real_time
import types
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"
sys.path.insert(0, str(BRIDGE))
import audiod  # noqa: E402
import midi  # noqa: E402
from audiod import IN, OUT  # noqa: E402

stub = "tomllib" not in sys.modules and importlib.util.find_spec("tomllib") is None
if stub:   # Python before 3.11: the daemon imports it, but these tests do not use it
    sys.modules["tomllib"] = types.ModuleType("tomllib")
loader = importlib.machinery.SourceFileLoader("rpi_audiod", str(BRIDGE / "rpi-audiod"))
daemon = importlib.util.module_from_spec(importlib.util.spec_from_loader("rpi_audiod", loader))
loader.exec_module(daemon)
if stub:
    del sys.modules["tomllib"]

CARD = "UAC2Gadget"
PCM_STATUS = f"/proc/asound/{CARD}/pcm0p/sub0/status"
DAC = "sndrpihifiberry"   # [standalone] card, by default
PCM_STATUS_DAC = f"/proc/asound/{DAC}/pcm0p/sub0/status"


class Halt(Exception):
    """Ends World.run without the loop's cleanup, so the state can be looked at."""


class FakeChild:
    def __init__(self, world, name, cmd, on_line, stop_signal):
        self.world, self.name, self.cmd, self.on_line, self.stop_signal = world, name, cmd, on_line, stop_signal
        self.started, self.alive_ = world.now, True
        world.next_pid += 1
        self.proc = types.SimpleNamespace(pid=world.next_pid, returncode=None)

    def alive(self):
        return self.alive_

    def die(self, code=1):
        self.alive_, self.proc.returncode = False, code

    def stop(self, grace=1.0):
        if self.alive_:
            self.world.stopped.append(self.name)
            self.world.forget(self.name)
            self.die(0)


class FakeOS:
    """The daemon's os, but /proc/asound/<card> resolves to the sound card the test picks."""

    def __init__(self, world):
        self.world = world
        self.path = types.SimpleNamespace(**{n: getattr(__import__("os").path, n)
                                             for n in dir(__import__("os").path) if not n.startswith("_")})
        self.path.realpath = self.realpath

    def realpath(self, path, *args, **kw):
        if str(path).startswith("/proc/asound/") and self.world.gadget_card is not None:
            return f"/proc/asound/card{self.world.gadget_card}"
        return __import__("os").path.realpath(path, *args, **kw)

    def __getattr__(self, name):
        return getattr(__import__("os"), name)


class World:
    """ALSA controls, /proc files, JACK, aconnect and the processes the daemon starts."""

    def __init__(self):
        self.now = 1000.0
        self.rates = (0, 0)               # the host's (playback, capture) rate, from the gadget's controls
        self.ptr, self.ptr_step = 0, 48   # the gadget's playback pointer, and how far it moves per tick
        self.files, self.calls, self.logs = {}, [], []
        self.children, self.stopped, self.next_pid = [], [], 100
        self.connections = set()          # frozensets of two JACK ports
        self.hang_jack = False            # jackd runs but jack_lsp does not answer
        self.aconnect, self.udc, self.gadget_card = "", "", 1
        self.scontents = {}               # card id -> `amixer scontents`
        self.devices = []
        self.sleeps, self.limit, self.stop_at_limit = 0, 0, False
        self.d = None
        self.set_ptr()

    # --- the module's functions, replaced -----------------------------------------------------

    def install(self, monkeypatch, tmp_path):
        monkeypatch.setattr(daemon, "log", self.logs.append)
        monkeypatch.setattr(daemon, "run", self.run)
        monkeypatch.setattr(daemon, "read", lambda path: self.files.get(str(path), ""))
        monkeypatch.setattr(daemon, "Child", self.spawn)
        monkeypatch.setattr(daemon, "udc_state", lambda: self.udc)
        monkeypatch.setattr(daemon, "scan", self.scan)
        monkeypatch.setattr(daemon, "time", types.SimpleNamespace(
            monotonic=lambda: self.now, sleep=self.sleep, strftime=real_time.strftime))
        monkeypatch.setattr(daemon, "os", FakeOS(self))
        monkeypatch.setattr(daemon.Midi, "sender", lambda self: None)   # would run aplaymidi
        monkeypatch.setattr(daemon, "STATE", tmp_path / "slots.json")
        monkeypatch.setattr(daemon, "PRESETS", tmp_path / "presets.json")
        monkeypatch.setattr(daemon, "CONFIG", tmp_path / "rpi-audio.toml")
        (tmp_path / "run").mkdir()
        monkeypatch.setattr(daemon, "STATUS", tmp_path / "run" / "status.json")
        for name in ("GADGET_SSIZE", "GADGET_MIDI_ID"):
            monkeypatch.delenv(name, raising=False)

    def spawn(self, name, cmd, on_line=None, stop_signal=signal.SIGTERM):
        child = FakeChild(self, name, cmd, on_line, stop_signal)
        self.children.append(child)
        return child

    def scan(self, cfg, profiles, cache):
        return list(self.devices), {dev.card: dev.identity for dev in self.devices}

    def live(self, name=None):
        return [c for c in self.children if c.alive_ and (name is None or c.name == name)]

    def forget(self, name):
        """A stopped zita leaves JACK with its connections; a stopped jackd takes them all."""
        if name == "jackd":
            self.connections.clear()
        self.connections = {c for c in self.connections if not any(p.startswith(name + ":") for p in c)}

    def ports(self):
        ports = {f"system:{kind}_{k}" for kind in ("capture", "playback") for k in range(1, 9)}
        for c in self.live():
            if c.name.endswith(("_in", "_out")):
                ports |= {f"{c.name}:{kind}_{k}" for kind in ("capture", "playback") for k in range(1, 9)}
        return ports

    def called(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == prefix]

    def run(self, *cmd, timeout=2):
        self.calls.append(cmd)
        out, code = "", 0
        if cmd[0] == "amixer" and cmd[1:2] == ("-c",) and cmd[3] == "contents":
            out = "".join(f"numid={n},iface=PCM,name='{name}'\n  ; type=INTEGER,values=1\n  : values={rate}\n"
                          for n, (name, rate) in enumerate(zip(("Playback Rate", "Capture Rate"), self.rates)))
        elif cmd[0] == "amixer" and cmd[1:2] == ("-c",) and cmd[3] == "scontents":
            out = self.scontents.get(cmd[2], "")
        elif cmd[0] == "jack_lsp":
            code = 0 if self.live("jackd") and not self.hang_jack else 1
            if "-c" in cmd:
                for port in sorted(self.ports()):
                    out += port + "\n"
                    out += "".join(f"   {p}\n" for c in self.connections if port in c for p in c if p != port)
        elif cmd[0] == "jack_connect":
            self.connections.add(frozenset(cmd[1:]))
        elif cmd[0] == "jack_disconnect":
            self.connections.discard(frozenset(cmd[1:]))
        elif cmd[0] == "aconnect" and cmd[1:] == ("-l",):
            out = self.aconnect
        return subprocess.CompletedProcess(cmd, code, out, "")

    def set_ptr(self):
        self.files[PCM_STATUS] = self.files[PCM_STATUS_DAC] = (
            f"state: RUNNING\nowner_pid   : 1\nhw_ptr      : {self.ptr}\nappl_ptr    : 0\n")

    def sleep(self, seconds):
        self.now += seconds
        self.ptr += self.ptr_step
        self.set_ptr()
        self.sleeps += 1
        if self.sleeps >= self.limit:
            if self.stop_at_limit:
                self.d.stopping = True
            else:
                raise Halt

    def run_loop(self, ticks, stop=False):
        """Runs `ticks` iterations of Daemon.loop at 0.1 s each. With stop, ends it the way a
        signal does (cleanup included); otherwise the state is left as it is."""
        self.limit, self.stop_at_limit = self.sleeps + ticks, stop
        try:
            self.d.loop()
        except Halt:
            pass

    def seconds(self, s):
        self.run_loop(round(s / daemon.TICK))


def logged(w, text):
    return [line for line in w.logs if text in line]


def make(monkeypatch, tmp_path, channels=8, midi_ports=0, **sections):
    cfg = {"gadget": {}, "engine": {}, "bridge": {}, "slots": {}, "midi": {}, "usb": {}}
    cfg.update(sections)
    w = World()
    w.install(monkeypatch, tmp_path)
    monkeypatch.setenv("GADGET_CHANNELS", str(channels))
    monkeypatch.setenv("GADGET_MIDI_PORTS", str(midi_ports))
    w.d = daemon.Daemon(cfg)
    return w, w.d


def usb_device(card, name, plans=None, loads=None, bus="1", profile=None, usbbus="001/002"):
    plans = plans or {IN: (48000, 2), OUT: (48000, 2)}
    loads = loads or {IN: 196, OUT: 192}
    return daemon.Device(card, name, usbbus, "usb-" + name, plans, profile, speed="12", bus=bus, loads=loads)


def streaming(w, rates=(48000, 48000)):
    w.rates = rates


def bring_up(monkeypatch, tmp_path, *devices, **kw):
    """A daemon whose host streams both ways at 48 kHz, run until jackd and the bridges are up."""
    w, d = make(monkeypatch, tmp_path, **kw)
    w.devices = list(devices)
    streaming(w)
    w.run_loop(3)
    return w, d


def zita_names(w):
    return [c.name for c in w.live() if c.name.endswith(("_in", "_out"))]


# --- host starts and stops streaming ------------------------------------------------------------

def test_host_streaming_brings_up_jackd_bridges_and_routes(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer")]
    streaming(w)
    w.run_loop(1)   # a rate is only believed when seen on two ticks in a row
    assert d.mode is None and not w.children
    assert d.bridges[("usb-mixer", IN)].start == 1 and d.bridges[("usb-mixer", OUT)].start == 1
    w.run_loop(1)
    assert logged(w, "host streaming at 48000 Hz (capture 48000): jack")
    assert d.mode == "jack" and d.jack_ready and logged(w, "jackd is up")
    assert [c.name for c in w.children] == ["jackd", "mixer_in", "mixer_out"]
    jackd, a2j, j2a = w.children
    assert jackd.cmd[:2] == ["jackd", "-R"] and "hw:UAC2Gadget" in jackd.cmd
    assert jackd.cmd[jackd.cmd.index("-r") + 1] == "48000"
    assert (jackd.cmd[jackd.cmd.index("-i") + 1], jackd.cmd[jackd.cmd.index("-o") + 1]) == ("8", "8")
    assert a2j.cmd[0] == "zita-a2j" and j2a.cmd[0] == "zita-j2a"
    assert a2j.stop_signal == j2a.stop_signal == signal.SIGINT   # zita only leaves JACK cleanly on SIGINT
    assert a2j.cmd[a2j.cmd.index("-d") + 1] == "hw:CARD=mixer" and a2j.cmd[a2j.cmd.index("-c") + 1] == "2"
    assert w.connections == {
        frozenset(("mixer_in:capture_1", "system:playback_1")), frozenset(("mixer_in:capture_2", "system:playback_2")),
        frozenset(("system:capture_1", "mixer_out:playback_1")),
        frozenset(("system:capture_2", "mixer_out:playback_2"))}


def test_routes_are_connected_once_and_the_status_file_follows(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"))
    assert len(w.called("jack_connect")) == 4
    w.seconds(3)   # many route passes later, nothing is connected twice
    assert len(w.called("jack_connect")) == 4 and len(w.live()) == 3
    status = json.loads((tmp_path / "run" / "status.json").read_text())
    assert (status["feeder"], status["jack_ready"], status["host_playback_rate"]) == ("jack", True, 48000)
    assert status["devices"][0]["identity"] == "usb-mixer" and status["devices"][0][IN]["running"] is True


def test_host_stops_stops_everything_and_plays_no_silence(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"))
    assert len(w.live()) == 3
    streaming(w, (0, 0))
    w.run_loop(1)   # seen once: nothing yet
    assert len(w.live()) == 3
    w.run_loop(1)
    assert logged(w, "the host stopped streaming")
    assert not w.live() and d.mode is None and not d.jack_ready and d.jackd is d.player is None
    assert w.stopped == ["mixer_in", "mixer_out", "jackd"]   # bridges first, then the server
    assert not w.called("jack_disconnect")   # jackd is going away: nothing is disconnected one by one
    assert [c.name for c in w.children] == ["jackd", "mixer_in", "mixer_out"]   # and no keepalive player
    w.seconds(2)
    assert len(w.children) == 3   # still nothing


def test_host_recording_only_gets_silence_and_no_bridges(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer")]
    streaming(w, (48000, 0))
    w.run_loop(3)
    assert d.mode == "silence" and d.jackd is None and not d.jack_ready
    (player,) = w.live()
    assert player.name == "silence"
    assert player.cmd == ["aplay", "-q", "-D", "hw:CARD=UAC2Gadget", "-t", "raw", "-f", "S32_LE", "-c", "8",
                          "-r", "48000", "/dev/zero"]
    assert d.bridges[("usb-mixer", IN)].child is None   # bridges wait for jackd


def test_silence_gives_way_to_jack_and_back(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer")]
    streaming(w, (48000, 0))
    w.run_loop(3)
    streaming(w)   # the host starts recording from the Pi too
    w.run_loop(3)
    assert d.mode == "jack" and w.stopped == ["silence"]
    assert [c.name for c in w.live()] == ["jackd", "mixer_in", "mixer_out"]
    streaming(w, (48000, 0))   # and stops recording again
    w.run_loop(3)
    assert d.mode == "silence" and [c.name for c in w.live()] == ["silence"]
    assert w.stopped[1:] == ["mixer_in", "mixer_out", "jackd"]


def test_silence_stops_when_the_host_stops_recording(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    streaming(w, (48000, 0))
    w.run_loop(3)
    assert d.mode == "silence"
    streaming(w, (0, 0))
    w.run_loop(2)
    assert d.mode is None and not w.live() and w.stopped == ["silence"]


def test_rate_change_restarts_the_feeder_and_the_bridges(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"))
    streaming(w, (44100, 44100))
    w.run_loop(2)
    assert d.rate == 44100 and w.stopped[:3] == ["mixer_in", "mixer_out", "jackd"]
    jackd = w.live("jackd")[0]
    assert jackd.cmd[jackd.cmd.index("-r") + 1] == "44100"
    assert zita_names(w) == ["mixer_in", "mixer_out"] and not w.connections   # routes come with the next pass
    w.seconds(1.1)
    assert len(w.connections) == 4 and w.stopped.count("jackd") == 1


def test_a_stop_request_stops_every_child(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"))
    w.run_loop(2, stop=True)   # what SIGTERM does
    assert not w.live() and logged(w, "rpi-audiod: stopped")


# --- a feeder that dies or stalls -------------------------------------------------------------

def test_jackd_dying_restarts_it_and_the_routes_come_back(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"))
    w.live("jackd")[0].die(1)
    w.run_loop(3)
    assert logged(w, "jackd exited, restarting") and d.jack_fails == 1
    assert [c.name for c in w.live()] == ["jackd", "mixer_in", "mixer_out"]
    assert len(w.children) == 6 and d.jack_ready
    assert not w.connections
    w.seconds(1.1)   # the next route pass
    assert len(w.connections) == 4 and len(w.called("jack_connect")) == 8


def test_stalled_pointer_restarts_the_feeder_in_the_loop(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer")]
    streaming(w)
    w.ptr_step = 0   # jackd lives but the gadget's playback pointer never moves
    w.seconds(3.5)
    assert len(w.children) == 3 and not logged(w, "stalled")   # a new feeder gets STARTUP_S
    w.seconds(2)
    assert logged(w, "jackd stalled (RUNNING, pointer still), restarting")
    assert d.jack_fails == 1 and len(w.live("jackd")) == 1 and len(w.children) == 6
    assert zita_names(w) == ["mixer_in", "mixer_out"]


def test_repeated_jackd_failures_fall_back_to_silence(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer")]
    streaming(w)
    w.ptr_step = 0
    w.seconds(14)
    assert logged(w, "jackd failed 3 times in a row; silence for 10 s")
    assert d.mode == "silence" and d.target == "jack" and d.jackd is None and d.player
    assert sum(c.name == "jackd" for c in w.children) == 3
    assert zita_names(w) == []   # bridges need jackd


def test_check_feeder_leaves_a_moving_feeder_alone(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    d.set_mode("jack", w.now)
    d.jack_fails = 2
    for step in range(1, 80):   # 8 s
        w.now += 0.1
        w.ptr += 48
        w.set_ptr()
        d.check_feeder(w.now)
        if step < 49:
            assert d.jack_fails == 2   # a feeder that lived 5 s has not failed yet
    assert d.jack_fails == 0 and len(w.children) == 1 and not logged(w, "restarting")


def test_check_feeder_stall_needs_startup_and_stall_time(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.now = 100.0
    d.set_mode("jack", 100.0)
    w.ptr = 5
    w.set_ptr()
    d.check_feeder(101.0)             # the pointer moved at 101
    d.check_feeder(104.0)             # 4 s old, still: STARTUP_S is exclusive
    assert d.jackd and not logged(w, "stalled")
    d.check_feeder(104.01)
    assert not d.jackd and d.mode is None and logged(w, "jackd stalled (RUNNING, pointer still)")
    w.now = 105.0
    d.set_mode("jack", 105.0)         # set_mode starts it again, with the pointer unknown
    assert d.jackd and d.ptr is None and d.ptr_moved == 105.0
    w.ptr = 6
    w.set_ptr()
    d.check_feeder(109.0)             # pointer seen moving at 109: not stalled even though old
    d.check_feeder(110.0)
    assert d.jackd and d.jack_fails == 1
    d.check_feeder(110.6)             # pointer 1.6 s still, feeder 5.6 s old
    assert not d.jackd and d.jack_fails == 2


def test_check_feeder_dead_silence_player_is_not_a_jack_failure(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    d.set_mode("silence", w.now)
    d.player.die(1)
    d.check_feeder(w.now + 0.1)
    assert logged(w, "silence exited, restarting") and d.player is None and d.mode is None
    assert d.jack_fails == 0 and d.fallback_until == 0.0
    d.set_mode("silence", w.now + 0.2)
    assert d.player and d.mode == "silence"


def test_jack_fallback_lasts_fallback_s_then_jack_returns(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    t = 100.0
    for _ in range(daemon.JACK_FAILS):
        d.set_mode("jack", t)
        assert d.mode == "jack" and d.jackd
        d.jackd.die(1)
        d.check_feeder(t + 1)
        t += 1
    assert d.jack_fails == 0 and d.fallback_until == t + daemon.FALLBACK_S
    d.set_mode("jack", t)    # jack wanted, silence played
    assert d.mode == "silence" and d.player and d.jackd is None
    player = d.player
    d.set_mode("jack", t + 9)
    assert d.player is player and d.mode == "silence"   # same feeder, not restarted every tick
    d.set_mode("jack", t + daemon.FALLBACK_S)
    assert d.mode == "jack" and d.jackd and d.player is None and not player.alive_


def test_set_mode_is_idempotent_and_none_stops(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    d.set_mode("jack", w.now)
    first = d.jackd
    d.set_mode("jack", w.now + 1)
    assert d.jackd is first and len(w.children) == 1
    first.die(1)
    d.jackd = None   # the feeder is gone but the mode says it runs: set_mode starts it again
    d.set_mode("jack", w.now + 2)
    assert d.jackd and d.jackd is not first
    d.set_mode(None, w.now + 3)
    assert d.mode is None and d.jackd is d.player is None and not w.live()
    d.set_mode(None, w.now + 4)
    assert len(w.children) == 2


def test_check_jack_ready_waits_for_jack_lsp(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    d.check_jack_ready()
    assert not w.calls   # no jackd: no jack_lsp
    d.set_mode("jack", w.now)
    w.hang_jack = True
    d.check_jack_ready()
    d.check_jack_ready()
    assert not d.jack_ready and len(w.called("jack_lsp")) == 2
    w.hang_jack = False
    d.check_jack_ready()
    d.check_jack_ready()
    assert d.jack_ready and len(w.called("jack_lsp")) == 3 and len(logged(w, "jackd is up")) == 1
    d.stop_feeder()
    assert not d.jack_ready


# --- one bridge ----------------------------------------------------------------------------

def bridge_for(w, direction=IN, start=1, **kw):
    dev = usb_device(1, "mixer", **kw)
    b = daemon.Bridge(dev, direction)
    b.start = start
    return b


def test_bridge_command_and_cfg(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    cfg = {"bridge": {"period": 128, "periods": 3}}
    a2j, j2a = bridge_for(w, IN), bridge_for(w, OUT)
    a2j.tick(cfg, w.now)
    j2a.tick(cfg, w.now)
    assert a2j.child.cmd == ["zita-a2j", "-j", "mixer_in", "-d", "hw:CARD=mixer", "-r", "48000", "-c", "2",
                             "-p", "128", "-n", "3"]
    assert j2a.child.cmd[:3] == ["zita-j2a", "-j", "mixer_out"]
    b = bridge_for(w, IN)
    b.tick({"bridge": {}}, w.now)
    assert b.child.cmd[-4:] == ["-p", "256", "-n", "2"]


def test_bridge_restarts_with_doubling_backoff(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    cfg, b = {"bridge": {}}, bridge_for(w)
    w.now = 0.0
    b.tick(cfg, 0.0)
    first = b.child
    b.tick(cfg, 3.0)
    assert b.child is first
    first.die(1)
    b.tick(cfg, 5.0)
    assert b.child is None and b.backoff == 2.0 and b.next_try == 7.0
    assert logged(w, "mixer_in exited after 5.0 s (code 1)")
    b.tick(cfg, 6.9)
    assert b.child is None
    w.now = 7.0
    b.tick(cfg, 7.0)
    second = b.child
    assert second and second is not first
    second.die(1)
    b.tick(cfg, 10.0)
    assert b.backoff == 4.0 and b.next_try == 14.0
    for _ in range(6):   # the backoff stops at 30 s
        b.child = FakeChild(w, "x", [], None, None)
        b.child.started = 0.0
        b.child.die(1)
        b.tick(cfg, 20.0)
    assert b.backoff == 30.0


def test_bridge_that_lived_a_minute_restarts_quickly(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    cfg, b = {"bridge": {}}, bridge_for(w)
    w.now = 0.0
    b.tick(cfg, 0.0)
    b.backoff = 16.0
    b.child.die(1)
    b.tick(cfg, 61.0)
    assert b.backoff == 1.0 and b.next_try == 62.0
    b.tick(cfg, 62.0)
    assert b.child


def test_bridge_stop_disconnects_its_routes_unless_told_not_to(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    b = bridge_for(w, OUT, start=3)
    b.tick({"bridge": {}}, w.now)
    b.stop()
    assert w.called("jack_disconnect") == [("jack_disconnect", f"system:capture_{c + 2}", f"mixer_out:playback_{c}")
                                           for c in (1, 2)]
    assert b.child is None and w.stopped == ["mixer_out"]
    b.stop()   # nothing running: nothing to do
    assert len(w.called("jack_disconnect")) == 2
    b.tick({"bridge": {}}, w.now + 100)
    b.stop(disconnect=False)
    assert len(w.called("jack_disconnect")) == 2 and b.child is None


# --- the budget, through the whole daemon -------------------------------------------------

def test_direction_refused_by_the_budget_is_not_started_until_it_fits(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    tracker = usb_device(1, "tracker", loads={IN: 903, OUT: 100}, usbbus="001/002")
    mixer = usb_device(2, "mixer", loads={IN: 200, OUT: 90}, usbbus="001/003")
    w.devices = [tracker, mixer]
    streaming(w)
    w.run_loop(3)
    assert zita_names(w) == ["tracker_in", "tracker_out", "mixer_out"]
    blocked = d.bridges[("usb-mixer", IN)]
    assert blocked.child is None
    assert blocked.blocked == "USB full-speed budget: needs 200 B, 6 B of 1099 B free on bus 1"
    assert logged(w, "mixer_in waits, USB full-speed budget")
    entry = {e["identity"]: e for e in d.status_data()["devices"]}["usb-mixer"]
    assert entry[IN]["running"] is False and entry[IN]["blocked"].startswith("USB full-speed budget")
    assert entry[OUT]["running"] is True and "blocked" not in entry[OUT]
    w.seconds(2)
    assert len(logged(w, "waits")) == 1   # said once
    w.devices = [mixer]   # the tracker is unplugged: its budget frees up
    w.seconds(1.5)
    assert zita_names(w) == ["mixer_out", "mixer_in"] and blocked.blocked is None
    assert logged(w, "mixer_in has USB budget again")


def test_a_crashed_bridge_keeps_its_place_in_the_budget_order(monkeypatch, tmp_path):
    """While a crashed bridge waits out its backoff it still holds its share of the bus: the one blocked behind it
    does not start in the meantime and take it."""
    w, d = make(monkeypatch, tmp_path)
    one_way = {IN: (48000, 2), OUT: None}
    w.devices = [usb_device(1, "tracker", plans=one_way, loads={IN: 903, OUT: None}),
                 usb_device(2, "mixer", plans=one_way, loads={IN: 200, OUT: None}, usbbus="001/003")]
    streaming(w)
    w.run_loop(3)
    assert zita_names(w) == ["tracker_in"]
    w.live("tracker_in")[0].die(1)
    w.seconds(3)
    assert zita_names(w) == ["tracker_in"]   # the first device is back, the second still waits


def test_budget_zero_in_the_config_starts_everything(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path, usb={"fs_budget": 0})
    w.devices = [usb_device(1, "tracker", loads={IN: 903, OUT: 903}), usb_device(2, "mixer", loads={IN: 903, OUT: 903})]
    streaming(w)
    w.run_loop(3)
    assert len(zita_names(w)) == 4


def test_bad_budget_in_the_config_uses_the_default(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path, usb={"fs_budget": "lots"})
    assert d.fs_budget == daemon.usb.FS_BUDGET and logged(w, "is not a number")


# --- scan_devices and reassign ------------------------------------------------------------

def test_scan_finds_a_device_and_gives_it_gadget_channels(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer"), usb_device(2, "synth", plans={IN: (48000, 4), OUT: None},
                                                    loads={IN: 100, OUT: None})]
    d.scan_devices()
    assert sorted(d.devices) == ["usb-mixer", "usb-synth"] and d.cards == {1: "usb-mixer", 2: "usb-synth"}
    assert sorted(d.bridges) == [("usb-mixer", IN), ("usb-mixer", OUT), ("usb-synth", IN)]   # no OUT plan: no bridge
    starts = {k: b.start for k, b in d.bridges.items()}
    assert starts == {("usb-mixer", IN): 1, ("usb-mixer", OUT): 1, ("usb-synth", IN): 3}
    slots = daemon.load_slots()
    assert slots["in"] == {"usb-mixer": 1, "usb-synth": 3} and slots["out"] == {"usb-mixer": 1}
    assert slots["in_channels"] == {"usb-mixer": 2, "usb-synth": 4}
    assert d.starts() == {IN: {1: "usb-mixer", 3: "usb-synth"}, OUT: {1: "usb-mixer"}}
    assert logged(w, "mixer_in -> gadget IN 1-2") and logged(w, "synth_in -> gadget IN 3-6")
    stamp = daemon.slots_stamp()
    d.scan_devices()   # nothing changed: slots.json is not rewritten and nothing is logged again
    assert daemon.slots_stamp() == stamp and len(logged(w, "synth_in -> gadget")) == 1


def test_a_direction_with_every_channel_ignored_gets_no_bridge(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    profile = audiod.Profile("1234:5678", "p.toml", ignore_in=(1, 2))
    w.devices = [usb_device(1, "mixer", profile=profile)]
    d.scan_devices()
    assert list(d.bridges) == [("usb-mixer", OUT)]
    assert logged(w, "the profile ignores every IN channel; no bridge")
    assert "usb-mixer" not in daemon.load_slots().get("in", {})


def test_a_profile_ignoring_some_channels_gives_a_smaller_block(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    profile = audiod.Profile("1234:5678", "p.toml", ignore_out=(2,), start_in=5)
    w.devices = [usb_device(1, "mixer", plans={IN: (48000, 2), OUT: (48000, 4)}, profile=profile)]
    d.scan_devices()
    out = d.bridges[("usb-mixer", OUT)]
    assert (out.channels, out.size, out.kept) == (4, 3, [1, 3, 4])
    assert d.bridges[("usb-mixer", IN)].start == 5   # the profile's preferred start
    assert daemon.load_slots()["out_channels"] == {"usb-mixer": 3}


def test_a_device_that_does_not_fit_is_parked(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path, channels=2)
    w.devices = [usb_device(1, "mixer"), usb_device(2, "synth")]
    d.scan_devices()
    assert d.bridges[("usb-mixer", IN)].start == 1
    parked = d.bridges[("usb-synth", IN)]
    assert parked.start is None and parked.routes() == []
    parked.tick({"bridge": {}}, w.now)
    assert parked.child is None   # a parked bridge never starts
    assert logged(w, "synth_in -> gadget IN parked: no free channels")
    d.reassign()
    assert len(logged(w, "synth_in -> gadget IN parked")) == 1   # said once
    status = {e["identity"]: e for e in d.status_data()["devices"]}
    assert status["usb-synth"][IN]["start"] is None


def test_unplugged_device_stops_its_bridges_and_keeps_its_slot(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"), usb_device(2, "synth"))
    assert len(zita_names(w)) == 4
    w.devices = [usb_device(2, "synth")]
    w.seconds(0.7)
    assert logged(w, "mixer (usb-mixer) unplugged")
    assert list(d.devices) == ["usb-synth"] and sorted(d.bridges) == [("usb-synth", IN), ("usb-synth", OUT)]
    assert zita_names(w) == ["synth_in", "synth_out"] and w.stopped == ["mixer_in", "mixer_out"]
    assert len(w.called("jack_disconnect")) == 4   # one at a time: jackd stays
    assert daemon.load_slots()["in"]["usb-mixer"] == 1   # remembered for when it returns
    assert d.bridges[("usb-synth", IN)].start == 3   # the others do not move
    w.devices = [usb_device(3, "mixer"), usb_device(2, "synth")]
    w.seconds(2)
    assert d.bridges[("usb-mixer", IN)].start == 1 and len(zita_names(w)) == 4


def test_reenumerated_device_gets_new_bridges_on_the_same_channels(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer", usbbus="001/002"))
    old = d.bridges[("usb-mixer", IN)]
    w.devices = [usb_device(4, "mixer", usbbus="001/009")]
    w.seconds(0.7)
    assert logged(w, "mixer (usb-mixer) re-enumerated")
    new = d.bridges[("usb-mixer", IN)]
    assert new is not old and new.start == 1 and new.dev.card == 4
    assert old.child is None and w.stopped[:2] == ["mixer_in", "mixer_out"]
    w.seconds(1.5)
    assert zita_names(w) == ["mixer_in", "mixer_out"] and len(w.live()) == 3


def test_a_change_from_the_command_line_moves_the_bridge(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer")]
    d.scan_devices()
    b = d.bridges[("usb-mixer", IN)]
    b.tick(d.cfg, w.now)   # running on channels 1-2
    daemon.cmd_change("assign usb-mixer in=5")
    d.scan_devices()
    assert b.start == 5 and b.child is None and logged(w, "mixer_in -> gadget IN 5-6")
    assert ("jack_disconnect", "mixer_in:capture_1", "system:playback_1") in w.calls   # from the old channels
    assert d.bridges[("usb-mixer", OUT)].start == 1


# --- standalone: no host, jackd on a local card ------------------------------------------------------------------

def alone(monkeypatch, tmp_path, *devices, **sections):
    w, d = make(monkeypatch, tmp_path, engine={"mode": "standalone"}, **sections)
    w.devices = list(devices)
    return w, d


def test_standalone_starts_jackd_on_the_dac_without_a_host(monkeypatch, tmp_path):
    w, d = alone(monkeypatch, tmp_path, usb_device(1, "mixer"))
    assert w.rates == (0, 0)
    w.run_loop(3)
    assert d.mode == "jack" and d.jack_ready and logged(w, "standalone on sndrpihifiberry, 2 ch at 48000 Hz")
    assert not logged(w, "host streaming") and not w.called("amixer", "-c", CARD, "contents")   # nobody asks the gadget
    jackd = w.children[0]
    assert jackd.cmd[:2] == ["jackd", "-R"] and "hw:sndrpihifiberry" in jackd.cmd
    alsa = jackd.cmd[jackd.cmd.index("alsa"):]
    assert alsa[:3] == ["alsa", "-d", "hw:sndrpihifiberry"] and "-P" in alsa   # playback only
    assert [alsa[alsa.index(k) + 1] for k in ("-r", "-p", "-n", "-o")] == ["48000", "256", "3", "2"]
    assert "-i" not in alsa
    assert zita_names(w) == ["mixer_in", "mixer_out"]
    assert w.connections == set()   # no gadget channels to connect to: routes only
    assert not (tmp_path / "slots.json").exists() and d.midi is None


def test_standalone_leaves_the_hosts_saved_slots_alone(monkeypatch, tmp_path):
    saved = {"in": {"usb-mixer": 5}, "in_channels": {"usb-mixer": 2}, "mute": {"in": ["usb-old"]}}
    (tmp_path / "slots.json").write_text(json.dumps(saved))
    w, d = alone(monkeypatch, tmp_path, usb_device(1, "mixer"))
    w.run_loop(3)
    assert json.loads((tmp_path / "slots.json").read_text()) == saved
    assert d.muted[IN] == {"usb-old"}   # the mutes and routes are the same in both modes


def test_standalone_routes_end_in_the_dac_and_unwanted_connections_go(monkeypatch, tmp_path):
    w, d = alone(monkeypatch, tmp_path, usb_device(1, "mixer"), usb_device(2, "tracker"))
    daemon.cmd_change("route usb-mixer local-dac")
    daemon.cmd_change("route usb-mixer usb-tracker")
    daemon.cmd_change("route usb-tracker local-dac")
    w.run_loop(3)
    w.seconds(1.5)
    both = {frozenset((f"{src}:capture_{k}", f"{dst}:playback_{k}")) for k in (1, 2)
            for src, dst in (("mixer_in", "system"), ("mixer_in", "tracker_out"), ("tracker_in", "system"))}
    assert w.connections == both   # a stereo pair, channel for channel; the DAC takes both sources (JACK sums)
    stray = frozenset(("tracker_in:capture_1", "system:playback_2"))   # not a route
    w.connections.add(stray)
    w.seconds(1.5)
    assert stray not in w.connections and w.connections == both
    daemon.cmd_change("unroute usb-mixer local-dac")
    w.seconds(1.5)
    assert w.connections == {c for c in both if not any(p.startswith("mixer_in") for p in c) or
                             any(p.startswith("tracker_out") for p in c)}


def test_standalone_status_lists_the_dac_as_a_destination_and_a_mute_cuts_it(monkeypatch, tmp_path):
    w, d = alone(monkeypatch, tmp_path, usb_device(1, "mixer"))
    daemon.cmd_change("route usb-mixer local-dac")
    w.run_loop(3)
    w.seconds(1)
    status = json.loads((tmp_path / "run" / "status.json").read_text())
    assert status["standalone"] == {"identity": "local-dac", "name": "pHAT DAC", "card": "sndrpihifiberry",
                                    "channels": 2, "rate": 48000}
    dac = status["devices"][-1]
    assert dac["identity"] == "local-dac" and dac["local"] is True and "in" not in dac
    assert dac[OUT] == {"channels": 2, "rate": 48000, "running": True, "muted": False, "fixed_level": True}
    assert status["routes"] == [{"src": "usb-mixer", "dst": "local-dac", "waiting": None}]
    daemon.cmd_change("mute local-dac out on")
    w.seconds(2.5)
    assert not any("system:playback_1" in c for c in w.connections)
    status = json.loads((tmp_path / "run" / "status.json").read_text())
    assert status["routes"][0]["waiting"] == "muted" and status["devices"][-1][OUT]["muted"] is True


def test_standalone_waits_instead_of_playing_silence_when_jackd_keeps_failing(monkeypatch, tmp_path):
    w, d = alone(monkeypatch, tmp_path)
    w.ptr_step = 0
    w.seconds(14)
    assert logged(w, "jackd failed 3 times in a row; waiting for 10 s")
    assert d.mode is None and d.target == "jack" and d.jackd is None and d.player is None
    assert not [c for c in w.children if c.name == "silence"]
    w.ptr_step = 48
    w.seconds(12)
    assert d.mode == "jack" and d.jackd and d.jackd.alive()   # and it tries again


def test_host_mode_is_what_an_unknown_mode_means(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path, engine={"mode": "stand-alone"})
    assert not d.standalone and logged(w, "mode 'stand-alone' is not host or standalone; using host")
    assert "standalone" not in d.status_data() and d.card == CARD


def test_status_cli_prints_the_standalone_engine(monkeypatch, tmp_path, capsys):
    w, d = alone(monkeypatch, tmp_path, usb_device(1, "mixer"))
    w.run_loop(3)
    w.seconds(1)
    monkeypatch.setattr(daemon, "STATUS", tmp_path / "run" / "status.json")
    daemon.cmd_status(None)
    out = capsys.readouterr().out
    assert "standalone: sndrpihifiberry, 2 ch at 48000 Hz; jackd up" in out
    assert "local output  running" in out and "capture  running" in out and "playback  running" in out
    assert "host IN" not in out and "parked" not in out


def test_cmd_takes_a_whole_command_the_way_the_display_service_sends_it(monkeypatch, tmp_path, capsys):
    make(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["rpi-audiod", "cmd", "route", "usb-a", "usb-b", "src=1", "dst=2"])
    daemon.main()
    saved = json.loads((tmp_path / "slots.json").read_text())
    assert saved["routes"] == [{"src": "usb-a", "dst": "usb-b", "dst_pair": 2}]
    assert "saved" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["rpi-audiod", "cmd", "route", "usb-a", "usb-a"])
    with pytest.raises(SystemExit) as stopped:
        daemon.main()
    assert str(stopped.value).startswith("rpi-audiod: ") and "itself" in str(stopped.value)


def test_slots_that_cannot_be_written_are_still_applied_in_memory(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer")]

    def fail(path, data):
        raise OSError("read-only file system")
    monkeypatch.setattr(daemon, "write_json", fail)
    d.scan_devices()
    assert logged(w, "cannot save") and d.bridges[("usb-mixer", IN)].start == 1
    assert not (tmp_path / "slots.json").exists()


def test_muted_routes_are_cut_and_come_back(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"))
    assert len(w.connections) == 4
    assert d.command("mute usb-mixer in on") == "ok"
    w.seconds(1.6)   # one scan, one route pass
    assert d.muted[IN] == {"usb-mixer"}
    assert w.connections == {frozenset(("system:capture_1", "mixer_out:playback_1")),
                             frozenset(("system:capture_2", "mixer_out:playback_2"))}
    assert logged(w, "muted mixer_in:capture_1 -> system:playback_1")
    assert d.command("mute usb-mixer in off") == "ok"
    w.seconds(1.6)
    assert len(w.connections) == 4 and not d.muted[IN]


def test_device_routes_connect_cut_and_leave_the_gadget_alone(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"), usb_device(2, "tracker"))
    gadget = set(w.connections)
    assert len(gadget) == 8   # mixer and tracker on the host's channels
    assert d.command("route usb-mixer usb-tracker") == "ok"
    w.seconds(1.6)
    mine = {frozenset(("mixer_in:capture_1", "tracker_out:playback_1")),
            frozenset(("mixer_in:capture_2", "tracker_out:playback_2"))}
    assert w.connections == gadget | mine
    assert d.status_data()["routes"] == [{"src": "usb-mixer", "dst": "usb-tracker", "waiting": None}]
    assert d.command("mute usb-tracker out on") == "ok"
    w.seconds(1.6)
    assert not mine & w.connections
    assert d.status_data()["routes"][0]["waiting"] == "muted"
    assert d.command("mute usb-tracker out off") == "ok"
    w.seconds(1.6)
    assert mine <= w.connections
    assert d.command("unroute usb-mixer usb-tracker") == "ok"
    w.seconds(1.6)
    assert not mine & w.connections and "routes" not in d.status_data()
    assert gadget <= w.connections   # the host's own routes were never touched


def test_a_route_to_a_device_that_is_not_here_waits(monkeypatch, tmp_path):
    w, d = bring_up(monkeypatch, tmp_path, usb_device(1, "mixer"))
    assert d.command("route usb-mixer usb-tracker") == "ok"
    w.seconds(1.6)
    assert d.status_data()["routes"][0]["waiting"] == "usb-tracker is not here"
    assert d.command("route usb-mixer usb-mixer").startswith("error:")


def test_connect_routes_waits_for_the_ports(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.devices = [usb_device(1, "mixer")]
    d.scan_devices()
    d.connect_routes()   # zita is not running: its ports do not exist
    assert not w.called("jack_connect") and not w.connections
    for b in d.bridges.values():
        b.tick(d.cfg, w.now)
    d.connect_routes()
    assert len(w.connections) == 4


def test_saved_levels_are_set_once_and_again_on_change_or_return(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.scontents["mixer"] = ("Simple mixer control 'PCM',0\n  Capabilities: pvolume pswitch\n"
                            "  Front Left: Playback 10 [10%] [on]\n"
                            "Simple mixer control 'Mic',0\n  Capabilities: cvolume\n")
    w.devices = [usb_device(1, "mixer")]
    d.command("volume usb-mixer out 70")
    d.command("volume usb-mixer in 30")
    d.scan_devices()
    assert w.called("amixer", "-q") == [("amixer", "-q", "-c", "mixer", "sset", "Mic,0", "capture", "30%"),
                                        ("amixer", "-q", "-c", "mixer", "sset", "PCM,0", "playback", "70%")]
    assert d.volumes == {("usb-mixer", IN): 30, ("usb-mixer", OUT): 70}
    d.scan_devices()
    assert len(w.called("amixer", "-q")) == 2   # unchanged: not set again
    d.command("volume usb-mixer out 50")
    d.scan_devices()
    assert w.called("amixer", "-q")[-1][-1] == "50%" and len(w.called("amixer", "-q")) == 3
    w.devices = []
    d.scan_devices()
    assert d.volumes == {}
    w.devices = [usb_device(2, "mixer")]
    d.scan_devices()   # back: the levels are set again
    assert len(w.called("amixer", "-q")) == 5


def test_a_device_that_comes_up_silent_is_raised_once_per_bus(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path, bridge={"min_volume": "60%"})
    w.scontents["mixer"] = ("Simple mixer control 'PCM',0\n  Capabilities: pvolume pswitch\n"
                            "  Front Left: Playback 0 [0%] [off]\n  Front Right: Playback 0 [0%] [off]\n")
    w.devices = [usb_device(1, "mixer")]
    d.scan_devices()
    assert w.called("amixer", "-q") == [("amixer", "-q", "-c", "mixer", "sset", "PCM,0", "60%", "unmute")]
    assert logged(w, "playback volume was 0, setting 60%")
    w.devices = []
    d.scan_devices()
    w.devices = [usb_device(1, "mixer")]
    d.scan_devices()   # same bus again: not raised a second time
    assert len(w.called("amixer", "-q")) == 1


def test_a_saved_level_replaces_the_silent_volume_fix(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    w.scontents["mixer"] = ("Simple mixer control 'PCM',0\n  Capabilities: pvolume\n"
                            "  Front Left: Playback 0 [0%] [off]\n")
    d.command("volume usb-mixer out 0")
    w.devices = [usb_device(1, "mixer")]
    d.scan_devices()
    assert w.called("amixer", "-q") == [("amixer", "-q", "-c", "mixer", "sset", "PCM,0", "playback", "0%")]


# --- the MIDI control port ---------------------------------------------------------------------

class Recorder:
    """A daemon that only notes what the control port asked of it."""

    def __init__(self):
        self.applied, self.commands = [], []

    def starts(self):
        return {IN: {1: "usb-a"}, OUT: {3: "usb-b"}}

    def apply(self, cmd):
        self.applied.append(cmd)
        return "ok"

    def command(self, text):
        self.commands.append(text)
        return {"ping": "ok rpi-audio"}.get(text, "ok")


def new_midi(w, ports=4, **m):
    return daemon.Midi({"midi": m}, ports, "MIDIGadget")


def sysex(text):
    return "sysex", bytes.fromhex(midi.sysex_hex(text).replace(" ", ""))


def reply_text(sysex):
    start = sysex.index(midi.REPLY_HEAD[1:]) + 3
    return sysex[start:sysex.index(b"\xf7", start)].decode()


def replies(m):
    out = []
    while not m.replies.empty():
        port, sysex = m.replies.get_nowait()
        out.append((port, reply_text(sysex)))
    return out


def test_midi_settings_are_checked(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w)
    assert (m.control, m.channels) == (1, (16, 15))
    m = new_midi(w, control_port=3, channel_in=2, channel_out=9)
    assert (m.control, m.channels) == (3, (2, 9))
    assert not w.logs
    m = new_midi(w, control_port=5)
    assert m.control == 1 and logged(w, "control_port 5 is not one of the gadget's 4 ports")
    m = new_midi(w, channel_in=4, channel_out=4)
    assert m.channels == (16, 15) and logged(w, "must be two channels 1..16")
    m = new_midi(w, channel_in=0)
    assert m.channels == (16, 15)


def test_a_sysex_command_reaches_the_daemon_and_the_reply_goes_back(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w, control_port=2)
    m.client = 40
    rec = Recorder()
    for text in ("ping", "status", "mute usb-a in on"):
        m.events.put(sysex(text))
    m.drain(rec)
    assert rec.commands == ["ping", "status", "mute usb-a in on"]
    assert replies(m) == [("40:1", "ok rpi-audio"), ("40:1", "ok"), ("40:1", "ok")]
    assert [line for line in w.logs if "MIDI command" in line] == ["rpi-audiod: MIDI command 'mute usb-a in on': ok"]


def test_sysex_that_is_not_a_command_is_ignored(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w)
    m.client = 40
    rec = Recorder()
    reply = bytes.fromhex(midi.sysex_hex("ok", reply=True).replace(" ", ""))   # our own reply, echoed back
    for data in (reply, b"\xf0\x7e\x00\x06\x01\xf7", b"\xf0\x7d\x52\x41ping\x01\xf7"):
        m.events.put(("sysex", data))
    m.events.put(("note", 1, 60))   # not a command at all
    m.drain(rec)
    assert not rec.commands and m.replies.empty() and not m.events.qsize()


def test_midi_commands_through_the_real_daemon(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w)
    m.client = 40
    for text in ("assign usb-a in=3", "bogus", "name usb-a " + "x" * 30, "status"):
        m.events.put(sysex(text))
    m.drain(d)
    answers = [text for _, text in replies(m)]
    assert answers[:3] == ["ok", "error: unknown command bogus", "error: name must be at most 24 characters"]
    assert json.loads(answers[3])["gadget_channels"] == 8
    assert daemon.load_slots()["in"] == {"usb-a": 3}


def test_midi_replies_pile_up_at_the_limit_and_non_ascii_is_replaced(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w)
    m.client = 40
    rec = Recorder()
    for _ in range(25):
        m.events.put(sysex("ping"))
    m.drain(rec)
    assert len(rec.commands) == daemon.MIDI_COMMANDS and m.events.qsize() == 5   # the rest wait for the next tick
    m.drain(rec)   # nothing sends the replies: the next five are dropped
    assert m.replies.qsize() == daemon.MIDI_COMMANDS and len(logged(w, "replies are piling up")) == 5
    m = new_midi(w)
    m.client = 40
    m.send("café")
    assert replies(m) == [("40:0", "error: the reply is not plain ASCII")]


def test_control_ccs_are_coalesced_and_program_change_comes_after_them(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w)
    rec = Recorder()
    events = (("cc", 16, 33, 10), ("cc", 16, 33, 50), ("cc", 16, 65, 64), ("cc", 16, 33, 127),   # IN side, device 1
              ("cc", 15, 35, 127),                                                           # OUT side, device 3
              ("cc", 15, 40, 127), ("cc", 14, 33, 1), ("cc", 16, 7, 100),                    # no device; not ours
              ("pc", 15, 1), ("pc", 16, 8))                                                  # not ours; no preset
    for event in events:
        m.events.put(event)
    m.drain(rec)
    assert [(c.verb, c.identity, c.arg("direction"), c.arg("percent"), c.arg("on")) for c in rec.applied] == [
        ("volume", "usb-a", IN, 100, None), ("mute", "usb-a", IN, None, True), ("volume", "usb-b", OUT, 100, None)]
    assert logged(w, "MIDI CC 40 on channel 15: no device there") and logged(w, "MIDI program 8 on channel 16")
    rec.applied.clear()
    for event in (("cc", 16, 33, 0), ("pc", 16, 2), ("cc", 16, 33, 127), ("pc", 16, 0)):
        m.events.put(event)
    m.drain(rec)
    assert [(c.verb, c.arg("percent"), c.arg("action"), c.arg("slot")) for c in rec.applied] == [
        ("volume", 0, None, None), ("preset", None, "load", 3),
        ("volume", 100, None, None), ("preset", None, "load", 1)]
    assert logged(w, "MIDI program 2: preset 3: ok")


def test_control_channels_are_the_configured_ones(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w, channel_in=3, channel_out=4)
    rec = Recorder()
    for event in (("cc", 16, 33, 127), ("cc", 3, 33, 127), ("pc", 16, 0), ("pc", 4, 0), ("pc", 3, 1)):
        m.events.put(event)
    m.drain(rec)
    assert [(c.verb, c.arg("direction") or c.arg("slot")) for c in rec.applied] == [("volume", IN), ("preset", 2)]


GADGET = "client 20: 'f_midi' [type=kernel,card=1]\n" + "".join(f"    {k} 'f_midi'\n" for k in range(4))
CAPS = """Client   0 : "System" [Kernel Legacy]
  Port   0 : "Timer" (Rwe-) [In/Out]
Client  20 : "f_midi" [Kernel Legacy]
  Port   0 : "f_midi" (RWeX) [In/Out]
  Port   1 : "f_midi" (RWeX) [In/Out]
Client  24 : "GP-150" [Kernel Legacy]
  Port   0 : "GP-150 MIDI 1" (RWeX) [In/Out]
"""
DEVICE = "client 24: 'GP-150' [type=kernel,card=2]\n    0 'GP-150 MIDI 1'\n"
CARDS = {2: "usb-gp"}


def midi_world(monkeypatch, tmp_path, aconnect=GADGET + DEVICE, udc="configured"):
    w, d = make(monkeypatch, tmp_path)
    w.aconnect, w.udc = aconnect, udc
    w.files["/proc/asound/seq/clients"] = CAPS
    return w, new_midi(w)


def test_midi_tick_listens_assigns_a_cable_and_subscribes(monkeypatch, tmp_path):
    w, m = midi_world(monkeypatch, tmp_path)
    m.tick(CARDS, w.now)
    assert m.client == 20 and logged(w, "gadget MIDI on sequencer client 20")
    assert m.listener.name == "midi-control" and m.listener.cmd == ["aseqdump", "-p", "20:0"]
    assert m.assigned == {"usb-gp/0": 2}   # cable 1 is the control port
    assert daemon.load_slots()["midi"] == {"usb-gp/0": 2}
    assert logged(w, "MIDI GP-150 (usb-gp/0) -> gadget MIDI port 2") and logged(w, "host connected: routing MIDI")
    assert {c[1:] for c in w.called("aconnect") if c[1] != "-l"} == {("24:0", "20:1"), ("20:1", "24:0")}
    assert m.status() == {"card": "MIDIGadget", "client": 20, "ports": 4, "control_port": 1, "host_connected": True,
                          "listening": True, "endpoints": [{"endpoint": "usb-gp/0", "port": 2}]}


def test_midi_tick_does_not_route_before_the_host_configures_the_gadget(monkeypatch, tmp_path):
    connected = (GADGET.replace("    1 'f_midi'\n", "    1 'f_midi'\n\tConnecting To: 24:0\n")
                 + DEVICE.replace("    0 'GP-150 MIDI 1'\n", "    0 'GP-150 MIDI 1'\n\tConnecting To: 20:1\n"))
    w, m = midi_world(monkeypatch, tmp_path, aconnect=connected, udc="")
    m.tick(CARDS, w.now)
    assert not m.configured and not logged(w, "routing MIDI")
    assert {c[1:] for c in w.called("aconnect") if c[1] != "-l"} == {("-d", "24:0", "20:1"), ("-d", "20:1", "24:0")}
    assert logged(w, "unsubscribed MIDI 24:0 -> 20:1")
    w.udc = "configured"
    w.aconnect = GADGET + DEVICE
    w.calls.clear()
    m.tick(CARDS, w.now + 1)
    assert logged(w, "host connected: routing MIDI") and len(w.called("aconnect", "24:0")) == 1
    w.udc = ""
    m.tick(CARDS, w.now + 2)
    assert logged(w, "host gone: unrouting MIDI")


def test_midi_tick_keeps_existing_subscriptions(monkeypatch, tmp_path):
    connected = (GADGET.replace("    1 'f_midi'\n", "    1 'f_midi'\n\tConnecting To: 24:0\n")
                 + DEVICE.replace("    0 'GP-150 MIDI 1'\n", "    0 'GP-150 MIDI 1'\n\tConnecting To: 20:1\n"))
    w, m = midi_world(monkeypatch, tmp_path, aconnect=connected)
    m.tick(CARDS, w.now)
    assert [c for c in w.called("aconnect") if c[1] != "-l"] == []


def test_midi_listener_is_restarted_after_it_dies_but_not_at_once(monkeypatch, tmp_path):
    w, m = midi_world(monkeypatch, tmp_path)
    m.tick(CARDS, 100.0)
    first = m.listener
    m.tick(CARDS, 101.0)   # alive, not yet seen subscribed, only 1 s: left alone
    assert m.listener is first
    first.die(1)
    m.tick(CARDS, 101.5)
    assert logged(w, "the MIDI control listener exited (code 1)") and m.listener is None   # next_listen is 102
    m.tick(CARDS, 102.0)
    assert m.listener and m.listener is not first and m.listener.alive()


def test_midi_listener_that_lost_its_subscription_is_restarted_after_three_seconds(monkeypatch, tmp_path):
    w, m = midi_world(monkeypatch, tmp_path)
    m.tick(CARDS, 100.0)
    first = m.listener
    subscribed = (GADGET.replace("    0 'f_midi'\n", "    0 'f_midi'\n\tConnecting To: 128:0\n", 1)
                  + DEVICE + f"client 128: 'aseqdump' [type=user,pid={first.proc.pid}]\n    0 'aseqdump'\n")
    w.aconnect = subscribed
    m.tick(CARDS, 110.0)   # subscribed: heard
    assert m.heard == 110.0 and m.listener is first
    w.aconnect = GADGET + DEVICE   # the gadget came back as a new client: no subscription
    m.tick(CARDS, 112.0)
    assert m.listener is first
    m.tick(CARDS, 113.5)
    assert logged(w, "lost its subscription") and m.listener is not first and not first.alive_


def test_midi_gadget_going_away_stops_the_listener(monkeypatch, tmp_path):
    w, m = midi_world(monkeypatch, tmp_path)
    m.tick(CARDS, 100.0)
    listener = m.listener
    w.gadget_card = None
    m.tick(CARDS, 101.0)
    assert logged(w, "gadget MIDI gone") and m.client is None and m.listener is None and not listener.alive_
    n = len(w.called("aconnect"))
    m.tick(CARDS, 102.0)
    assert len(w.called("aconnect")) == n + 1 and len(logged(w, "gadget MIDI gone")) == 1   # only -l, nothing else
    w.gadget_card = 1
    m.tick(CARDS, 103.0)
    assert m.client == 20 and m.listener


def test_midi_cables_that_cannot_be_saved_are_still_assigned(monkeypatch, tmp_path):
    w, m = midi_world(monkeypatch, tmp_path)

    def fail(path, data):
        raise OSError("read-only file system")
    monkeypatch.setattr(daemon, "write_json", fail)
    m.tick(CARDS, w.now)
    assert logged(w, "cannot save") and m.assigned == {"usb-gp/0": 2}


# --- the loop with MIDI -----------------------------------------------------------------------------

def test_a_midi_command_through_the_loop_changes_the_routes(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path, midi_ports=4)
    assert d.midi and d.midi.ports == 4
    w.devices = [usb_device(1, "mixer")]
    streaming(w)
    w.run_loop(3)
    assert len(w.connections) == 4
    d.midi.events.put(sysex("mute usb-mixer in on"))
    d.midi.events.put(("pc", 16, 4))   # an empty preset
    d.midi.events.put(sysex("ping"))
    w.seconds(1.6)
    assert [text for _, text in replies(d.midi)] == ["ok", f"ok rpi-audio {daemon.VERSION}"]
    assert logged(w, "MIDI command 'mute usb-mixer in on': ok") and logged(w, "MIDI program 4: preset 5: error")
    assert w.connections == {frozenset(("system:capture_1", "mixer_out:playback_1")),
                             frozenset(("system:capture_2", "mixer_out:playback_2"))}
    status = d.status_data()
    assert status["midi"]["ports"] == 4 and status["devices"][0][IN]["muted"] is True
    assert status["version"] == daemon.VERSION


def test_the_loop_with_midi_stops_its_listener(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path, midi_ports=4)
    w.aconnect, w.udc = GADGET + DEVICE, "configured"
    w.files["/proc/asound/seq/clients"] = CAPS
    w.run_loop(2)
    assert d.midi.listener and d.midi.listener.alive()
    listener = d.midi.listener
    w.run_loop(1, stop=True)
    assert not listener.alive_ and d.midi.listener is None


def test_a_status_file_that_cannot_be_written_is_retried_later(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    (tmp_path / "run").rmdir()
    w.run_loop(2)
    assert len(logged(w, "cannot write")) == 1 and d.next_status > w.now + 50   # no run dir: try again in a minute


# --- the reply sender ---------------------------------------------------------------------------

class FakeAsound:
    """libasound's raw MIDI calls, scripted: write_results is consumed one call at a time (None: write it all)."""

    def __init__(self, open_result=0, write_results=()):
        self.open_result, self.write_results = open_result, list(write_results)
        self.opened, self.closed, self.written = [], 0, b""

    def snd_rawmidi_open(self, inp, href, name, mode):
        self.opened.append((name, mode))
        if self.open_result == 0:
            href._obj.value = 1234
        return self.open_result

    def snd_rawmidi_write(self, handle, data, n):
        r = self.write_results.pop(0) if self.write_results else None
        if r is None or r > 0:
            k = n if r is None else min(r, n)
            self.written += data[:k]
            return k
        return r

    def snd_rawmidi_close(self, handle):
        self.closed += 1

    def snd_strerror(self, code):
        return b"error %d" % code


def test_raw_midi_writes_everything_and_keeps_the_device_open():
    lib = FakeAsound(write_results=[3, None])
    out = daemon.RawMidiOut("hw:CARD=MIDIGadget,DEV=0,SUBDEV=0", lib)
    out.write(b"\xf0\x7d\x52\x42ok\xf7")
    out.write(b"\xf0\x01\xf7")
    assert lib.written == b"\xf0\x7d\x52\x42ok\xf7\xf0\x01\xf7"
    assert lib.opened == [(b"hw:CARD=MIDIGadget,DEV=0,SUBDEV=0", daemon.RawMidiOut.NONBLOCK)] and lib.closed == 0


def test_raw_midi_writes_in_small_pieces_with_a_pause(monkeypatch):
    sizes, pauses = [], []
    lib = FakeAsound()
    write = lib.snd_rawmidi_write
    lib.snd_rawmidi_write = lambda h, data, n: sizes.append(n) or write(h, data, n)
    monkeypatch.setattr(daemon.time, "sleep", pauses.append)
    out = daemon.RawMidiOut("hw:CARD=MIDIGadget,DEV=0,SUBDEV=0", lib)
    data = bytes(range(128)) * 2
    out.write(data)
    assert lib.written == data
    assert sizes == [64, 64, 64, 64]
    assert pauses == [out.GAP] * 3


def test_raw_midi_waits_while_the_host_is_not_reading_then_gives_up(monkeypatch):
    lib = FakeAsound(write_results=[-11, -11, None])
    out = daemon.RawMidiOut("hw:X", lib)
    monkeypatch.setattr(daemon.time, "sleep", lambda s: None)
    out.write(b"\xf0\xf7")
    assert lib.written == b"\xf0\xf7"
    lib.write_results = [-11] * 1000
    clock = iter(range(0, 10000))
    monkeypatch.setattr(daemon.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError):
        out.write(b"\xf0\xf7", timeout=5)


def test_raw_midi_reopens_after_an_error():
    lib = FakeAsound(write_results=[-19])
    out = daemon.RawMidiOut("hw:X", lib)
    with pytest.raises(OSError):
        out.write(b"\xf0\xf7")
    assert lib.closed == 1 and out.handle is None
    out.write(b"\xf0\xf7")
    assert len(lib.opened) == 2 and lib.written == b"\xf0\xf7"


def test_raw_midi_open_failure_raises():
    out = daemon.RawMidiOut("hw:X", FakeAsound(open_result=-16))
    with pytest.raises(OSError, match="cannot open hw:X: error -16"):
        out.write(b"\xf0\xf7")


def test_replies_go_through_raw_midi_on_the_control_cable(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w, control_port=2)
    lib = FakeAsound()
    monkeypatch.setattr(daemon.RawMidiOut, "load", staticmethod(lambda: lib))
    monkeypatch.setattr(daemon.subprocess, "run", lambda *a, **k: pytest.fail("aplaymidi ran"))
    m.client = 40
    m.send("ok")
    m.send_one(*m.replies.get_nowait())
    assert lib.opened[0][0] == b"hw:CARD=MIDIGadget,DEV=0,SUBDEV=1" and reply_text(lib.written) == "ok"


def test_replies_fall_back_to_aplaymidi(monkeypatch, tmp_path):
    w, d = make(monkeypatch, tmp_path)
    m = new_midi(w)
    ran = []
    monkeypatch.setattr(daemon.subprocess, "run", lambda cmd, **k: ran.append((cmd, k["input"])))

    def no_lib():
        raise OSError("libasound.so.2: cannot open shared object file")
    monkeypatch.setattr(daemon.RawMidiOut, "load", staticmethod(no_lib))
    m.client = 40
    m.send("ok")
    m.send_one(*m.replies.get_nowait())
    assert ran and ran[0][0][:4] == ["aplaymidi", "-d", "0", "-p"] and ran[0][1].startswith(b"MThd")
    assert logged(w, "using aplaymidi")
    lib = FakeAsound(write_results=[-19])   # a device error sends that reply through aplaymidi
    m.raw = daemon.RawMidiOut("hw:X", lib)
    m.send("ok")
    m.send_one(*m.replies.get_nowait())
    assert len(ran) == 2 and logged(w, "goes through aplaymidi")
