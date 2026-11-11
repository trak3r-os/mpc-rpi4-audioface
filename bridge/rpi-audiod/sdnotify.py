# SPDX-License-Identifier: GPL-3.0-or-later
"""The two sd_notify(3) messages rpi-audiod needs, without libsystemd: READY=1 and WATCHDOG=1.

systemd gives a Type=notify service NOTIFY_SOCKET (a datagram socket: a path, or "@name" in the
abstract namespace) and, with WatchdogSec=, WATCHDOG_USEC (and WATCHDOG_PID). Once the service
says READY=1, systemd kills and restarts it when no WATCHDOG=1 arrives within WATCHDOG_USEC.
Without NOTIFY_SOCKET (run by hand, tests) every call does nothing.

The variables are taken out of os.environ, so jackd, the bridges and other children do not see
them: only the main process may speak for the service (NotifyAccess=main).
"""

import os
import socket

PING_S = 1.0   # at most one WATCHDOG=1 per second, however fast the caller's loop runs


def address(value):
    """The socket address of a NOTIFY_SOCKET value, or None for an empty or unsupported one
    (vsock and other forms are not used for system services)."""
    if value.startswith("@") and len(value) > 1:
        return "\0" + value[1:]
    if value.startswith("/"):
        return value
    return None


class Notifier:
    def __init__(self, environ=None, pid=None, log=None):
        env = os.environ if environ is None else environ
        self.addr = address(env.pop("NOTIFY_SOCKET", ""))
        usec = env.pop("WATCHDOG_USEC", "")
        owner = env.pop("WATCHDOG_PID", "")
        pid = os.getpid() if pid is None else pid
        try:
            interval = int(usec) / 1e6
        except ValueError:
            interval = 0.0
        if owner and owner != str(pid):
            interval = 0.0   # the watchdog is armed for another process
        # Send well inside the timeout: a stall shorter than about WATCHDOG_USEC - PING_S is tolerated.
        self.every = min(PING_S, interval / 4) if interval > 0 and self.addr else 0.0
        self.log = log or (lambda text: None)
        self.sock = None
        self.next_ping = 0.0
        self.said_ready = False
        self.failed = False

    @property
    def watchdog_enabled(self):
        return self.every > 0

    def send(self, text):
        """One datagram; never blocks and never raises (a full or missing socket only skips it)."""
        if not self.addr:
            return False
        try:
            if self.sock is None:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
                self.sock.setblocking(False)
            self.sock.sendto(text.encode(), self.addr)
            return True
        except OSError as e:
            if not self.failed:
                self.log(f"sd_notify: cannot send {text!r}: {e}")
            self.failed = True
            return False

    def ready(self):
        """Start-up finished: systemd starts the units ordered after this one, and arms the watchdog."""
        if not self.said_ready:
            self.said_ready = self.send("READY=1")

    def watchdog(self, now):
        """Called from the main loop with time.monotonic(); sends WATCHDOG=1 at most every self.every s."""
        if self.every and now >= self.next_ping:
            self.send("WATCHDOG=1")
            self.next_ping = now + self.every

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
