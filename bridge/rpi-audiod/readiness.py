# SPDX-License-Identifier: GPL-3.0-or-later
"""Assess a saved audio setup against actual device/engine availability, without applying it."""

import presets

VIRTUAL = {'local-dac': 'pHAT DAC', 'usb-host': 'USB host', 'network-rtp': 'Network RTP',
           'network-link': 'Link Audio'}


def assess(setup, status, reserved=None, midi_present=()):
    try:
        presets.validate_state(setup)
    except ValueError as error:
        return {'state': 'error', 'issues': [{'code': 'invalid_setup', 'identity': '', 'message': str(error)}]}
    issues, seen = [], set()
    devices = {d['identity']: d for d in status.get('devices', [])}
    names = setup.get('names', {})
    expected = {}
    playback_needed = set()
    midi_needs = set()

    def issue(code, identity, text):
        key = (code, identity, text)
        if key not in seen:
            seen.add(key)
            issues.append({'code': code, 'identity': identity, 'message': text})

    def label(identity):
        return names.get(identity, {}).get('name') or devices.get(identity, {}).get('name') or \
            VIRTUAL.get(identity, identity)

    def need(identity, side, channels=1):
        expected[(identity, side)] = max(expected.get((identity, side), 0), channels)

    for side in ('in', 'out'):
        for identity in setup.get(side, {}):
            need(identity, side, setup.get(side + '_channels', {}).get(identity, 1))
    for route in setup.get('routes', []):
        src, dst = route['src'], route['dst']
        if src in setup.get('mute', {}).get('in', []) or dst in setup.get('mute', {}).get('out', []):
            continue
        if setup.get('outputs', {}).get(dst) is False:
            continue
        need(src, 'in', 2 * route.get('src_pair', 1) - 1)
        need(dst, 'out', 2 * route.get('dst_pair', 1) - 1)
        playback_needed.add(dst)
    for identity, enabled in setup.get('outputs', {}).items():
        if enabled and identity in VIRTUAL:
            need(identity, 'out')
    for endpoint in setup.get('midi', {}):
        midi_needs.add(endpoint if '/' in endpoint else endpoint + '/0')
    for route in setup.get('midi_routes', []):
        for endpoint in (route['src'], route['dst']):
            midi_needs.add(endpoint if '/' in endpoint else endpoint + '/0')
    if status.get('engine_mode', 'host') == 'host':
        devices['usb-host'] = {'in': {'channels': status.get('gadget_channels', 0),
                                      'running': status.get('jack_ready') and bool(status.get('host_capture_rate'))},
                               'out': {'channels': status.get('gadget_channels', 0),
                                       'running': status.get('jack_ready') and bool(status.get('host_playback_rate'))}}
    outputs = {o['identity']: o for o in status.get('outputs', [])}
    for (identity, side), channels in sorted(expected.items()):
        dev = devices.get(identity)
        title = label(identity)
        if dev is None:
            issue('missing_device', identity, f'Missing: {title}')
            continue
        info = dev.get(side)
        if info is None or info.get('channels', 0) < channels:
            issue('channels', identity, f'{title}: {side.upper()} needs {channels} ch')
            continue
        idle_playback = (status.get('engine_mode') == 'hub' and side == 'out' and
                         identity not in VIRTUAL and identity not in playback_needed)
        if (status.get('engine_mode', 'host') == 'host' and identity not in VIRTUAL and
                'start' in info and info['start'] is None):
            issue('allocation', identity, f'No USB channels: {title} {side.upper()}')
        elif info.get('blocked'):
            issue('blocked', identity, f"{title}: {info['blocked']}")
        elif not info.get('running') and not idle_playback:
            issue('waiting', identity, f'Waiting: {title} {side.upper()}')
        elif identity == 'network-link' and outputs.get(identity, {}).get('state') != 'sending':
            issue('receiver', identity, 'Link Audio: waiting for receiver')
    present = set(midi_present) | {p['identity'] + '/' + str(p['port']) for p in status.get('midi_ports', [])}
    for endpoint in sorted(midi_needs - present):
        identity, _, port = endpoint.rpartition('/')
        issue('missing_midi', identity, f'Missing MIDI: {label(identity)} port {int(port) + 1}')
    if (expected or midi_needs) and not status.get('jack_ready') and expected:
        issue('engine', '', 'Audio engine waiting')
    total = status.get('gadget_channels', 0)
    for side in ('in', 'out'):
        if total and any(ch > total for ch in (reserved or {}).get('reserve_' + side, [])):
            issue('reservation', '', f'Reserved {side.upper()} exceeds {total} USB ch')
    return {'state': 'partial' if issues else 'ready', 'issues': issues,
            'required_devices': len({i for i, _ in expected} | {e.rpartition('/')[0] for e in midi_needs})}
