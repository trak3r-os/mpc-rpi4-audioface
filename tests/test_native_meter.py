# SPDX-License-Identifier: GPL-3.0-or-later
"""Real JACK integration, isolated from hardware. Also runnable on the Pi with plain Python (no pytest)."""

import json
import os
import selectors
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AVAILABLE = shutil.which("cc") and shutil.which("jackd") and Path("/usr/include/jack/jack.h").exists()


@unittest.skipUnless(AVAILABLE, "native meter integration needs JACK headers, jackd and cc")
class NativeMeter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rpi-meter-test-")
        cls.folder = Path(cls.temp.name)
        cls.helper, cls.tone = cls.folder / "meter", cls.folder / "tone"
        for source, output in ((ROOT / "bridge/rpi-audio-ui/meter.c", cls.helper),
                               (ROOT / "tests/helpers/meter-tone.c", cls.tone)):
            subprocess.run(["cc", "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source),
                            "-ljack", "-lm", "-o", str(output)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def stop(self, proc):
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if proc.stdout:
            proc.stdout.close()

    def start(self, command, env):
        proc = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.addCleanup(self.stop, proc)
        return proc

    def frames(self, proc, seconds=1.0):
        found, buffer = [], b""
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if not selector.select(max(0, deadline - time.monotonic())):
                    break
                data = os.read(proc.stdout.fileno(), 8192)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    found.append(json.loads(line))
        return found

    def test_never_starts_a_server(self):
        env = {**os.environ, "JACK_DEFAULT_SERVER": "absent_" + uuid.uuid4().hex[:10]}
        result = subprocess.run([str(self.helper), "in=system:capture_1"], env=env, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")

    def test_peaks_destination_taps_clipping_and_no_route_changes(self):
        name = "meter_test_" + uuid.uuid4().hex[:8]
        env = {**os.environ, "JACK_DEFAULT_SERVER": name, "JACK_NO_START_SERVER": "1"}
        server = self.start(["jackd", "--no-realtime", "--name", name, "-d", "dummy", "-r", "48000", "-p", "256"], env)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = subprocess.run(["jack_lsp"], env=env, capture_output=True, timeout=1)
            if result.returncode == 0:
                break
            self.assertIsNone(server.poll(), "isolated JACK dummy server failed")
            time.sleep(0.05)
        else:
            self.fail("isolated JACK dummy server did not start")
        tone = self.start([str(self.tone)], env)
        time.sleep(0.1)
        self.assertIsNone(tone.poll(), "test tone could not start")
        # The default 26x26 gadget means 52 passive taps. Exercise that workload, including destination taps.
        helper = self.start([str(self.helper), *(["in=meter_test_tone:out_1"] * 26),
                             *(["out=system:playback_1"] * 26), "p0=meter_test_tone:out_1",
                             "p1=meter_test_tone:out_2", "p2=missing:port"], env)
        # Connecting 52 taps takes ~0.8 s on a Pi 4; afterwards packets arrive every 200 ms.
        frames = self.frames(helper, 2.5)
        self.assertIsNone(helper.poll(), "meter stopped while audio was active")
        self.assertGreaterEqual(len(frames), 5)
        self.assertTrue(any(abs(f["in"] - 0.25) < 0.001 and abs(f["out"] - 0.5) < 0.001 for f in frames))
        self.assertTrue(any(f.get("p0") == 0.25 and f.get("p1") == 0.5 and f.get("p2") is None for f in frames))
        self.assertTrue(all(f["_rate"] == 48000 and f["_period"] == 256 and f["_dsp_load"] >= 0 for f in frames))
        clipped = self.start([str(self.helper), "out=meter_test_tone:out_3", "in=missing:port"], env)
        frames = self.frames(clipped, 0.7)
        self.assertTrue(any(f["out"] >= 1.24 and f["in"] is None for f in frames))
        self.stop(helper)
        routes = subprocess.run(["jack_lsp", "-c"], env=env, capture_output=True, text=True, timeout=2).stdout
        self.assertIn("meter_test_tone:out_2", routes)
        playback = routes.split("system:playback_1\n", 1)[1].split("\nsystem:", 1)[0]
        self.assertIn("meter_test_tone:out_2", playback)
        self.assertIsNone(server.poll())


if __name__ == "__main__":
    unittest.main(verbosity=2)
