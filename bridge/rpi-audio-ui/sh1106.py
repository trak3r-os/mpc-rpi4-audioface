# SPDX-License-Identifier: GPL-3.0-or-later
"""A 128x64 SH1106 OLED on I2C, with no dependencies beyond smbus2 (the Pi has it; luma and PIL are not
installed there). Canvas is the 1-bit frame in the controller's own page layout and Display sends it; the
only thing that touches the bus is I2C.write. tests/test_sh1106.py checks the rest."""

import threading
import time
import errno

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

    def close(self):
        self.bus.close()


class Display:
    def __init__(self, link, flip=False, contrast=0x7F):
        self.link = link
        self.pages = [None] * PAGES
        try:
            self.link.write([COMMAND, *init_commands(flip, contrast)])
        except OSError:
            self.close()
            raise

    def close(self):
        if hasattr(self.link, 'close'):
            self.link.close()

    def show(self, canvas):
        for number, page in enumerate(canvas.pages):
            data = bytes(page)
            if data == self.pages[number]:
                continue
            # A failed transfer can leave part of this page changed. Even if the next frame returns
            # to the old pixels, it must rewrite the page rather than trust the previous cache.
            previous = self.pages[number]
            start, end = 0, WIDTH
            if previous is not None:
                changed = [x for x in range(WIDTH) if previous[x] != data[x]]
                start, end = changed[0], changed[-1] + 1
            self.pages[number] = None
            column = COLUMN_OFFSET + start
            self.link.write([COMMAND, 0xB0 + number, column & 0x0F, 0x10 | column >> 4])
            self.link.write([DATA, *page[start:end]])
            self.pages[number] = data

    def contrast(self, value):
        self.link.write([COMMAND, 0x81, value])

    def configure(self, flip, contrast):
        """Sends the start-up sequence again with new settings (the picture in RAM stays)."""
        self.link.write([COMMAND, *init_commands(flip, contrast)])

    def all_on(self, on=True):
        """The panel lit regardless of RAM (a quick check that it works), or back to the RAM."""
        self.link.write([COMMAND, 0xA5 if on else 0xA4])

    def power(self, on):
        self.link.write([COMMAND, 0xAF if on else 0xAE])


class AsyncDisplay:
    """Own all I2C work on one thread. A single replaceable frame prevents an input/render backlog.

    Even a stuck kernel transfer must not hold up GPIO, commands or sleep/wake. The worker reconnects
    after bus errors and applies the latest settings/frame, rather than replaying stale screens.
    """

    def __init__(self, factory, flip=False, contrast=0x7F, log=print, retry_s=0.01, max_retry_s=0.05):
        self.factory, self.log, self.retry_s = factory, log, retry_s
        self.max_retry_s = max(retry_s, max_retry_s)
        self.condition = threading.Condition()
        self.flip, self.value, self.on, self.frame = flip, contrast, True, None
        self.revision, self.stopping = 0, False
        self.thread = threading.Thread(target=self.run, name='oled-i2c', daemon=True)
        self.thread.start()

    def update(self, **values):
        with self.condition:
            for key, value in values.items():
                setattr(self, key, value)
            self.revision += 1
            self.condition.notify()

    def show(self, canvas):
        frame = Canvas()
        frame.pages = [bytes(page) for page in canvas.pages]
        self.update(frame=frame)

    def contrast(self, value):
        self.update(value=value)

    def configure(self, flip, contrast):
        self.update(flip=flip, value=contrast)

    def power(self, on):
        self.update(on=on)

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify()
        # A stalled bus must not prevent the service from stopping either.
        self.thread.join(timeout=0.5)

    def run(self):
        display, applied, sent = None, None, -1
        failures, failed_at, next_slow_log = 0, 0.0, 0.0
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.stopping or self.revision != sent)
                    if self.stopping:
                        return
                    revision = self.revision
                    flip, value, on, frame = self.flip, self.value, self.on, self.frame
                started = time.monotonic()
                try:
                    if display is None:
                        display = self.factory(flip, value)
                        applied = (flip, value, True)
                    if flip != applied[0]:
                        display.configure(flip, value)
                        applied = (flip, value, True)
                    elif value != applied[1]:
                        display.contrast(value)
                    if on and frame is not None:
                        display.show(frame)
                    if on != applied[2]:
                        display.power(on)
                    applied, sent = (flip, value, on), revision
                    if failures:
                        self.log(f'rpi-audio-ui: OLED recovered in {time.monotonic() - failed_at:.3f}s '
                                 f'after {failures} failed transfers')
                        failures = 0
                    elapsed = time.monotonic() - started
                    if elapsed >= 0.25 and started >= next_slow_log:
                        self.log(f'rpi-audio-ui: slow OLED transfer: {elapsed:.3f}s (input continues)')
                        next_slow_log = started + 10
                except OSError as error:
                    if not failures:
                        failed_at = time.monotonic()
                        self.log(f'rpi-audio-ui: OLED I2C error: {error}; retrying in background')
                    failures += 1
                    # An I2C transfer error does not invalidate the open adapter. Reinitialising
                    # the OLED switches it off/on and causes flashing during noisy bursts.
                    # Only reopen a removed adapter or invalid descriptor; retry page data otherwise.
                    if display is not None and error.errno in (errno.EBADF, errno.ENODEV):
                        display.close()
                        display, applied = None, None
                    delay = min(self.max_retry_s, self.retry_s * 2 ** min(failures - 1, 16))
                    with self.condition:
                        self.condition.wait_for(lambda: self.stopping, timeout=delay)
        finally:
            if display is not None:
                try:
                    display.power(False)
                except OSError:
                    pass
                display.close()
