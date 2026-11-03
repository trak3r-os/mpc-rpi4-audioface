# SPDX-License-Identifier: GPL-3.0-or-later
"""Native network integration on an isolated JACK server; runnable without pytest on a Pi."""
import json
import os
import socket
import queue
import threading
import struct
import subprocess
import time
import unittest
from pathlib import Path

from test_native_meter import NativeMeter, AVAILABLE, ROOT

HELPER = Path(os.environ.get('RPI_NETWORK_HELPER', ROOT / 'out/network/rpi-audio-network'))
RECEIVER = Path(os.environ.get('RPI_LINK_RECEIVER', ROOT / 'out/network/link-receiver'))


@unittest.skipUnless(AVAILABLE and HELPER.exists(), 'build network helper first; needs JACK dev tools')
class NativeNetwork(NativeMeter):
    # Only inherit the fixtures, not the meter test cases.
    test_never_starts_a_server = None
    test_peaks_destination_taps_clipping_and_no_route_changes = None

    def collect(self, udp):
        packets = queue.Queue()
        stopping = threading.Event()
        self.addCleanup(stopping.set)
        udp.settimeout(0.1)

        def read():
            while not stopping.is_set():
                try:
                    packets.put(udp.recv(1500))
                except socket.timeout:
                    pass
                except OSError:
                    break
        threading.Thread(target=read, daemon=True).start()
        return packets

    def setup_audio(self):
        name = 'network_test_' + str(os.getpid())
        env = {**os.environ, 'JACK_DEFAULT_SERVER': name, 'JACK_NO_START_SERVER': '1'}
        server = self.start(['jackd', '--no-realtime', '--name', name, '-d', 'dummy', '-r', '48000', '-p', '256'], env)
        for _ in range(100):
            if subprocess.run(['jack_lsp'], env=env, capture_output=True).returncode == 0:
                break
            self.assertIsNone(server.poll())
            time.sleep(0.05)
        else:
            self.fail('isolated JACK server failed to start')
        self.start([str(self.tone)], env)
        time.sleep(0.15)
        return env

    def connect(self, env, client):
        for _ in range(100):
            result = subprocess.run(['jack_lsp'], env=env, capture_output=True, text=True)
            if client + ':playback_2' in result.stdout:
                break
            time.sleep(0.05)
        else:
            self.fail('network JACK ports did not appear')
        for n in (1, 2):
            subprocess.run(['jack_connect', f'meter_test_tone:out_{n}', f'{client}:playback_{n}'], env=env,
                           capture_output=True, check=True)

    def test_adapter_never_starts_a_server(self):
        env = {**os.environ, 'JACK_DEFAULT_SERVER': 'absent_network_test'}
        result = subprocess.run([str(HELPER)], env=env, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        self.assertIn('JACK server', json.loads(result.stdout)['error'])

    def test_rtp_pcm_timestamps_rtcp_and_sdp(self):
        env = self.setup_audio()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rtcp:
            # Ask the OS for a free even RTP/RTCP pair.
            for port in range(28000, 29000, 2):
                try:
                    udp.bind(('127.0.0.1', port))
                    rtcp.bind(('127.0.0.1', port + 1))
                    break
                except OSError:
                    self.fail('test port pair unavailable')
            packets = self.collect(udp)
            rtcp.settimeout(3)
            sdp = self.folder / 'network.sdp'
            publisher = self.start([str(HELPER), '--address', '127.0.0.1', '--port', str(port),
                                    '--sdp', str(sdp)], env)
            self.connect(env, 'network_rtp_out')
            time.sleep(0.1)
            while not packets.empty():
                packets.get_nowait()  # discard the initial silence and sequential port-connection transition
            deadline = time.monotonic() + 3
            received, previous = 0, None
            while time.monotonic() < deadline:
                packet = packets.get(timeout=3)
                version, payload, sequence, timestamp, ssrc = struct.unpack('!BBHII', packet[:12])
                self.assertEqual((version, payload), (128, 96))
                frames = (len(packet) - 12) // 4
                self.assertTrue(0 < frames <= 48)
                samples = struct.unpack('!' + str(frames * 2) + 'h', packet[12:])
                if previous:
                    self.assertEqual(sequence, (previous[0] + 1) % 65536)
                    # A JACK xrun may skip samples; RTP timestamps must preserve the gap.
                    self.assertGreaterEqual((timestamp - previous[1]) % 2**32, previous[2])
                previous = (sequence, timestamp, frames)
                left, right = samples[::2], samples[1::2]
                if frames == 48 and max(left) >= 8190 and min(left) <= -8190:
                    self.assertTrue(all(abs(b - 2 * a) <= 2 for a, b in zip(left, right)))
                    self.assertTrue(16380 <= max(right) <= 16384)
                    received += 1
                    if received == 100:
                        break
            self.assertEqual(received, 100, 'did not receive stereo test tone')
            report = rtcp.recv(1500)
            self.assertEqual((len(report), report[1], report[29]), (56, 200, 202))
            self.assertEqual(struct.unpack('!I', report[4:8])[0], ssrc)
            self.assertIn('a=rtpmap:96 L16/48000/2', sdp.read_text())
            self.assertIn('m=audio ' + str(port), sdp.read_text())
            self.assertIsNone(publisher.poll())

    @unittest.skipUnless(RECEIVER.exists(), 'build the Link SDK receiver fixture first')
    def test_link_sdk_peer_receives_stereo_pcm(self):
        env = self.setup_audio()
        peer = 'network-test-' + str(os.getpid())
        publisher = self.start([str(HELPER), '--transport', 'link', '--client', 'network_link_out',
                                '--peer', peer], env)
        self.connect(env, 'network_link_out')
        result = subprocess.run([str(RECEIVER)], env={**os.environ, 'RPI_LINK_TEST_PEER': peer},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        received = json.loads(result.stdout)
        self.assertGreaterEqual(received['buffers'], 50)
        self.assertEqual((received['left'], received['right'], received['rate']), (8192, 16384, 48000))
        self.assertIsNone(publisher.poll())


if __name__ == '__main__':
    unittest.main(verbosity=2)
