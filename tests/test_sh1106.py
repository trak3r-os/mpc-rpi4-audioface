# SPDX-License-Identifier: GPL-3.0-or-later
"""The SH1106 driver's frame and what it sends (bridge/rpi-audio-ui/sh1106.py), on a fake I2C link."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audio-ui"))
import sh1106  # noqa: E402


class Link:
    def __init__(self):
        self.sent = []

    def write(self, data):
        self.sent.append(list(data))


def test_pixels_land_in_the_pages_bit_by_bit():
    c = sh1106.Canvas()
    c.pixel(0, 0)
    c.pixel(5, 9)
    c.pixel(127, 63)
    assert c.pages[0][0] == 0b1 and c.pages[1][5] == 0b10 and c.pages[7][127] == 0b10000000
    assert c.get(5, 9) and not c.get(5, 8)
    c.pixel(5, 9, False)
    assert c.pages[1][5] == 0 and not c.get(5, 9)
    c.pixel(-1, 0)
    c.pixel(128, 0)
    c.pixel(0, 64)   # outside the panel: ignored
    assert sum(bin(b).count("1") for page in c.pages for b in page) == 2


def test_clear_and_shapes():
    c = sh1106.Canvas()
    c.clear(True)
    assert all(b == 0xFF for page in c.pages for b in page)
    c.clear()
    c.rect(2, 2, 5, 4)
    assert [c.get(x, y) for x, y in ((2, 2), (5, 4), (3, 3), (2, 4))] == [True, True, False, True]
    c.rect(10, 10, 12, 12, fill=True)
    assert c.get(11, 11)
    d = sh1106.Canvas()
    d.line(0, 0, 10, 10)
    assert d.get(0, 0) and d.get(5, 5) and d.get(10, 10) and not d.get(5, 4)


def test_show_sends_each_page_at_the_column_offset():
    link, c = Link(), sh1106.Canvas()
    screen = sh1106.Display(link)
    assert link.sent[0][0] == sh1106.COMMAND and link.sent[0][1] == 0xAE and link.sent[0][-1] == 0xAF
    link.sent.clear()
    c.pixel(0, 8)
    screen.show(c)
    assert len(link.sent) == 16
    assert link.sent[2] == [sh1106.COMMAND, 0xB1, 0x02, 0x10]      # page 1, column 2
    assert link.sent[3][0] == sh1106.DATA and len(link.sent[3]) == 1 + sh1106.WIDTH and link.sent[3][1] == 1
    assert link.sent[1][0] == sh1106.DATA and not any(link.sent[1][1:])


def test_flip_turns_the_picture():
    assert 0xA1 in sh1106.init_commands() and 0xC8 in sh1106.init_commands()
    flipped = sh1106.init_commands(flip=True)
    assert 0xA0 in flipped and 0xC0 in flipped and 0xA1 not in flipped and 0xC8 not in flipped
    assert sh1106.init_commands(contrast=0x20)[sh1106.init_commands().index(0x81) + 1] == 0x20


def test_all_on_and_power():
    link = Link()
    screen = sh1106.Display(link)
    link.sent.clear()
    screen.all_on()
    screen.all_on(False)
    screen.power(False)
    screen.power(True)
    assert link.sent == [[0, 0xA5], [0, 0xA4], [0, 0xAE], [0, 0xAF]]
