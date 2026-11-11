# SPDX-License-Identifier: GPL-3.0-or-later
"""sd_notify without libsystemd (bridge/rpi-audiod/sdnotify.py), against real datagram sockets."""

import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"))
import sdnotify  # noqa: E402


@pytest.fixture
def listener():
    """A socket like systemd's NOTIFY_SOCKET, in a short directory (AF_UNIX paths are limited to 108 bytes)."""
    folder = tempfile.mkdtemp(prefix="sdn")
    path = os.path.join(folder, "notify")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(path)
    sock.settimeout(1)
    yield path, sock
    sock.close()
    os.unlink(path)
    os.rmdir(folder)


def pending(sock):
    sock.setblocking(False)
    out = []
    while True:
        try:
            out.append(sock.recv(256).decode())
        except BlockingIOError:
            return out


def test_ready_then_rate_limited_watchdog_on_a_path_socket(listener):
    path, sock = listener
    env = {"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "30000000", "WATCHDOG_PID": "42", "PATH": "/bin"}
    n = sdnotify.Notifier(env, pid=42)
    assert env == {"PATH": "/bin"}   # children (jackd, the bridges) must not inherit them
    assert n.watchdog_enabled and n.every == sdnotify.PING_S
    n.ready()
    n.ready()   # said once
    for t in (100.0, 100.1, 100.5, 101.0, 101.2, 102.5):
        n.watchdog(t)
    assert pending(sock) == ["READY=1", "WATCHDOG=1", "WATCHDOG=1", "WATCHDOG=1"]
    n.close()


def test_short_timeouts_are_petted_four_times_per_period(listener):
    path, sock = listener
    n = sdnotify.Notifier({"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "2000000"}, pid=1)
    assert n.every == pytest.approx(0.5)


def test_abstract_namespace_socket():
    name = f"rpi-audio-test-{os.getpid()}"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind("\0" + name)
    sock.settimeout(1)
    try:
        n = sdnotify.Notifier({"NOTIFY_SOCKET": "@" + name}, pid=1)
        assert not n.watchdog_enabled   # no WatchdogSec=: READY=1 only
        n.ready()
        n.watchdog(5.0)
        assert pending(sock) == ["READY=1"]
    finally:
        sock.close()


def test_watchdog_of_another_process_is_not_ours(listener):
    path, sock = listener
    n = sdnotify.Notifier({"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "30000000", "WATCHDOG_PID": "7"}, pid=8)
    assert not n.watchdog_enabled
    n.watchdog(1.0)
    n.ready()
    assert pending(sock) == ["READY=1"]


@pytest.mark.parametrize("value", ["", "@", "vsock:2:1234", "relative/path"])
def test_no_usable_socket_does_nothing(value):
    logs = []
    n = sdnotify.Notifier({"NOTIFY_SOCKET": value, "WATCHDOG_USEC": "30000000"}, pid=1, log=logs.append)
    assert not n.watchdog_enabled
    n.ready()
    n.watchdog(1.0)
    assert n.sock is None and logs == []


def test_a_vanished_socket_is_logged_once_and_never_raises(listener):
    path, sock = listener
    logs = []
    n = sdnotify.Notifier({"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "4000000"}, pid=1, log=logs.append)
    os.unlink(path)
    n.ready()
    n.watchdog(1.0)
    n.watchdog(3.0)
    assert not n.said_ready and len(logs) == 1 and "READY=1" in logs[0]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as back:   # systemd back (the fixture removes the file)
        back.bind(path)
        n.ready()
        assert n.said_ready and pending(back) == ["READY=1"]
