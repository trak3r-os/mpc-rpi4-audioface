# SPDX-License-Identifier: GPL-3.0-or-later
"""A 5x7 bitmap font for printable ASCII (0x20-0x7E): the classic five-column table, one byte per column,
bit 0 the top row. A glyph plus one blank column is a 6-pixel cell, so a 128-pixel display takes 21
characters; eight pixel rows take eight text rows."""

CELL_W, CELL_H = 6, 8

_COLUMNS = """
00 00 00 00 00 | 00 00 5F 00 00 | 00 07 00 07 00 | 14 7F 14 7F 14 | 24 2A 7F 2A 12 | 23 13 08 64 62
36 49 56 20 50 | 00 05 03 00 00 | 00 1C 22 41 00 | 00 41 22 1C 00 | 14 08 3E 08 14 | 08 08 3E 08 08
00 50 30 00 00 | 08 08 08 08 08 | 00 60 60 00 00 | 20 10 08 04 02 | 3E 51 49 45 3E | 00 42 7F 40 00
42 61 51 49 46 | 21 41 45 4B 31 | 18 14 12 7F 10 | 27 45 45 45 39 | 3C 4A 49 49 30 | 01 71 09 05 03
36 49 49 49 36 | 06 49 49 29 1E | 00 36 36 00 00 | 00 56 36 00 00 | 08 14 22 41 00 | 14 14 14 14 14
00 41 22 14 08 | 02 01 51 09 06 | 32 49 79 41 3E | 7E 11 11 11 7E | 7F 49 49 49 36 | 3E 41 41 41 22
7F 41 41 22 1C | 7F 49 49 49 41 | 7F 09 09 09 01 | 3E 41 49 49 7A | 7F 08 08 08 7F | 00 41 7F 41 00
20 40 41 3F 01 | 7F 08 14 22 41 | 7F 40 40 40 40 | 7F 02 0C 02 7F | 7F 04 08 10 7F | 3E 41 41 41 3E
7F 09 09 09 06 | 3E 41 51 21 5E | 7F 09 19 29 46 | 46 49 49 49 31 | 01 01 7F 01 01 | 3F 40 40 40 3F
1F 20 40 20 1F | 3F 40 38 40 3F | 63 14 08 14 63 | 07 08 70 08 07 | 61 51 49 45 43 | 00 7F 41 41 00
02 04 08 10 20 | 00 41 41 7F 00 | 04 02 01 02 04 | 40 40 40 40 40 | 00 01 02 04 00 | 20 54 54 54 78
7F 48 44 44 38 | 38 44 44 44 20 | 38 44 44 48 7F | 38 54 54 54 18 | 08 7E 09 01 02 | 0C 52 52 52 3E
7F 08 04 04 78 | 00 44 7D 40 00 | 20 40 44 3D 00 | 7F 10 28 44 00 | 00 41 7F 40 00 | 7C 04 18 04 78
7C 08 04 04 78 | 38 44 44 44 38 | 7C 14 14 14 08 | 08 14 14 18 7C | 7C 08 04 04 08 | 48 54 54 54 20
04 3F 44 40 20 | 3C 40 40 20 7C | 1C 20 40 20 1C | 3C 40 30 40 3C | 44 28 10 28 44 | 0C 50 50 50 3C
44 64 54 4C 44 | 00 08 36 41 00 | 00 00 7F 00 00 | 00 41 36 08 00 | 10 08 08 10 08
"""

GLYPHS = [tuple(int(b, 16) for b in glyph.split()) for glyph in _COLUMNS.replace("\n", "|").split("|") if glyph.strip()]
FIRST = 0x20
assert len(GLYPHS) == 0x7F - FIRST and all(len(g) == 5 for g in GLYPHS)


def glyph(char):
    """The five columns of a character; anything outside printable ASCII is a '?'."""
    code = ord(char)
    return GLYPHS[(code if FIRST <= code < 0x7F else ord("?")) - FIRST]
