#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render README diagrams as ordinary PNG images. Needs Pillow and DejaVu Sans; no network or Pi."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/img"
FONTS = Path("/usr/share/fonts/truetype/dejavu")
PAPER, INK, MUTED = "#f3f7fa", "#183348", "#506878"
TEAL, BLUE, PURPLE = "#087d76", "#2563ad", "#7652a6"


def font(size=24, bold=False):
    return ImageFont.truetype(str(FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def canvas(title, subtitle, width=1440, height=680):
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)
    draw.text((44, 28), title, font=font(34, True), fill=INK)
    draw.text((44, 84), subtitle, font=font(22), fill=MUTED)
    return image, draw


def card(draw, bounds, title, detail, color=TEAL, title_size=25, detail_size=21):
    x0, y0, x1, y1 = bounds
    draw.rounded_rectangle(bounds, 16, fill="white", outline=color, width=3)
    draw.text(((x0 + x1) / 2, y0 + 23), title, font=font(title_size, True), fill=INK, anchor="mt")
    draw.multiline_text(((x0 + x1) / 2, y0 + 65), detail, font=font(detail_size),
                        fill=MUTED, anchor="ma", align="center", spacing=8)


def arrow(draw, points, color=TEAL, both=False, dashed=False):
    for start, end in zip(points, points[1:]):
        if dashed:
            distance = math.dist(start, end)
            for at in range(0, int(distance), 20):
                p = tuple(a + (b - a) * at / distance for a, b in zip(start, end))
                q = tuple(a + (b - a) * min(at + 12, distance) / distance for a, b in zip(start, end))
                draw.line((p, q), fill=color, width=3)
        else:
            draw.line((start, end), fill=color, width=4)
    for tip, previous in [(points[-1], points[-2])] + ([(points[0], points[1])] if both else []):
        angle = math.atan2(tip[1] - previous[1], tip[0] - previous[0])
        head = [tip] + [(tip[0] - 16 * math.cos(angle + d), tip[1] - 16 * math.sin(angle + d))
                        for d in (-0.45, 0.45)]
        draw.polygon(head, fill=color)


def label(draw, xy, text, color=MUTED, size=20):
    draw.multiline_text(xy, text, font=font(size), fill=color, anchor="mm", align="center", spacing=7)


def overview():
    image, draw = canvas("Your USB gear, one host interface",
                         "USB host clock mode · channel assignments are remembered")
    draw.rounded_rectangle((35, 145, 420, 588), 20, outline="#b4c8d6", width=2)
    draw.text((62, 165), "Pi USB-A ports", font=font(23, True), fill=MUTED)
    for y, name, detail in [(220, "Guitar processor", "Audio + MIDI"), (345, "Mixer / interface", "Audio"),
                            (470, "MIDI keyboard", "MIDI")]:
        card(draw, (60, y, 393, y + 98), name, detail, title_size=23, detail_size=19)
        draw.line([(394, y + 49), (477, y + 49), (477, 394)], fill=TEAL, width=4)
    arrow(draw, [(477, 394), (552, 394)])
    card(draw, (567, 310, 875, 478), "Raspberry Pi 4", "rpi-audio\nAudio + MIDI routing")
    card(draw, (1100, 310, 1393, 478), "USB host", "Computer or sampler\nOne audio interface")
    arrow(draw, [(893, 394), (1082, 394)], both=True)
    label(draw, (989, 345), "USB-C", size=22)
    label(draw, (989, 508), "26 in × 26 out\n4 MIDI cables", size=20)
    draw.text((44, 625), "Host IN = Pi → host.  Host OUT = host → Pi.  Numbers describe the host's interface.",
              font=font(22), fill=MUTED)
    image.save(OUT / "readme-overview.png", optimize=True)


def architecture():
    image, draw = canvas("Inside the Pi: USB host clock mode",
                         "Audio uses JACK and resampling bridges; MIDI travels separately.", width=1600, height=875)
    draw.rounded_rectangle((48, 310, 1200, 750), 20, fill="#e9f2f7", outline="#91aebf", width=2)
    draw.text((600, 332), "Raspberry Pi 4", font=font(25, True), fill=MUTED)
    card(draw, (130, 142, 450, 252), "USB host", "Computer or sampler", color=BLUE)
    card(draw, (130, 390, 450, 540), "USB gadget", "UAC2 audio + USB MIDI\n26 × 26 audio channels")
    arrow(draw, [(290, 270), (290, 373)], both=True, color=BLUE)
    label(draw, (352, 286), "USB-C", color=BLUE)
    card(draw, (590, 390, 815, 540), "JACK", "Audio engine\nHost's sample clock", title_size=25, detail_size=19)
    arrow(draw, [(467, 465), (572, 465)], both=True)
    label(draw, (520, 423), "Audio\n26 × 26", size=18)
    card(draw, (900, 390, 1155, 540), "zita bridge", "48 ↔ 44.1 kHz\nRate conversion", detail_size=20)
    card(draw, (900, 580, 1155, 730), "zita bridge", "48 ↔ 44.1 kHz\nRate conversion", detail_size=20)
    arrow(draw, [(832, 465), (883, 465)], both=True)
    arrow(draw, [(832, 500), (857, 500), (857, 655), (883, 655)], both=True)
    card(draw, (130, 613, 450, 730), "rpi-audiod", "Commands, levels, scenes", color=PURPLE, detail_size=20)
    arrow(draw, [(290, 557), (290, 596)], both=True, color=PURPLE)
    label(draw, (469, 577), "MIDI cable 1: control", color=PURPLE, size=18)
    card(draw, (1300, 390, 1560, 540), "Guitar processor", "Audio\nMIDI cable 2", title_size=22, detail_size=20)
    card(draw, (1300, 580, 1560, 730), "Mixer", "Audio", title_size=25, detail_size=20)
    for y, channels in [(465, "IN 3–8\nOUT 5–8"), (655, "IN 1–2\nOUT 3–4")]:
        arrow(draw, [(1173, y), (1283, y)], both=True)
        label(draw, (1230, y - 47), channels, size=17)
    draw.text((44, 790), "Rates and channel blocks are examples. MIDI pass-through does not use the audio bridges.",
              font=font(22), fill=MUTED)
    draw.text((44, 832), "Hub uses a local DAC clock and independent USB/network adapters instead; "
              "see the mode comparison.", font=font(21), fill=MUTED)
    image.save(OUT / "readme-architecture.png", optimize=True)


def midi_control():
    image, draw = canvas("Control the Pi over USB MIDI",
                         "Cable 1 is the control port · other cables carry your devices' MIDI", height=870)
    card(draw, (65, 140, 525, 250), "Host", "For example, rpi-audio Panel in MPC", title_size=26, detail_size=20)
    card(draw, (920, 140, 1380, 250), "rpi-audiod", "Running on the Pi", color=PURPLE, title_size=26)
    for x in (295, 1150):
        for y in range(268, 776, 20):
            draw.line((x, y, x, y + 10), fill="#a2bacb", width=2)
    messages = [(310, 'SysEx: "status"', False), (390, "Devices, channels, levels, presets", True),
                (470, 'SysEx: "mute GP150 in on"', False), (550, '"ok"', True),
                (630, "CC 32+N on channel 16: level of device at IN channel N", False),
                (710, "Program Change 1 on channel 16: load scene 2", False)]
    for y, text, response in messages:
        label(draw, (723, y - 25), text, color=PURPLE if response else INK, size=21)
        arrow(draw, [(1150, y), (295, y)] if response else [(295, y), (1150, y)],
              color=PURPLE if response else TEAL, dashed=response)
    draw.text((44, 807), "Program Change values are zero-based: value 1 loads scene 2. "
              "Commands and audio are separate.", font=font(22), fill=MUTED)
    image.save(OUT / "readme-midi-control.png", optimize=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    overview()
    architecture()
    midi_control()
    print("Built three README diagrams in docs/img/")
