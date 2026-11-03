# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bridge/rpi-audio-ui'))
import health  # noqa: E402
import meters  # noqa: E402
import ui  # noqa: E402
import telemetry  # noqa: E402


STATUS = {'jack_ready': True, 'engine_mode': 'hub', 'hub': {'channels': 2},
          'engine': {'rate': 48000, 'period': 256, 'periods': 3},
          'devices': [{'identity': 'guitar', 'name': 'Guitar', 'card': 'GP150',
                       'in': {'running': True, 'channels': 2, 'rate': 48000, 'client': 'guitar_in'}},
                      {'identity': 'local-dac', 'name': 'DAC', 'card': 'DAC', 'local': True,
                       'out': {'running': True, 'channels': 2, 'rate': 48000}}]}


def test_endpoint_meters_have_distinct_keys_and_true_peak_bars():
    assert meters.ports({**STATUS, '_meter_detail': True}) == (
        'p0=guitar_in:capture_1', 'p0=guitar_in:capture_2', 'p1=system:playback_1', 'p1=system:playback_2')
    interface = ui.UI()
    interface.levels = meters.packet('{"in":null,"out":null,"p0":0.5,"p1":0.25,"_rate":48000,"_xruns":2}')
    screen = ui.IOStatus('in')
    rows = screen.rows(interface, STATUS, 0)
    assert rows[2].meter[2] == '-6'
    screen.handle('push', interface, STATUS, 0)
    assert isinstance(interface.screen, ui.EndpointStatus)
    assert interface.screen.rows(interface, STATUS, 0)[1].meter[2] == '-6'


def test_pcm_buffer_detail_and_unavailable_values_are_distinct():
    interface = ui.UI()
    interface.hardware = {'pcm': {'GP150/in': {'rate': 48000, 'period_size': 256, 'buffer_size': 512,
                                               'avail': 256, 'delay': 0, 'state': 'RUNNING'}}}
    rows = ui.EndpointStatus('guitar/in').details(interface, STATUS)
    assert 'Buffer: 512 f' in rows and 'Buffer: 10.7 ms' in rows and 'Fill [####...] 50%' in rows
    interface.hardware = {}
    assert 'Fill: --' in ui.EndpointStatus('guitar/in').details(interface, STATUS)
    assert health.bar(None).endswith('--')


def test_status_screensaver_rotates_measured_pages_and_moves_every_pixel_region():
    positions, contents = set(), set()
    for tick in range(40):
        rows = ui.saver_rows('status', tick * 3, status={**STATUS, 'session': {'counters': {'xruns': 2}}},
                             hardware={'machine': {'cpu_pct': 25, 'memory_pct': 50, 'temperature': 42}},
                             levels={'_rate': 48000, '_period': 256, '_dsp_load': 3, '_xruns': 2})
        assert len(rows) == 8 and all(len(r.text) == 21 and not r.footer and not r.inverse for r in rows)
        lit = [(n, r.text) for n, r in enumerate(rows) if r.text.strip()]
        positions.add((lit[0][0], len(lit[0][1]) - len(lit[0][1].lstrip())))
        contents.update(r.text.strip() for r in rows)
    assert len(positions) >= 4 and 'Rate: 48 kHz' in contents and 'Session XRuns: 2' in contents


def test_machine_and_pcm_read_actual_proc_values_and_tolerate_missing_data(tmp_path):
    proc, system = tmp_path / 'proc', tmp_path / 'sys'
    proc.mkdir()
    system.mkdir()
    (proc / 'stat').write_text('cpu 10 0 20 60 10 0 0 0 0 0\n')
    (proc / 'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 250 kB\n')
    (proc / 'uptime').write_text('3600.25 0\n')
    machine = telemetry.machine(proc, system)
    assert machine['cpu_times'] == (100, 70) and machine['memory_pct'] == 75 and machine['uptime'] == 3600.25
    card = proc / 'asound/card2'
    path = card / 'pcm0c/sub0'
    path.mkdir(parents=True)
    (card / 'id').write_text('GP150\n')
    (path / 'hw_params').write_text('rate: 48000 (48000/1)\nperiod_size: 256\nbuffer_size: 512\n')
    (path / 'status').write_text('state: RUNNING\navail       : 128\ndelay       : 10\n')
    pcm = telemetry.pcm_status(proc)['GP150/in']
    assert pcm['avail'] == 128 and pcm['delay'] == 10 and pcm['buffer_size'] == 512


def test_original_host_mode_reports_the_usb_endpoint_as_well():
    status = {'engine_mode': 'host', 'jack_ready': True, 'gadget_channels': 26,
              'host_capture_rate': 44100, 'host_playback_rate': 44100}
    endpoints = health.endpoints(status)
    assert [e['key'] for e in endpoints] == ['usb-host/in', 'usb-host/out']
    assert meters.ports({**status, '_meter_detail': True})[0] == 'p0=system:capture_1'


def test_machine_buffer_prefers_measured_alsa_size():
    status = {**STATUS, 'hub': {'card': 'DAC'}}
    rows = health.machine_lines(status, {'pcm': {'DAC/out': {'buffer_size': 1024, 'period_size': 256}}}, {})
    assert 'Engine buf: 1024 f' in rows and 'Buffer: 21.3 ms' in rows
