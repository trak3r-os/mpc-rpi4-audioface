# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent outputs, one-time legacy migration and safe RTP download behavior."""
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen, Request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bridge/rpi-audiod'))
import outputs  # noqa: E402
import midi  # noqa: E402
import presets  # noqa: E402
import sdpserver  # noqa: E402


def test_migration_preserves_and_does_not_recreate_removed_routes():
    state = {'in': {'keys': 3}, 'in_channels': {'keys': 4},
             'out': {'synth': 5}, 'out_channels': {'synth': 2}}
    outputs.migrate_host_routes(state)
    assert state['routes'] == [{'src': 'keys', 'dst': 'usb-host', 'dst_pair': 2},
                               {'src': 'keys', 'dst': 'usb-host', 'src_pair': 2, 'dst_pair': 3},
                               {'src': 'usb-host', 'dst': 'synth', 'src_pair': 3}]
    state['routes'] = []
    assert outputs.migrate_host_routes(state)['routes'] == []


@pytest.mark.parametrize('table', [{'address': 'broken'}, {'port': 5005}, {'port': True}, {'ttl': 0},
                                   {'http_port': 80}, {'http_port': True}])
def test_invalid_network_config_has_an_actionable_error(table):
    with pytest.raises(ValueError):
        outputs.network(table)


def test_output_commands_persist_and_scenes_keep_flags_without_changing_engine():
    state, _ = midi.apply_command({}, midi.parse_command('output network-rtp on'))
    state, _ = midi.apply_command(state, midi.parse_command('engine hub'))
    assert outputs.enabled(state, outputs.RTP) and state['engine_mode'] == 'hub'
    assert 'outputs' in presets.STATE_KEYS and 'hub_routes_initialized' in presets.STATE_KEYS
    assert 'engine_mode' not in presets.STATE_KEYS
    for command in ('output fake on', 'output usb-host yes', 'engine fake'):
        with pytest.raises(ValueError):
            midi.parse_command(command)


def test_sdp_http_only_serves_active_description_and_no_arbitrary_files(tmp_path):
    path = tmp_path / 'network-rtp.sdp'
    path.write_bytes(b'v=0\r\ns=Example\r\n')
    active = [False]
    server = sdpserver.Server('127.0.0.1', 0, path, lambda: active[0])
    url = 'http://127.0.0.1:' + str(server.http.server_port)
    try:
        with urlopen(url + '/') as response:
            assert b'Download' in response.read()
        for route, code in (('/network-rtp.sdp', 503), ('/../../etc/passwd', 404)):
            with pytest.raises(HTTPError) as error:
                urlopen(url + route)
            assert error.value.code == code
        active[0] = True
        with urlopen(url + '/network-rtp.sdp') as response:
            assert response.headers['Content-Type'] == 'application/sdp'
            assert response.headers['Cache-Control'] == 'no-store'
            assert response.read() == path.read_bytes()
        with urlopen(Request(url + '/network-rtp.sdp', method='HEAD')) as response:
            assert response.read() == b''
        path.unlink()
        with pytest.raises(HTTPError) as error:
            urlopen(url + '/network-rtp.sdp')
        assert error.value.code == 503
    finally:
        server.close()
