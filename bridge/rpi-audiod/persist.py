# SPDX-License-Identifier: GPL-3.0-or-later
"""State that survives a read-only root (install.sh --read-only): two alternating slots on the boot partition.

The root filesystem is then a RAM overlay, so /var/lib/rpi-audio starts every boot as it was when the
image was made. rpi-audio-persist copies the files that change at runtime (slots, presets, host profiles,
the display's settings) into one bundle, and back at boot. The boot partition is FAT, which has no journal
and may lose power in the middle of a write, so:

- there are two slots, slot0/ and slot1/, each in a directory of its own (a torn directory sector can only
  hurt one of them), each holding one file, state.bin;
- a save always writes the slot that does not hold the newest valid bundle, with a sequence number one
  higher, so the newest good copy is never the one being written;
- the file is overwritten in place, never truncated or replaced, and padded to whole 4 KiB blocks: the same
  clusters are reused, so the FAT tables are not written at all once the slot exists;
- a header carries the payload's length and a CRC-32 of header and payload; gzip has its own CRC too. A slot
  that fails any check is skipped, and the other one is used: at worst, the last change is lost.

This follows the pattern of raspimidihub's config.py (two gzip slots, remount with flock and sync), without its
code. The module is pure: the caller passes a context manager that makes the store writable (remount rw, then
sync and ro) and does its own locking.
"""

import base64
import contextlib
import gzip
import json
import os
import struct
import zlib
from pathlib import Path

MAGIC = b"RPAS"
VERSION = 1
HEAD = struct.Struct("<4sHHQI")   # magic, version, reserved, sequence, payload length
CRC = struct.Struct("<I")
HEADER_SIZE = HEAD.size + CRC.size
SLOTS = ("slot0", "slot1")
NAME = "state.bin"
BLOCK = 4096
MAX_PAYLOAD = 4 << 20


def pack(seq, files):
    """The bytes of one slot (before padding) holding files, {name: bytes}."""
    doc = {"files": {name: base64.b64encode(data).decode() for name, data in sorted(files.items())}}
    payload = gzip.compress(json.dumps(doc, sort_keys=True).encode(), mtime=0)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"state too large: {len(payload)} bytes compressed")
    head = HEAD.pack(MAGIC, VERSION, 0, seq, len(payload))
    return head + CRC.pack(zlib.crc32(head + payload)) + payload


def unpack(blob):
    """(seq, files) from the bytes of a slot; ValueError says why a slot cannot be used."""
    if len(blob) < HEADER_SIZE:
        raise ValueError("empty" if not blob.strip(b"\0") else "cut short")
    magic, version, _, seq, length = HEAD.unpack_from(blob)
    if magic != MAGIC:
        raise ValueError("empty" if not blob[:HEADER_SIZE].strip(b"\0") else "not a slot")
    if version != VERSION:
        raise ValueError(f"version {version}")
    payload = blob[HEADER_SIZE:HEADER_SIZE + length]
    if length > MAX_PAYLOAD or len(payload) != length:
        raise ValueError("cut short")
    if zlib.crc32(blob[:HEAD.size] + payload) != CRC.unpack_from(blob, HEAD.size)[0]:
        raise ValueError("bad CRC (torn write?)")
    try:
        doc = json.loads(gzip.decompress(payload))
        files = {str(name): base64.b64decode(text, validate=True) for name, text in doc["files"].items()}
    except (OSError, EOFError, zlib.error, ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"bad payload: {e}") from None
    return seq, files


class Slot:
    def __init__(self, index, seq=None, files=None, error=None):
        self.index, self.seq, self.files, self.error = index, seq, files, error

    @property
    def name(self):
        return SLOTS[self.index]

    @property
    def valid(self):
        return self.error is None


class Store:
    """The two slots under folder (e.g. /boot/firmware/rpi-audio). writable() is entered around every write."""

    def __init__(self, folder, writable=None, fsync=os.fsync):
        self.folder = Path(folder)
        self.writable = writable or contextlib.nullcontext
        self.fsync = fsync

    def path(self, index):
        return self.folder / SLOTS[index] / NAME

    def read(self, index):
        try:
            blob = self.path(index).read_bytes()
        except FileNotFoundError:
            return Slot(index, error="missing")
        except OSError as e:
            return Slot(index, error=f"unreadable: {e.strerror or e}")
        try:
            seq, files = unpack(blob)
        except ValueError as e:
            return Slot(index, error=str(e))
        return Slot(index, seq, files)

    def slots(self):
        return [self.read(i) for i in range(len(SLOTS))]

    def newest(self, slots=None):
        """The valid slot with the highest sequence number, or None."""
        good = [s for s in (slots or self.slots()) if s.valid]
        return max(good, key=lambda s: s.seq) if good else None

    def save(self, files):
        """Stores files ({name: bytes}) unless the newest valid slot holds exactly them. Returns the Slot
        written, or None when nothing had to be. Raises OSError when the write itself fails."""
        slots = self.slots()
        last = self.newest(slots)
        if last and last.files == files:
            return None
        index = 0 if last is None else 1 - last.index
        seq = 1 if last is None else last.seq + 1
        blob = pack(seq, files)
        with self.writable():
            self.write(index, blob)
        return Slot(index, seq, dict(files))

    def write(self, index, blob):
        path = self.path(index)
        created = not path.parent.is_dir()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644)
        try:
            size = os.fstat(fd).st_size
            total = max(size, -(-len(blob) // BLOCK) * BLOCK)
            data = memoryview(blob + bytes(total - len(blob)))
            offset = 0
            while offset < len(data):
                offset += os.pwrite(fd, data[offset:], offset)
            self.fsync(fd)
        finally:
            os.close(fd)
        if created:
            for folder in (path.parent, path.parent.parent):
                self.sync_dir(folder)

    def sync_dir(self, folder):
        with contextlib.suppress(OSError):
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.fsync(fd)
            finally:
                os.close(fd)
