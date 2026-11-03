# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded session counters/history, persisted in RAM across service and engine restarts within a boot."""
import copy
import json
from pathlib import Path
import threading
import time

LIMIT = 64


class Session:
    def __init__(self, path, boot_id=None, clock=time.monotonic, wall=lambda: time.strftime('%Y-%m-%d %H:%M:%S')):
        self.path, self.clock, self.wall = Path(path), clock, wall
        if boot_id is None:
            try:
                boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            except OSError:
                boot_id = 'unknown'
        self.lock = threading.Lock()
        self.data = {'boot_id': boot_id, 'started': wall(), 'counters': {}, 'events': []}
        try:
            old = json.loads(self.path.read_text())
            if (old.get('boot_id') == boot_id and isinstance(old.get('events'), list) and
                    isinstance(old.get('counters'), dict)):
                self.data = {**old, 'events': old['events'][-LIMIT:]}
        except (OSError, ValueError, AttributeError):
            pass
        self.baselines, self.dirty = {}, True

    def event(self, kind, detail, count=1, severity='info'):
        with self.lock:
            self._event(kind, detail, count, severity)

    def _event(self, kind, detail, count, severity):
        counters = self.data['counters']
        counters[kind] = counters.get(kind, 0) + count
        now, wall = self.clock(), self.wall()
        events = self.data['events']
        detail = str(detail)[:240]
        if (events and events[-1].get('kind') == kind and events[-1].get('detail') == detail and
                0 <= now - events[-1].get('monotonic', 0) < 2):
            events[-1]['count'] += count
            events[-1]['monotonic'] = now
            events[-1]['last_time'] = wall
        else:
            self.data['sequence'] = self.data.get('sequence', 0) + 1
            events.append({'id': self.data['sequence'], 'time': wall, 'monotonic': now, 'kind': kind,
                           'detail': detail, 'count': count, 'severity': severity})
        self.data['events'] = events[-LIMIT:]
        self.dirty = True

    def value(self, key, value):
        with self.lock:
            values = self.data.setdefault('last_values', {})
            before = values.get(key)
            if before != value:
                values[key] = value
                self.dirty = True
            return before

    def reset_observer(self, key):
        with self.lock:
            self.baselines.pop(key, None)

    def observe(self, key, value, kind, detail):
        if type(value) is not int or value < 0:
            return
        with self.lock:
            previous = self.baselines.get(key, 0)
            delta = value - previous if value >= previous else value
            self.baselines[key] = value
            if delta:
                self._event(kind, detail, delta, 'warning')

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def flush(self, writer):
        with self.lock:
            if not self.dirty:
                return
            data = copy.deepcopy(self.data)
            self.dirty = False
        try:
            writer(self.path, data)
        except OSError:
            with self.lock:
                self.dirty = True
            raise
