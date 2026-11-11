# SPDX-License-Identifier: GPL-3.0-or-later
"""The state store of a read-only root (bridge/rpi-audiod/persist.py) and its command (rpi-audio-persist):
two slots with a CRC, written in place, where a write cut anywhere leaves the previous state readable."""

import contextlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parent.parent / "bridge" / "rpi-audiod"
sys.path.insert(0, str(BRIDGE))
import persist  # noqa: E402

CLI = BRIDGE / "rpi-audio-persist"


def state(n):
    return {"rpi-audio/slots.json": b'{"usb_latency": "low", "n": %d}\n' % n,
            "rpi-audio-ui/settings.json": b'{"contrast": %d}' % n}


class Window:
    """Stands for the remount: counts how often the store asked for a writable filesystem."""

    def __init__(self):
        self.entered, self.inside = 0, False

    @contextlib.contextmanager
    def __call__(self):
        self.entered += 1
        self.inside = True
        try:
            yield
        finally:
            self.inside = False


def test_pack_and_unpack_round_trip():
    files = {"a": b"\x00\xffbinary", "b/c.json": b"{}"}
    assert persist.unpack(persist.pack(7, files)) == (7, files)
    padded = persist.pack(7, files) + bytes(4000)
    assert persist.unpack(padded) == (7, files)


@pytest.mark.parametrize("blob, why", [
    (b"", "empty"),
    (bytes(4096), "empty"),
    (b"RPAS", "cut short"),
    (b"XXXX" + bytes(60), "not a slot"),
])
def test_unusable_slots_say_why(blob, why):
    with pytest.raises(ValueError, match=why):
        persist.unpack(blob)


def test_other_version_and_bad_payload_are_rejected():
    good = bytearray(persist.pack(1, state(1)))
    other = bytearray(good)
    other[4] = 9
    with pytest.raises(ValueError, match="version 9"):
        persist.unpack(bytes(other))
    flipped = bytearray(good)
    flipped[-3] ^= 0x40
    with pytest.raises(ValueError, match="CRC"):
        persist.unpack(bytes(flipped))


def test_saves_alternate_slots_and_the_newest_wins(tmp_path):
    window = Window()
    store = persist.Store(tmp_path, writable=window)
    assert store.newest() is None
    first = store.save(state(1))
    assert (first.name, first.seq) == ("slot0", 1)
    second = store.save(state(2))
    assert (second.name, second.seq) == ("slot1", 2)
    third = store.save(state(3))
    assert (third.name, third.seq) == ("slot0", 3)
    last = store.newest()
    assert (last.name, last.seq, last.files) == ("slot0", 3, state(3))
    assert store.read(1).files == state(2)   # the one before stays, for a torn next write
    assert window.entered == 3


def test_an_unchanged_state_writes_nothing_and_never_remounts(tmp_path):
    window = Window()
    store = persist.Store(tmp_path, writable=window)
    store.save(state(1))
    before = store.path(0).stat().st_mtime_ns
    assert store.save(state(1)) is None
    assert window.entered == 1 and store.path(0).stat().st_mtime_ns == before and not store.path(1).exists()


def test_slots_are_overwritten_in_place_in_whole_blocks(tmp_path):
    store = persist.Store(tmp_path)
    store.save(state(1))
    store.save(state(2))
    inode, size = store.path(0).stat().st_ino, store.path(0).stat().st_size
    assert size == persist.BLOCK
    big = {**state(3), "rpi-audio/presets.json": os.urandom(6000)}   # incompressible: the slot grows
    store.save(big)
    assert store.path(0).stat().st_ino == inode and store.path(0).stat().st_size == 2 * persist.BLOCK
    store.save(state(4))   # slot1
    store.save(state(5))   # slot0 again, smaller: never shrinks, the old tail is zeroed
    assert store.path(0).stat().st_size == 2 * persist.BLOCK and store.newest().files == state(5)
    assert store.path(0).read_bytes()[persist.BLOCK:] == bytes(persist.BLOCK)


def test_each_slot_has_a_folder_of_its_own(tmp_path):
    store = persist.Store(tmp_path)
    store.save(state(1))
    store.save(state(2))
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == [
        "slot0/state.bin", "slot1/state.bin"]


def test_a_write_cut_at_any_byte_leaves_the_previous_state(tmp_path):
    # Power lost in the middle of a save: the slot being written holds the new bytes up to some point and the old
    # ones after it. The other slot, the newest good one, is never written, so it is what comes back.
    store = persist.Store(tmp_path)
    store.save(state(1))   # slot0
    store.save(state(2))   # slot1, newest
    old = store.path(0).read_bytes()
    blob = persist.pack(3, state(3))
    new = blob + bytes(len(old) - len(blob))
    for cut in range(len(new) + 1):
        torn = new[:cut] + old[cut:]
        store.path(0).write_bytes(torn)
        last = store.newest()
        if torn[:len(blob)] == blob:   # every byte that matters is new (or happened to be the same already)
            assert (last.name, last.seq, last.files) == ("slot0", 3, state(3)), cut
        else:
            assert (last.name, last.seq, last.files) == ("slot1", 2, state(2)), cut


def test_garbage_in_the_newest_slot_falls_back_to_the_other(tmp_path):
    store = persist.Store(tmp_path)
    store.save(state(1))
    store.save(state(2))
    blob = bytearray(store.path(1).read_bytes())
    blob[persist.HEADER_SIZE + 5] ^= 0xFF
    store.path(1).write_bytes(bytes(blob))
    assert store.read(1).error.startswith("bad CRC")
    assert store.newest().files == state(1)
    written = store.save(state(3))   # the broken slot is the one written next, never the good one
    assert (written.name, written.seq) == ("slot1", 2)
    assert store.read(0).files == state(1)


def test_a_failed_write_keeps_the_newest_good_slot(tmp_path):
    def broken_fsync(fd):
        raise OSError(5, "Input/output error")

    store = persist.Store(tmp_path)
    store.save(state(1))
    store.save(state(2))
    with pytest.raises(OSError):
        persist.Store(tmp_path, fsync=broken_fsync).save(state(3))
    assert store.read(1).files == state(2)   # whatever slot0 holds now, the newest good one was not touched


def test_both_slots_broken_starts_again_from_slot0(tmp_path):
    store = persist.Store(tmp_path)
    store.save(state(1))
    store.save(state(2))
    for i in (0, 1):
        store.path(i).write_bytes(b"\x01" * 100)
    assert store.newest() is None
    written = store.save(state(9))
    assert (written.name, written.seq) == ("slot0", 1)


def test_the_write_happens_inside_the_writable_window(tmp_path):
    seen = []
    window = Window()

    class Probe(persist.Store):
        def write(self, index, blob):
            seen.append(window.inside)
            super().write(index, blob)

    Probe(tmp_path, writable=window).save(state(1))
    assert seen == [True] and not window.inside


# --- The command --------------------------------------------------------------------------------------------


def cli(tmp_path, *args):
    env = {**os.environ, "RPI_AUDIO_PERSIST_DIR": str(tmp_path / "boot" / "rpi-audio"),
           "RPI_AUDIO_STATE_ROOT": str(tmp_path / "var"), "RPI_AUDIO_PERSIST_LOCK": str(tmp_path / "run" / "lock")}
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, timeout=30)


def live(tmp_path, name, data, mode=0o664):
    path = tmp_path / "var" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def test_command_saves_restores_and_reports(tmp_path):
    live(tmp_path, "rpi-audio/slots.json", b'{"usb_latency": "low"}\n')
    live(tmp_path, "rpi-audio/presets.json", b"{}\n")
    live(tmp_path, "rpi-audio-ui/settings.json", b'{"contrast": 3}', 0o644)
    live(tmp_path, "rpi-audio/slots.json.bak-1", b"not tracked")
    done = cli(tmp_path, "save", "--now")
    assert done.returncode == 0 and "as slot0 (save 1)" in done.stdout, done.stdout + done.stderr
    assert cli(tmp_path, "save", "--now").stdout == ""   # nothing changed: nothing written
    status = cli(tmp_path, "status")
    assert status.returncode == 0 and "slot0: save 1" in status.stdout and "matches" in status.stdout
    assert "slot1: missing" in status.stdout

    # The next boot: the image's old files come back first, then restore puts the saved ones in place.
    live(tmp_path, "rpi-audio/slots.json", b'{"image": true}\n', 0o600)
    (tmp_path / "var" / "rpi-audio-ui" / "settings.json").unlink()
    done = cli(tmp_path, "restore")
    assert done.returncode == 0 and "restored slot0 (save 1)" in done.stdout
    assert (tmp_path / "var/rpi-audio/slots.json").read_bytes() == b'{"usb_latency": "low"}\n'
    assert stat.S_IMODE((tmp_path / "var/rpi-audio/slots.json").stat().st_mode) == 0o664
    assert stat.S_IMODE((tmp_path / "var/rpi-audio-ui/settings.json").stat().st_mode) == 0o644
    assert (tmp_path / "var/rpi-audio/slots.json.bak-1").read_bytes() == b"not tracked"
    assert not list((tmp_path / "var").rglob(".*restore*"))


def test_restore_without_a_store_keeps_the_image(tmp_path):
    live(tmp_path, "rpi-audio/slots.json", b"{}\n")
    done = cli(tmp_path, "restore")
    assert done.returncode == 0 and "keeping the files of the image" in done.stdout
    assert cli(tmp_path, "status").returncode == 1


def test_links_are_neither_saved_nor_written_through(tmp_path):
    secret = tmp_path / "secret"
    secret.write_bytes(b"root only")
    (tmp_path / "var" / "rpi-audio").mkdir(parents=True)
    (tmp_path / "var" / "rpi-audio" / "slots.json").symlink_to(secret)
    live(tmp_path, "rpi-audio/presets.json", b"{}\n")
    assert cli(tmp_path, "save", "--now").returncode == 0
    store = persist.Store(tmp_path / "boot" / "rpi-audio")
    assert set(store.newest().files) == {"rpi-audio/presets.json"}

    store.save({"rpi-audio/slots.json": b"restored\n", "rpi-audio/presets.json": b"{}\n"})
    assert cli(tmp_path, "restore").returncode == 0
    link = tmp_path / "var" / "rpi-audio" / "slots.json"
    assert not link.is_symlink() and link.read_bytes() == b"restored\n" and secret.read_bytes() == b"root only"


def test_untracked_names_in_a_slot_are_never_restored(tmp_path):
    store = persist.Store(tmp_path / "boot" / "rpi-audio")
    store.save({"../escape": b"x", "rpi-audio/slots.json": b"{}\n"})
    assert cli(tmp_path, "restore").returncode == 0
    assert not (tmp_path / "escape").exists() and (tmp_path / "var/rpi-audio/slots.json").exists()
