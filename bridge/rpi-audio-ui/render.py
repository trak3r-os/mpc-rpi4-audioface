# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws ui.UI's rows on a sh1106.Canvas with the 5x7 font: ROWS rows of COLS characters in 6x8-pixel cells,
an inverse row as light text on a lit bar. tests/test_sh1106.py checks it."""

import font5x7
import sh1106

MARGIN = 1   # the 21 cells are 126 pixels wide: one blank column each side

# Seven-pixel symbols designed for this monochrome panel, one row of pixels per string.
ICONS = {
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


def draw_rows(canvas, rows):
    """Clears the canvas and draws `rows` (objects with .text and .inverse), top to bottom."""
    canvas.clear()
    for number, row in enumerate(rows):
        y = number * font5x7.CELL_H
        if row.meter:
            label, segments, value, clip = row.meter
            draw_text(canvas, 1, y, label)
            canvas.rect(22, y + 1, 93, y + 6)
            if segments >= 0:
                for segment in range(segments):
                    canvas.rect(23 + segment * 4, y + 2, min(25 + segment * 4, 92), y + 5, fill=True)
            if clip:
                canvas.line(95, y + 1, 95, y + 6)
            draw_text(canvas, 103, y, value[:4])
            continue
        if row.footer:
            wifi, devices, usb = row.footer
            canvas.line(0, y, 127, y)
            for x in (43, 79):
                canvas.line(x, y + 2, x, y + 7)
            for name, x, text in (("wifi", 2, wifi), ("device", 48, devices), ("usb", 85, usb)):
                icon(canvas, name, x, y + 1)
                draw_text(canvas, x + 10, y + 1, text)
            continue
        if row.selected:
            canvas.rect(1, y + 1, 125, y + 6, fill=True)
            canvas.line(2, y, 124, y)
            canvas.line(2, y + 7, 124, y + 7)
            canvas.line(3, y + 2, 5, y + 4, on=False)
            canvas.line(5, y + 4, 3, y + 6, on=False)
        elif row.inverse:
            canvas.rect(0, y, sh1106.WIDTH - 1, y + font5x7.CELL_H - 1, fill=True)
        if row.icon:
            # The header and home menu get icons, with room for the selection arrow.
            x = 9 if number else 2
            icon(canvas, row.icon, x, y, on=not row.inverse)
            text = row.text[1:] if number and row.text[:1] in (">", " ") else row.text
            limit = 18 if number else 19
            if row.scroll:
                top, total, visible = row.scroll
                position = f"{min(top + visible, total)}/{total}"
                right = 127 - len(position) * font5x7.CELL_W
                draw_text(canvas, right, y, position, on=False)
                limit = max(1, (right - x - 11) // font5x7.CELL_W)
            draw_text(canvas, x + 10, y, text[:limit], on=not row.inverse)
        elif row.selected or row.text.startswith((">", " ")):
            draw_text(canvas, 8, y, row.text[1:21], on=not row.inverse)
        else:
            draw_text(canvas, MARGIN, y, row.text, on=not row.inverse)
    return canvas
