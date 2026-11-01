# SPDX-License-Identifier: GPL-3.0-or-later
"""A 128x64 SH1106 OLED on I2C, with no dependencies beyond smbus2 (the Pi has it; luma and PIL are not
installed there). Canvas is the 1-bit frame in the controller's own page layout and Display sends it; the
only thing that touches the bus is I2C.write. tests/test_sh1106.py checks the rest."""

WIDTH, HEIGHT = 128, 64
PAGES = HEIGHT // 8
COLUMN_OFFSET = 2   # the SH1106 has a 132-column RAM and a 128-pixel panel centred in it

COMMAND, DATA = 0x00, 0x40   # I2C control bytes: what follows is a command / display data


def init_commands(flip=False, contrast=0x7F):
    """The start-up sequence. `flip` turns the picture 180 degrees (segment remap and COM scan direction)."""
    return [0xAE,                         # display off
            0xD5, 0x80,                   # clock divide / oscillator
            0xA8, HEIGHT - 1,             # multiplex ratio
            0xD3, 0x00,                   # display offset
            0x40,                         # start line 0
            0xAD, 0x8B,                   # internal DC-DC on
            0xA0 if flip else 0xA1,       # segment remap
            0xC0 if flip else 0xC8,       # COM scan direction
            0xDA, 0x12,                   # COM pins
            0x81, contrast,
            0xD9, 0x22,                   # pre-charge
            0xDB, 0x35,                   # VCOM deselect
            0xA4, 0xA6,                   # follow RAM, not inverted
            0xAF]                         # display on


class Canvas:
    """The frame: PAGES pages of WIDTH bytes, bit n of a byte is the pixel n rows below the page's top."""

    def __init__(self):
        self.pages = [bytearray(WIDTH) for _ in range(PAGES)]

    def clear(self, on=False):
        for page in self.pages:
            page[:] = bytes([0xFF if on else 0]) * WIDTH

    def pixel(self, x, y, on=True):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            if on:
                self.pages[y // 8][x] |= 1 << (y % 8)
            else:
                self.pages[y // 8][x] &= ~(1 << (y % 8)) & 0xFF

    def get(self, x, y):
        return bool(self.pages[y // 8][x] >> (y % 8) & 1) if 0 <= x < WIDTH and 0 <= y < HEIGHT else False

    def rect(self, x0, y0, x1, y1, fill=False, on=True):
        """The rectangle with corners (x0, y0) and (x1, y1), both included."""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if fill or x in (x0, x1) or y in (y0, y1):
                    self.pixel(x, y, on)

    def line(self, x0, y0, x1, y1, on=True):
        """Bresenham."""
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.pixel(x0, y0, on)
            if (x0, y0) == (x1, y1):
                return
            e2 = 2 * err
            if e2 >= dy:
                err, x0 = err + dy, x0 + sx
            if e2 <= dx:
                err, y0 = err + dx, y0 + sy


class I2C:
    """smbus2 underneath; `write` sends one transaction, whatever its length."""

    def __init__(self, bus=1, address=0x3C):
        import smbus2
        self.smbus2, self.bus, self.address = smbus2, smbus2.SMBus(bus), address

    def write(self, data):
        self.bus.i2c_rdwr(self.smbus2.i2c_msg.write(self.address, list(data)))


class Display:
    def __init__(self, link, flip=False, contrast=0x7F):
        self.link = link
        self.link.write([COMMAND, *init_commands(flip, contrast)])

    def show(self, canvas):
        for number, page in enumerate(canvas.pages):
            self.link.write([COMMAND, 0xB0 + number, COLUMN_OFFSET & 0x0F, 0x10 | COLUMN_OFFSET >> 4])
            self.link.write([DATA, *page])

    def all_on(self, on=True):
        """The panel lit regardless of RAM (a quick check that it works), or back to the RAM."""
        self.link.write([COMMAND, 0xA5 if on else 0xA4])

    def power(self, on):
        self.link.write([COMMAND, 0xAF if on else 0xAE])
