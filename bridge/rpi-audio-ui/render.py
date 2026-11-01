# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws ui.UI's rows on a sh1106.Canvas with the 5x7 font: ROWS rows of COLS characters in 6x8-pixel cells,
an inverse row as light text on a lit bar. tests/test_sh1106.py checks it."""

import font5x7
import sh1106

MARGIN = 1   # the 21 cells are 126 pixels wide: one blank column each side


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
        if row.inverse:
            canvas.rect(0, y, sh1106.WIDTH - 1, y + font5x7.CELL_H - 1, fill=True)
        draw_text(canvas, MARGIN, y, row.text, on=not row.inverse)
    return canvas
