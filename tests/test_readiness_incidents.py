# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bridge/rpi-audiod'))
import incidents  # noqa: E402
import readiness  # noqa: E402


STATUS = {'engine_mode': 'hub', 'jack_ready': True, 'gadget_channels': 26,
          'devices': [{'identity': 'guitar', 'name': 'GP-150',
                       'in': {'channels': 6, 'running': True}},
                      {'identity': 'local-dac', 'name': 'pHAT DAC',
                       'out': {'channels': 2, 'running': True}}]}
SETUP = {'in': {'guitar': 1}, 'in_channels': {'guitar': 6}, 'names': {'guitar': {'name': 'GP-150'}},
         'routes': [{'src': 'guitar', 'dst': 'local-dac'}]}


def test_profile_ready_missing_device_wrong_mode_and_waiting():
    assert readiness.assess(SETUP, STATUS)['state'] == 'ready'
    missing = readiness.assess(SETUP, {**STATUS, 'devices': STATUS['devices'][1:]})
    assert missing['state'] == 'partial' and any('Missing: GP-150' == i['message'] for i in missing['issues'])
    wrong_device = {**STATUS['devices'][0], 'in': {'channels': 2, 'running': True}}
    wrong = {**STATUS, 'devices': [wrong_device, STATUS['devices'][1]]}
    assert any(i['code'] == 'channels' for i in readiness.assess(SETUP, wrong)['issues'])
    assert any(i['code'] == 'engine' for i in readiness.assess(SETUP, {**STATUS, 'jack_ready': False})['issues'])


def test_hub_saved_playback_assignment_can_be_idle_until_a_route_needs_it():
    synth = {'identity': 'synth', 'out': {'channels': 2, 'running': False}}
    status = {**STATUS, 'devices': [*STATUS['devices'], synth]}
    setup = {**SETUP, 'out': {'synth': 3}, 'out_channels': {'synth': 2}}
    assert readiness.assess(setup, status)['state'] == 'ready'
    routed = {**setup, 'routes': [*SETUP['routes'], {'src': 'guitar', 'dst': 'synth'}]}
    assert any(i['code'] == 'waiting' and i['identity'] == 'synth'
               for i in readiness.assess(routed, status)['issues'])
    assert any(i['code'] == 'waiting' and i['identity'] == 'synth'
               for i in readiness.assess(setup, {**status, 'engine_mode': 'host'})['issues'])


def test_profile_checks_midi_port_and_intentionally_disabled_network_routes():
    setup = {**SETUP, 'midi_routes': [{'src': 'keys/1', 'dst': 'synth/0'}],
             'routes': [*SETUP['routes'], {'src': 'guitar', 'dst': 'network-rtp'}],
             'outputs': {'network-rtp': False}}
    partial = readiness.assess(setup, STATUS, midi_present=['keys/0', 'synth/0'])
    assert len(partial['issues']) == 1 and 'keys port 2' in partial['issues'][0]['message']
    assert readiness.assess(setup, STATUS, midi_present=['keys/1', 'synth/0'])['state'] == 'ready'


def test_profile_detects_blocked_device_missing_receiver_and_invalid_setup():
    network = {'identity': 'network-link', 'out': {'channels': 2, 'running': True}}
    status = {**STATUS, 'devices': [*STATUS['devices'], network],
              'outputs': [{'identity': 'network-link', 'state': 'waiting'}]}
    result = readiness.assess({'routes': [{'src': 'guitar', 'dst': 'network-link'}]}, status)
    assert result['state'] == 'partial' and result['issues'][0]['code'] == 'receiver'
    assert readiness.assess({'routes': 'bad'}, STATUS)['state'] == 'error'
    assert readiness.assess({}, STATUS, {'reserve_in': [27]})['state'] == 'partial'


def test_session_counter_deltas_coalescing_retention_restart_and_boot_reset(tmp_path):
    now = [10.0]
    path = tmp_path / 'session.json'

    def clock():
        return now[0]
    session = incidents.Session(path, 'boot-one', clock=clock, wall=lambda: 'test time')
    session.observe('observer/xruns', 2, 'xruns', 'JACK')
    now[0] += 0.5
    session.observe('observer/xruns', 5, 'xruns', 'JACK')
    session.observe('observer/xruns', 5, 'xruns', 'JACK')
    assert session.snapshot()['counters']['xruns'] == 5
    assert len(session.snapshot()['events']) == 1 and session.snapshot()['events'][0]['count'] == 5
    session.reset_observer('observer/xruns')
    session.observe('observer/xruns', 1, 'xruns', 'JACK')
    assert session.snapshot()['counters']['xruns'] == 6
    for n in range(80):
        now[0] += 3
        session.event('usb_disconnects', f'USB {n}')
    assert len(session.snapshot()['events']) == incidents.LIMIT
    session.flush(lambda p, data: p.write_text(json.dumps(data)))
    resumed = incidents.Session(path, 'boot-one', clock=clock)
    assert resumed.snapshot()['counters']['xruns'] == 6
    assert resumed.snapshot()['counters']['usb_disconnects'] == 80
    assert incidents.Session(path, 'boot-two').snapshot()['counters'] == {}
    assert resumed.value('rate', 48000) is None and resumed.value('rate', 44100) == 48000
