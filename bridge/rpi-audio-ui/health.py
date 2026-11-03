# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only status models shared by the OLED monitor and passive peak reader."""


def endpoints(status, hardware=None):
    devices = [dict(d) for d in status.get('devices', [])]
    if status.get('gadget_channels') and not (status.get('hub') or status.get('standalone')):
        channels = status['gadget_channels']
        devices.append({'identity': 'usb-host', 'name': 'USB host', 'card': 'UAC2Gadget',
                        'in': {'client': 'system', 'channels': channels, 'rate': status.get('host_capture_rate', 0),
                               'running': status.get('jack_ready', False)},
                        'out': {'client': 'system', 'channels': channels, 'rate': status.get('host_playback_rate', 0),
                                'running': status.get('jack_ready', False)}})
    for dev in (hardware or {}).get('devices', []):
        if not any(d.get('identity') == dev.get('identity') or d.get('card') == dev.get('card') for d in devices):
            devices.append(dev)
    rows = []
    for dev in devices:
        for side in ('in', 'out'):
            if side not in dev:
                continue
            info = dev[side]
            client = info.get('client') or ('system' if dev.get('local') else '')
            if not client and dev.get('virtual'):
                output = next((o for o in status.get('outputs', []) if o['identity'] == dev['identity']), {})
                client = output.get('client', '')
            rows.append({**info, 'identity': dev['identity'], 'side': side, 'client': client,
                         'name': dev.get('name') or dev.get('card') or dev['identity'],
                         'card': dev.get('card', ''), 'key': dev['identity'] + '/' + side,
                         'meter': 'p' + str(len(rows))})
    return rows


def pcm(endpoint, hardware):
    return hardware.get('pcm', {}).get(endpoint.get('card', '') + '/' + endpoint['side'], {})


def bar(value, width=7):
    if value is None:
        return '[-------] --'
    lit = max(0, min(width, round(value * width / 100)))
    return '[' + '#' * lit + '.' * (width - lit) + f'] {value:.0f}%'


def machine_lines(status, hardware, levels):
    machine = hardware.get('machine', {})
    engine = status.get('engine', {})
    rate = levels.get('_rate', engine.get('rate', 0))
    period = levels.get('_period', engine.get('period', 0))
    periods = engine.get('periods', 0)
    local = status.get('hub') or status.get('standalone') or {}
    actual = hardware.get('pcm', {}).get(local.get('card', 'UAC2Gadget') + '/out', {})
    period = actual.get('period_size', period)
    buffer_frames = actual.get('buffer_size', period * periods)
    buffer_label = 'Engine buf' if actual else 'Config buf'
    monitor = status.get('session', {}).get('monitor', {})
    dsp = levels.get('_dsp_load', monitor.get('dsp_load'))
    xruns = status.get('session', {}).get('counters', {}).get('xruns')
    temperature = machine.get('temperature')
    mem = machine.get('memory_pct')
    midi = status.get('midi') or {}
    return [f"Engine: {status.get('engine_mode', 'unknown')}",
            'JACK: ready' if status.get('jack_ready') else 'JACK: waiting',
            'CPU ' + bar(machine.get('cpu_pct')), 'RAM ' + bar(mem),
            f"Temp: {temperature:.1f} C" if temperature is not None else 'Temp: --',
            f"Rate: {rate / 1000:g} kHz" if rate else 'Rate: --',
            f"Period: {period} frames" if period else 'Period: --',
            f"Buffers: {periods}" if periods else 'Buffers: --',
            f"{buffer_label}: {buffer_frames} f" if buffer_frames else 'Engine buf: --',
            f"Buffer: {buffer_frames * 1000 / rate:.1f} ms" if buffer_frames and rate else 'Buffer: -- ms',
            f"DSP load: {dsp:.1f}%" if dsp is not None else 'DSP load: --',
            f"Session XRuns: {xruns}" if xruns is not None else 'Session XRuns: --',
            f"Uptime: {machine['uptime'] / 3600:.1f} h" if 'uptime' in machine else 'Uptime: --',
            f"MIDI cables: {midi.get('ports', 0)}", f"MIDI routes: {len(status.get('midi_routes', []))}"]
