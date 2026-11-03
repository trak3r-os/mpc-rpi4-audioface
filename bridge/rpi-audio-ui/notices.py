# SPDX-License-Identifier: GPL-3.0-or-later
"""Brief, bounded connection notices. Baseline snapshots do not announce devices already plugged in."""

from collections import deque

import ui

SHOW_S = 3.0


class Notifier:
    def __init__(self):
        self.previous, self.blocked = None, {}
        self.queue = deque(maxlen=8)
        self.current, self.until = (), 0.0
        self.changed = False

    def dismiss(self):
        self.current, self.until = (), 0.0
        self.queue.clear()

    def read(self, status, hardware, now):
        self.changed = False
        if "devices" in hardware:
            devices = {d.get("card") or d["identity"]: d for d in ui.inventory(status, hardware)}
            wifi = hardware.get("wifi", {}).get("state", "unknown")
            usb = hardware.get("usb_state", "unknown")
            snapshot = (devices, wifi, usb)
            if self.previous is not None:
                before, old_wifi, old_usb = self.previous
                for key in sorted(devices.keys() - before.keys()):
                    dev = devices[key]
                    self.queue.append((f"+ {ui.device_label(dev)}", ui.device_mode(dev)))
                for key in sorted(before.keys() - devices.keys()):
                    self.queue.append((f"- {ui.device_label(before[key])}", "Device disconnected"))
                if wifi != old_wifi and wifi != "unknown" and old_wifi != "unknown":
                    self.queue.append(("WiFi connected", hardware.get("wifi", {}).get("name", "")) if wifi == "up"
                                      else ("WiFi disconnected", "Check access point"))
                if usb != old_usb and usb != "unknown" and old_usb != "unknown":
                    if usb == "configured":
                        self.queue.append(("USB host connected", "Bridge ready to use"))
                    elif usb == "not attached":
                        self.queue.append(("USB host unplugged", "Bridge disconnected"))
            self.previous = snapshot
        if status:
            blocked = {}
            for dev in status.get("devices", []):
                for side in ("in", "out"):
                    info = dev.get(side, {})
                    why = info.get("blocked")
                    if not why and not (status.get("standalone") or status.get("hub")) and info and \
                            info.get("start", 1) is None:
                        why = "no free channels"
                    if why:
                        blocked[(dev["identity"], side)] = why
                        if self.blocked.get((dev["identity"], side)) != why:
                            if "budget" in why.lower():
                                title, detail = f"USB full: {ui.device_label(dev)}", "Unplug unused device"
                            elif "channels" in why.lower():
                                title, detail = "No free USB channels", "Review channel map"
                            else:
                                title, detail = "Device cannot start", "Check device details"
                            self.queue.append((title, detail))
            self.blocked = blocked
        if now >= self.until:
            self.current = ()
            if self.queue:
                self.current = self.queue.popleft()
                self.until, self.changed = now + SHOW_S, True
        return self.current
