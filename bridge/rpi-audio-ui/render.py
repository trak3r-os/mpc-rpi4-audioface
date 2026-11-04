# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws ui.UI's rows on a sh1106.Canvas with the 5x7 font: ROWS rows of COLS characters in 6x8-pixel cells,
an inverse row as light text on a lit bar. tests/test_sh1106.py checks it."""

import font5x7
import sh1106

MARGIN = 1   # the 21 cells are 126 pixels wide: one blank column each side

# Seven-pixel symbols designed for this monochrome panel, one row of pixels per string.
ICONS = {
    'edit': ('.....##', '....###', '...###.', '..###..', '.###...', '###....', '##.....'),
    'check': ('.......', '......#', '.....#.', '#...#..', '.#.#...', '..#....', '.......'),
    'error': ('#.....#', '.#...#.', '..#.#..', '...#...', '..#.#..', '.#...#.', '#.....#'),
    'busy': ('#######', '.#...#.', '..#.#..', '...#...', '..#.#..', '.#...#.', '#######'),
    "home": ("...#...", "..###..", ".#####.", "#######", ".#...#.", ".#.#.#.", ".#####."),
    "preset": ("#######", "#...#.#", "#...#.#", "#######", "#.....#", "#.###.#", "#######"),
    "route": (".#...#.", "###.###", ".#...#.", ".#####.", ".#...#.", "###.###", ".#...#."),
    "device": ("#######", "#.....#", "#.###.#", "#.#.#.#", "#.###.#", "#.....#", "#######"),
    "midi": ("..###..", ".#...#.", "#.#.#.#", "#.....#", "#.#.#.#", ".#...#.", "..###.."),
    "settings": (".#.#.#.", ".#.#.#.", "###.#.#", ".#.###.", ".#.#.##", ".#.#.#.", ".#.#.#."),
    "info": ("..###..", ".#...#.", "#..#..#", "#.....#", "#..#..#", ".#.#.#.", "..###.."),
    "list": ("#..####", ".......", "#..####", ".......", "#..####", ".......", "#..####"),
    "wifi": (".#####.", "#.....#", "..###..", ".#...#.", "...#...", "..#.#..", "...#..."),
    "usb": ("...#...", "..###..", "...#.#.", ".#.#.#.", ".#.###.", "..##...", "...#..."),
}


def icon(canvas, name, x, y, on=True):
    for dy, row in enumerate(ICONS.get(name, ICONS["list"])):
        for dx, pixel in enumerate(row):
            if pixel == "#":
                canvas.pixel(x + dx, y + dy, on)


def draw_text(canvas, x, y, text, on=True):
    for i, char in enumerate(text):
        for dx, bits in enumerate(font5x7.glyph(char)):
            for dy in range(7):
                if bits >> dy & 1:
                    canvas.pixel(x + i * font5x7.CELL_W + dx, y + dy, on)


def text_window(text, width, tick=0):
    """Hold both ends before scrolling a long name; untouched labels show an ellipsis."""
    if len(text) <= width or width < 3:
        return text[:width]
    travel = len(text) - width
    phase = tick % (2 * travel + 8)
    offset = min(travel, max(0, phase - 4)) if phase < travel + 8 else max(0, 2 * travel + 8 - phase)
    return text[offset:offset + width] if offset else text[:max(0, width - 2)] + '..'


def draw_large(canvas, y, text):
    x = (128 - len(text) * 12) // 2
    for i, char in enumerate(text):
        for dx, bits in enumerate(font5x7.glyph(char)):
            for dy in range(7):
                if bits >> dy & 1:
                    canvas.rect(x + i * 12 + dx * 2, y + dy * 2,
                                x + i * 12 + dx * 2 + 1, y + dy * 2 + 1, fill=True)


def draw_rows(canvas, rows):
    """Clears the canvas and draws `rows` (objects with .text and .inverse), top to bottom."""
    canvas.clear()
    for number, row in enumerate(rows):
        y = number * font5x7.CELL_H
        inverse = row.inverse and not row.selected
        if row.large:
            draw_large(canvas, y, row.large)
            continue
        if row.meter:
            label, segments, value, clip = row.meter
            draw_text(canvas, 1, y, label)
            canvas.rect(22, y + 1, 93, y + 6)
            if segments >= 0:
                for segment in range(segments):
                    canvas.rect(23 + segment * 4, y + 2, min(25 + segment * 4, 92), y + 5, fill=True)
            if clip:
                canvas.line(95, y + 1, 95, y + 6)
            if row.peak > 0 and segments >= 0:
                x = 23 + min(17, row.peak - 1) * 4
                canvas.line(x, y + 1, x, y + 6)
            draw_text(canvas, 103, y, value[:4])
            continue
        if row.footer:
            wifi, devices, usb = row.footer
            for name, x, text in (("wifi", 2, wifi), ("device", 48, devices), ("usb", 85, usb)):
                icon(canvas, name, x, y + 1)
                draw_text(canvas, x + 10, y + 1, text)
            continue
        if row.selected:
            canvas.line(2, y + 1, 5, y + 4)
            canvas.line(5, y + 4, 2, y + 7)
        elif inverse:
            canvas.rect(0, y, sh1106.WIDTH - 1, y + font5x7.CELL_H - 1, fill=True)
        if row.icon:
            # The header and home menu get icons, with room for the selection arrow.
            x = 9 if number else 2
            icon(canvas, row.icon, x, y, on=not inverse)
            text = row.label or (row.text[1:] if number and row.text[:1] in (">", " ") else row.text).rstrip()
            limit = 18 if number else 19
            if row.scroll:
                top, total, visible = row.scroll
                position = f"{min(top + visible, total)}/{total}"
                right = 127 - len(position) * font5x7.CELL_W
                draw_text(canvas, right, y, position, on=not inverse)
                limit = max(1, (right - x - 11) // font5x7.CELL_W)
            draw_text(canvas, x + 10, y, text_window(text, limit, row.tick), on=not inverse)
        elif row.selected or row.text.startswith((">", " ")):
            width = 20
            if row.badge:
                right = 127 - len(row.badge) * 6
                draw_text(canvas, right, y, row.badge, on=not inverse)
                width = max(1, (right - 14) // 6)
            text = row.label or row.text[1:21]
            draw_text(canvas, 8, y, text_window(text, width, row.tick), on=not inverse)
        elif row.label:
            draw_text(canvas, MARGIN, y, text_window(row.label, 21, row.tick), on=not inverse)
        else:
            draw_text(canvas, MARGIN, y, row.text, on=not inverse)
    return canvas
