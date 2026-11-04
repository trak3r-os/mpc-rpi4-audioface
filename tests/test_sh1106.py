# SPDX-License-Identifier: GPL-3.0-or-later
"""The SH1106 driver's frame and what it sends (bridge/rpi-audio-ui/sh1106.py), on a fake I2C link."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge" / "rpi-audio-ui"))
import font5x7  # noqa: E402
import render  # noqa: E402
import sh1106  # noqa: E402
import ui as display  # noqa: E402


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


def test_show_only_transfers_changed_pages_and_keeps_a_copy():
    link, canvas = Link(), sh1106.Canvas()
    screen = sh1106.Display(link)
    screen.show(canvas)
    link.sent.clear()
    screen.show(canvas)
    assert link.sent == []
    canvas.pixel(0, 8)
    screen.show(canvas)
    assert link.sent == [[sh1106.COMMAND, 0xB1, 0x02, 0x10], [sh1106.DATA, 1]]
    link.sent.clear()
    canvas.pixel(0, 8, False)
    screen.show(canvas)
    assert link.sent == [[sh1106.COMMAND, 0xB1, 0x02, 0x10], [sh1106.DATA, 0]]


def test_failed_page_is_retried():
    link, canvas = Link(), sh1106.Canvas()
    screen = sh1106.Display(link)
    screen.show(canvas)
    canvas.pixel(5, 19)
    write = link.write

    def fail(data):
        if data[0] == sh1106.DATA:
            raise OSError("bus error")
        write(data)

    link.write = fail
    with pytest.raises(OSError):
        screen.show(canvas)
    link.write = write
    link.sent.clear()
    screen.show(canvas)
    assert len(link.sent) == 2 and link.sent[0][1] == 0xB2 and link.sent[1][6] == 8


def test_changed_span_uses_correct_column_and_keeps_unchanged_bytes_between_changes():
    link, canvas = Link(), sh1106.Canvas()
    screen = sh1106.Display(link)
    screen.show(canvas)
    link.sent.clear()
    canvas.pixel(31, 9)
    canvas.pixel(34, 10)
    screen.show(canvas)
    assert link.sent == [[sh1106.COMMAND, 0xB1, 1, 0x12], [sh1106.DATA, 2, 0, 0, 4]]


def test_moving_menu_focus_only_transfers_the_arrow_pixels():
    link, canvas = Link(), sh1106.Canvas()
    screen, interface = sh1106.Display(link), display.UI()
    screen.show(render.draw_rows(canvas, interface.render({})))
    link.sent.clear()
    interface.handle('cw', {})
    screen.show(render.draw_rows(canvas, interface.render({})))
    payloads = [packet for packet in link.sent if packet[0] == sh1106.DATA]
    assert len(payloads) == 2 and all(len(packet) == 5 for packet in payloads)
    # Home starts its list on the top row: the arrow left it, the first item's icon and text stay.
    assert not any(canvas.pages[0][2:6]) and any(canvas.pages[0][9:])


def test_partial_failed_page_is_rewritten_when_latest_frame_returns_to_old_pixels():
    link, canvas = Link(), sh1106.Canvas()
    screen = sh1106.Display(link)
    screen.show(canvas)
    canvas.pixel(5, 19)
    write = link.write

    def partial(data):
        write(data)  # the panel may have accepted some or all bytes before the reported error
        if data[0] == sh1106.DATA:
            raise OSError('partial transfer')

    link.write = partial
    with pytest.raises(OSError):
        screen.show(canvas)
    canvas.clear()
    link.write = write
    link.sent.clear()
    screen.show(canvas)
    assert link.sent == [[sh1106.COMMAND, 0xB2, 2, 0x10], [sh1106.DATA, *([0] * 128)]]


def test_all_on_and_power():
    link = Link()
    screen = sh1106.Display(link)
    link.sent.clear()
    screen.all_on()
    screen.all_on(False)
    screen.power(False)
    screen.power(True)
    assert link.sent == [[0, 0xA5], [0, 0xA4], [0, 0xAE], [0, 0xAF]]


def test_failed_initialisation_closes_the_bus():
    link = Link()
    closed = []
    link.close = lambda: closed.append(True)

    def fail(data):
        raise OSError('disconnected')

    link.write = fail
    with pytest.raises(OSError):
        sh1106.Display(link)
    assert closed == [True]


def test_home_list_starts_on_top_line_and_submenu_heading_has_no_lit_background():
    interface = display.UI()
    canvas = render.draw_rows(sh1106.Canvas(), interface.render({}))
    # No title: the top row is the first item, with the selection arrow and no lit background.
    assert any(canvas.pages[0][2:6]) and canvas.pages[0][0] == canvas.pages[0][127] == 0
    interface.handle('push', {})
    canvas = render.draw_rows(canvas, interface.render({}))
    assert any(canvas.pages[0]) and canvas.pages[0][0] == canvas.pages[0][127] == 0


def lit(canvas, x, y, w=6, h=8):
    return [[canvas.get(x + i, y + j) for i in range(w)] for j in range(h)]


def test_font_has_every_printable_character_and_falls_back_to_a_question_mark():
    assert len(font5x7.GLYPHS) == 95 and all(len(g) == 5 and all(0 <= b < 128 for b in g) for g in font5x7.GLYPHS)
    assert font5x7.glyph("\u00e9") == font5x7.glyph("?") == font5x7.glyph("\x01")
    assert font5x7.glyph(" ") == (0, 0, 0, 0, 0)
    assert len({font5x7.glyph(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"}) == 62


def test_text_is_drawn_in_six_pixel_cells():
    c = sh1106.Canvas()
    render.draw_text(c, 0, 0, "F")
    # the F: a stem on the left, a bar on top, a bar in the middle
    assert [c.get(0, y) for y in range(7)] == [True] * 7 and c.get(4, 0) and c.get(3, 3) and not c.get(4, 6)
    assert not any(c.get(5, y) for y in range(8))   # the blank column after the glyph
    render.draw_text(c, 0, 8, "FF")
    assert lit(c, 0, 8, 6, 8) == lit(c, 6, 8, 6, 8)


def test_rows_fill_the_display_and_an_inverse_row_is_a_bar():
    rows = [display.Row(display.fit("Title"), True)] + [display.Row(display.fit("x"))] * (display.ROWS - 1)
    c = render.draw_rows(sh1106.Canvas(), rows)
    assert all(c.get(x, 0) for x in (0, 127)) and all(c.get(0, y) and c.get(127, y) for y in range(8))   # the bar
    assert not c.get(0, 8) and not c.get(127, 63)
    assert display.COLS * font5x7.CELL_W + 2 * render.MARGIN <= sh1106.WIDTH
    assert display.ROWS * font5x7.CELL_H == sh1106.HEIGHT
    # the title is dark text on the bar: the T's first column has only its top pixel set
    assert not c.get(render.MARGIN, 0) and c.get(render.MARGIN, 3)


def test_long_names_pause_then_scroll_without_covering_the_state(monkeypatch):
    name = 'An unusually long output name'
    assert render.text_window(name, 12, 0) == render.text_window(name, 12, 3)
    assert render.text_window(name, 12, 8) != render.text_window(name, 12, 0)
    assert any(render.text_window(name, 12, n).endswith('name') for n in range(80))
    calls = []
    original = render.draw_text

    def record(canvas, x, y, text, on=True):
        calls.append((x, y, text))
        original(canvas, x, y, text, on)

    monkeypatch.setattr(render, 'draw_text', record)
    rows = [display.Row('Outputs', True, icon='device'),
            display.Row('>name', True, True, label=name, badge='off', tick=8)]
    render.draw_rows(sh1106.Canvas(), rows)
    state = next(c for c in calls if c[2] == 'off')
    text = next(c for c in calls if c[0] == 8 and c[1] == 8)
    assert text[0] + len(text[2]) * 6 < state[0]


def test_large_output_percentage_uses_two_rows_and_keeps_footer():
    ui = display.UI()
    ui.stack = [display.OutputLevel('local-dac', 75)]
    rows = ui.render({'outputs': [{'identity': 'local-dac', 'name': 'pHAT DAC'}]})
    assert rows[2].large == '75%' and rows[-1].footer
    canvas = render.draw_rows(sh1106.Canvas(), rows)
    assert any(canvas.get(x, y) for x in range(128) for y in range(24, 30))


def test_static_menus_do_not_redraw_and_marquee_restarts_after_input():
    ui = display.UI()
    assert ui.render({}, 0) == ui.render({}, 10)
    ui.stack = [display.Outputs()]
    status = {'outputs': [{'identity': 'local-dac', 'name': 'A very long output device name', 'state': 'active'}]}
    first = ui.render(status, 10)
    assert first[1].badge == 'on' and first[1].tick == 0
    assert ui.render(status, 13)[1].tick > 0
    ui.handle('ccw', status, 14)
    assert ui.render(status, 14)[1].tick == 0
