# SPDX-License-Identifier: GPL-3.0-or-later
"""Real, isolated JACK verification of independent gains and the continuous session observer."""
import os
import signal
import subprocess
import time
import unittest

from test_native_meter import NativeMeter, AVAILABLE, ROOT


@unittest.skipUnless(AVAILABLE, 'native output gain tests need JACK headers, jackd and cc')
class NativeGain(NativeMeter):
    test_never_starts_a_server = None
    test_peaks_destination_taps_clipping_and_no_route_changes = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.gain = cls.folder / 'gain'
        subprocess.run(['cc', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'bridge/audio/gain.c'), '-ljack', '-lm', '-o', str(cls.gain)], check=True)

    def audio(self, rate=48000, period=256):
        name = 'gain_test_' + str(os.getpid())
        env = {**os.environ, 'JACK_DEFAULT_SERVER': name, 'JACK_NO_START_SERVER': '1'}
        server = self.start(['jackd', '--no-realtime', '--name', name, '-d', 'dummy',
                             '-r', str(rate), '-p', str(period)], env)
        for _ in range(100):
            if subprocess.run(['jack_lsp'], env=env, capture_output=True).returncode == 0:
                break
            self.assertIsNone(server.poll())
            time.sleep(0.05)
        else:
            self.fail('JACK test server failed')
        self.start([str(self.tone)], env)
        return env, server

    def controlled(self, env, name, level, channels=2):
        process = subprocess.Popen([str(self.gain), '--client', name, '--channels', str(channels),
                                    '--level', str(level)],
                                   env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, bufsize=0)
        self.addCleanup(self.stop, process)
        self.addCleanup(process.stdin.close)
        for _ in range(100):
            ports = subprocess.run(['jack_lsp'], env=env, capture_output=True, text=True).stdout
            if name + f':playback_{channels}' in ports and 'meter_test_tone:out_2' in ports:
                break
            self.assertIsNone(process.poll())
            time.sleep(0.03)
        for n in (1, 2):
            subprocess.run(['jack_connect', f'meter_test_tone:out_{n}', f'{name}:playback_{n}'],
                           env=env, capture_output=True, check=True)
        return process

    def test_independent_gains_live_updates_zero_and_no_server_restart(self):
        env, server = self.audio()
        local = self.controlled(env, 'test_dac_out', 50)
        usb = self.controlled(env, 'test_usb_out', 100)
        meter = self.start([str(self.helper), 'in=test_dac_out:capture_2', 'out=test_usb_out:capture_2'], env)
        frames = self.frames(meter, 1.2)
        self.assertTrue(any(abs(f['in'] - 0.25) < 0.001 and abs(f['out'] - 0.5) < 0.001 for f in frames))
        local.stdin.write(b'25\n')
        frames = self.frames(meter, 0.8)
        self.assertTrue(any(abs(f['in'] - 0.125) < 0.001 and abs(f['out'] - 0.5) < 0.001 for f in frames))
        local.stdin.write(b'0\n')
        frames = self.frames(meter, 0.8)
        self.assertTrue(any(f['in'] == 0 and abs(f['out'] - 0.5) < 0.001 for f in frames))
        local.stdin.write(b'bad\n101\n')
        frames = self.frames(meter, 0.5)
        self.assertTrue(all(f['in'] == 0 for f in frames if f['in'] is not None))
        self.assertIsNone(local.poll())
        self.assertIsNone(usb.poll())
        self.assertIsNone(server.poll())

    def test_all_usb_channels_at_44100_and_64_frame_period(self):
        env, server = self.audio(rate=44100, period=64)
        gain = self.controlled(env, 'usb_26_out', 50, channels=26)
        subprocess.run(['jack_connect', 'meter_test_tone:out_2', 'usb_26_out:playback_26'],
                       env=env, check=True, capture_output=True)
        meter = self.start([str(self.helper), 'in=usb_26_out:capture_1', 'out=usb_26_out:capture_26'], env)
        frames = self.frames(meter, 1.3)
        self.assertTrue(any(f['in'] is not None and f['out'] is not None and
                            abs(f['in'] - 0.125) < 0.001 and abs(f['out'] - 0.25) < 0.001 for f in frames))
        self.assertIsNone(gain.poll())
        self.assertIsNone(server.poll())

    def test_session_observer_reports_without_any_meter_view_and_detects_xrun(self):
        env, server = self.audio()
        observer = self.start([str(self.gain), '--client', 'observer_test', '--channels', '0'], env)
        frames = self.frames(observer, 1.2)
        self.assertTrue(frames and frames[-1]['rate'] == 48000 and frames[-1]['period'] == 256)
        before = frames[-1]['xruns']
        os.kill(server.pid, signal.SIGSTOP)
        time.sleep(0.15)
        os.kill(server.pid, signal.SIGCONT)
        frames = self.frames(observer, 1.5)
        self.assertTrue(any(frame['xruns'] > before for frame in frames), 'observer missed forced JACK xrun')
        self.assertIsNone(observer.poll())

    def test_gain_never_starts_a_server(self):
        result = subprocess.run([str(self.gain)], env={**os.environ, 'JACK_DEFAULT_SERVER': 'absent_gain_test'},
                                capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
