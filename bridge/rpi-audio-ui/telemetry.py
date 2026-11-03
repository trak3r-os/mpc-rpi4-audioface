# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only hardware snapshots for the panel, collected away from its input loop."""

import re
import json
import subprocess
import sys as python_sys
from pathlib import Path

# The daemon's pure identity rules must also identify MIDI-only cards while audio is idle.
SHARED = Path(__file__).resolve().parent.parent
python_sys.path.extend((str(SHARED), str(SHARED / "rpi-audiod")))
import audiod  # noqa: E402

POLL_S = 2.0


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def wifi(proc, sys, run):
    blocked = any(read(p / "type") == "wlan" and (read(p / "soft") == "1" or read(p / "hard") == "1")
                  for p in (sys / "class/rfkill").glob("rfkill*"))
    out = {"state": "off" if blocked else "down", "name": "", "ip": "", "signal": None}
    if not (sys / "class/net/wlan0").exists():
        out["state"] = "missing"
        return out
    try:
        result = run(["nmcli", "--escape", "no", "--get-values", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS",
                      "device", "show", "wlan0"], capture_output=True, text=True, timeout=2)
        lines = result.stdout.splitlines()
        if result.returncode == 0 and len(lines) >= 2:
            out.update(state="up" if lines[0].startswith("100 ") else out["state"],
                       name=lines[1] if lines[1] != "--" else "",
                       ip=lines[2].split("/")[0] if len(lines) > 2 else "")
        elif not blocked:
            out["state"] = "unknown"
    except (OSError, subprocess.TimeoutExpired):
        out["state"] = "off" if blocked else "unknown"
    for line in read(proc / "net/wireless").splitlines():
        if line.strip().startswith("wlan0:"):
            try:
                out["signal"] = min(100, max(0, round(float(line.split()[2].rstrip(".")) * 100 / 70)))
            except (ValueError, IndexError):
                pass
    return out


def sound_devices(proc, sys=Path("/sys")):
    """Physical USB audio/MIDI cards and the pHAT; exclude HDMI, headphones and the gadget itself."""
    devices = []
    for card in sorted((proc / "asound").glob("card[0-9]*"), key=lambda p: int(p.name[4:])):
        identity = read(card / "id")
        usbid = read(card / "usbid")
        local = identity == "sndrpihifiberry"
        if not usbid and not local:
            continue
        device = {"card": identity, "identity": "card:" + identity, "name": identity,
                  "local": local, "usb_id": usbid, "midi": any(card.glob("midi*"))}
        if usbid:
            path = (sys / "class/sound" / card.name / "device").resolve()
            for parent in list(path.parents)[:3]:
                if read(parent / "idVendor"):
                    device["identity"] = audiod.identity(read(parent / "idVendor"), read(parent / "idProduct"),
                                                         read(parent / "serial"), parent.name)
                    break
        for stream in sorted(card.glob("stream[0-9]*")):
            text = read(stream)
            if " : " in text.split("\n")[0]:
                device["name"] = text.split("\n")[0].split(" at ", 1)[0].split(" : ", 1)[0]
            sections = re.split(r"(?m)^(Playback|Capture):\s*$", text)
            for section, contents in zip(sections[1::2], sections[2::2]):
                channels = [int(n) for n in re.findall(r"Channels:\s*(\d+)", contents)]
                side = "in" if section == "Capture" else "out"
                if channels:
                    device[side] = {"channels": max(max(channels), device.get(side, {}).get("channels", 0))}
        if local:
            device.update(name="pHAT DAC", out={"channels": 2, "fixed_level": True})
        elif not any(k in device for k in ("in", "out")) and not device["midi"]:
            continue
        devices.append(device)
    for device, identity in zip(devices, audiod.dedupe([d["identity"] for d in devices])):
        device["identity"] = identity
    return devices


def machine(proc, sys):
    out = {}
    try:
        fields = next(line.split()[1:9] for line in read(proc / 'stat').splitlines() if line.startswith('cpu '))
        values = list(map(int, fields))
        out['cpu_times'] = (sum(values), values[3] + values[4])
    except (StopIteration, ValueError, IndexError):
        pass
    try:
        memory = {line.split(':', 1)[0]: int(line.split()[1]) for line in read(proc / 'meminfo').splitlines()}
        out['memory_pct'] = 100 * (1 - memory['MemAvailable'] / memory['MemTotal'])
    except (KeyError, ValueError, IndexError, ZeroDivisionError):
        pass
    for key, path, divisor in (('temperature', sys / 'class/thermal/thermal_zone0/temp', 1000),
                               ('uptime', proc / 'uptime', 1)):
        try:
            out[key] = float(read(path).split()[0]) / divisor
        except (ValueError, IndexError):
            pass
    return out


def pcm_status(proc):
    out = {}
    for card in (proc / 'asound').glob('card[0-9]*'):
        identity = read(card / 'id')
        for suffix, side in (('c', 'in'), ('p', 'out')):
            directory = card / ('pcm0' + suffix) / 'sub0'
            info = {}
            for line in read(directory / 'hw_params').splitlines():
                fields = line.split(':', 1)
                fields[0] = fields[0].strip()
                if len(fields) == 2 and fields[0] in ('rate', 'channels', 'period_size', 'buffer_size'):
                    try:
                        info[fields[0]] = int(fields[1].split()[0])
                    except (ValueError, IndexError):
                        pass
            for line in read(directory / 'status').splitlines():
                fields = line.split(':', 1)
                fields[0] = fields[0].strip()
                if len(fields) == 2 and fields[0] in ('avail', 'delay', 'avail_max'):
                    try:
                        info[fields[0]] = int(fields[1].strip())
                    except ValueError:
                        pass
                elif len(fields) == 2 and fields[0] == 'state':
                    info['state'] = fields[1].strip()
            if info:
                out[identity + '/' + side] = info
    return out


def collect(proc=Path("/proc"), sys=Path("/sys"), run=subprocess.run,
            state=Path("/var/lib/rpi-audio/slots.json")):
    states = [read(p / "state") for p in sorted((sys / "class/udc").glob("*"))]
    try:
        saved = json.loads(read(state))
        assignments = {k: saved.get(k, {}) for k in ("in", "out", "in_channels", "out_channels", "midi", "names")}
    except (ValueError, AttributeError):
        assignments = {}
    return {"wifi": wifi(proc, sys, run), "usb_state": next((s for s in states if s), "unknown"),
            "devices": sound_devices(proc, sys), "assignments": assignments,
            "machine": machine(proc, sys), "pcm": pcm_status(proc)}


class Monitor:
    """One in-flight background read at most. read() never waits for subprocesses or filesystem scans."""

    def __init__(self, submit, collector=collect):
        self.submit, self.collector = submit, collector
        self.value, self.future, self.next_at = {}, None, 0.0
        self.previous_cpu = None

    def read(self, now):
        if self.future is not None and self.future.done():
            try:
                self.value = self.future.result()
                machine = self.value.get('machine', {})
                current = machine.get('cpu_times')
                if current and self.previous_cpu:
                    total = current[0] - self.previous_cpu[0]
                    idle = current[1] - self.previous_cpu[1]
                    if total > 0 and 0 <= idle <= total:
                        machine['cpu_pct'] = 100 * (total - idle) / total
                if current:
                    self.previous_cpu = current
            except Exception:
                self.value = {}
            self.future = None
        if self.future is None and now >= self.next_at:
            self.future = self.submit(self.collector)
            self.next_at = now + POLL_S
        return self.value
