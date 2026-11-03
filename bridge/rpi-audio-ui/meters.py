# SPDX-License-Identifier: GPL-3.0-or-later
"""Nonblocking control of the native, passive JACK peak reader. Never starts an audio server."""

import json
import math
import os
import subprocess
import re
import health
from pathlib import Path

STALE_S = 0.7
RETRY_S = 5.0
HELPER = Path(__file__).with_name("rpi-audio-meter")


def ports(status):
    if not status.get("jack_ready"):
        return ()
    targets = []
    if status.get('_meter_detail'):
        for endpoint in health.endpoints(status)[:64]:
            if not endpoint.get('running') or not endpoint.get('client'):
                continue
            prefix = 'capture' if endpoint['side'] == 'in' else 'playback'
            targets += [f"{endpoint['meter']}={endpoint['client']}:{prefix}_{n}"
                        for n in range(1, endpoint.get('channels', 0) + 1)]
        return tuple(targets)[:128]
    alone = status.get("standalone") or status.get("hub")
    if alone:
        for dev in status.get("devices", []):
            info = dev.get("in", {})
            if info.get("running") and info.get("client"):
                targets += [f"in={info['client']}:capture_{n}" for n in range(1, info.get("channels", 0) + 1)]
        targets += [f"out=system:playback_{n}" for n in range(1, alone.get("channels", 2) + 1)]
        if status.get("hub"):
            for output in status.get("outputs", []):
                if output.get("enabled") and output.get("running") and output.get("client") != "system":
                    targets += [f"out={output['client']}:playback_{n}"
                                for n in range(1, output.get("channels", 2) + 1)]
    else:
        for n in range(1, status.get("gadget_channels", 0) + 1):
            targets += [f"in=system:playback_{n}", f"out=system:capture_{n}"]
    return tuple(dict.fromkeys(targets))[:128]


def packet(line):
    try:
        data = json.loads(line)
        if not isinstance(data, dict) or not {"in", "out"} <= data.keys():
            return None
        result = {}
        for side in data:
            if (side not in ('in', 'out', '_xruns', '_rate', '_period', '_dsp_load') and
                    not re.fullmatch(r'p[0-9]{1,2}', side)):
                continue
            value = data[side]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value < 0):
                return None
            result[side] = value
        return result
    except (ValueError, TypeError):
        return None


class Reader:
    def __init__(self, helper=HELPER, popen=subprocess.Popen):
        self.helper, self.popen = helper, popen
        self.proc, self.retired, self.target = None, [], ()
        self.value, self.received, self.next_try = {}, float("-inf"), 0.0
        self.buffer = b""

    def stop(self, now):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
            self.retired.append((self.proc, now + 0.5))
        self.proc, self.value, self.buffer = None, {}, b""
        self.received = float("-inf")

    def read(self, status, now, enabled=True):
        waiting = []
        for proc, deadline in self.retired:
            if proc.poll() is None:
                if now >= deadline:
                    proc.kill()
                waiting.append((proc, deadline))
            else:
                proc.stdout.close()
        self.retired = waiting
        target = ports(status) if enabled else ()
        if target != self.target:
            self.stop(now)
            self.target, self.next_try = target, now
        if not target:
            return {}
        if self.proc is not None and self.proc.poll() is not None:
            self.stop(now)
        if self.proc is None and now >= self.next_try:
            self.next_try = now + RETRY_S
            try:
                self.proc = self.popen([str(self.helper), *target], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       stdin=subprocess.DEVNULL, bufsize=0,
                                       env={**os.environ, "JACK_NO_START_SERVER": "1"})
                os.set_blocking(self.proc.stdout.fileno(), False)
            except OSError:
                self.stop(now)
        if self.proc is not None:
            try:
                chunk = os.read(self.proc.stdout.fileno(), 8192)
                self.buffer += chunk
            except BlockingIOError:
                pass
            except OSError:
                self.stop(now)
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                value = packet(line)
                if value is not None:
                    self.value, self.received = value, now
            if len(self.buffer) > 8192:
                self.buffer = b""
        return dict(self.value) if now - self.received < STALE_S else {}

    def close(self):
        self.stop(0.0)
        for proc, _ in self.retired:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.stdout.close()
        self.retired = []
