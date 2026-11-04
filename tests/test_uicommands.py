# SPDX-License-Identifier: GPL-3.0-or-later
"""Check the executable's power dispatch with subprocesses replaced; never power off the test machine."""

import runpy
import sys
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

UI = Path(__file__).resolve().parent.parent / 'bridge/rpi-audio-ui'
sys.path.insert(0, str(UI))


@pytest.fixture
def program():
    return SimpleNamespace(**runpy.run_path(str(UI / 'rpi-audio-ui')))


@pytest.mark.parametrize('action', ['poweroff', 'reboot'])
def test_confirmed_power_action_uses_only_the_exact_privileged_command(program, monkeypatch, action):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(program.subprocess, 'run', run)
    assert program.run_command(f'system {action}') == ''
    assert calls == [(['/usr/bin/sudo', '-n', '/usr/bin/systemctl', action],
                      {'capture_output': True, 'text': True, 'timeout': program.COMMAND_TIMEOUT_S})]


def test_unknown_system_action_never_runs_a_subprocess(program, monkeypatch):
    def run(*args, **kwargs):
        raise AssertionError('unrecognised system action must not run')

    monkeypatch.setattr(program.subprocess, 'run', run)
    for text in ('system reboot --force', 'system reset', 'system poweroff now'):
        assert program.run_command(text) == 'unknown system action'


@pytest.mark.parametrize('failure', ['permission', 'missing', 'timeout'])
def test_power_failures_are_reported_for_the_ui_to_recover(program, monkeypatch, failure):
    def run(command, **kwargs):
        if failure == 'missing':
            raise FileNotFoundError('sudo unavailable')
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        return SimpleNamespace(returncode=1, stderr='sudo: permission denied\n')

    monkeypatch.setattr(program.subprocess, 'run', run)
    assert program.run_command('system poweroff')


def test_audio_commands_still_use_the_daemon(program, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(program.subprocess, 'run', run)
    assert program.run_command('volume local-dac out 80') == ''
    assert calls == [[program.AUDIOD, 'cmd', 'volume', 'local-dac', 'out', '80']]
