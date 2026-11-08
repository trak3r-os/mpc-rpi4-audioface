#!/usr/bin/env python3
"""Render the rpi5-audioface overview video: silent slides drawn with Pillow, a procedural music bed, ffmpeg.

    python3 tools/video/make-overview.py            # -> out/video/rpi5-audioface-overview.mp4
    python3 tools/video/make-overview.py --frames   # only the slide PNGs (out/video/build/), no encoding

Needs Python 3 with Pillow and numpy, DejaVu fonts, and ffmpeg. No network, no Pi, no downloaded assets:
every diagram is drawn here, the OLED screens are cropped from docs/manual/img/ or rendered with the
project's own OLED renderer (bridge/rpi-audio-ui), and the music comes from music.py.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "bridge/rpi-audio-ui"))

W, H, S = 1920, 1080, 2          # output size, supersampling factor (everything is drawn at 2x, then reduced)
FPS = 25
SLIDE_FADE, STAGE_FADE = 0.9, 0.4  # seconds of crossfade between slides, and between reveal steps of a slide
SPEED = 0.92                       # global timing factor

PAPER, INK, MUTED, LINE = "#f4f7fb", "#17304a", "#4d6178", "#cfdbe8"
TEAL, BLUE, PURPLE, AMBER, RED = "#087d76", "#2563ad", "#7660ac", "#b7791f", "#b4412f"
WHITE, NIGHT, TERM = "#ffffff", "#10243a", "#0d1a2a"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
OLED = ROOT / "docs/manual/img"
REPO_URL = "github.com/trak3r-os/rpi5-audioface"


class Cv:
    """A 1920x1080 canvas in logical coordinates, drawn at S times the size for smooth edges."""

    _fonts = {}

    def __init__(self, bg=PAPER):
        self.im = Image.new("RGB", (W * S, H * S), bg)
        self.d = ImageDraw.Draw(self.im)

    def font(self, size, bold=False, mono=False):
        key = (size, bold, mono)
        if key not in self._fonts:
            name = ("DejaVuSansMono" if mono else "DejaVuSans") + ("-Bold" if bold else "") + ".ttf"
            self._fonts[key] = ImageFont.truetype(str(FONT_DIR / name), size * S)
        return self._fonts[key]

    def tw(self, s, size, bold=False, mono=False):
        return self.d.textlength(s, font=self.font(size, bold, mono)) / S

    def text(self, x, y, s, size=34, color=INK, bold=False, mono=False, anchor="la"):
        self.d.text((x * S, y * S), s, font=self.font(size, bold, mono), fill=color, anchor=anchor)

    def wrap(self, s, size, maxw, bold=False, mono=False):
        lines = []
        for para in s.split("\n"):
            cur = ""
            for word in para.split(" "):
                trial = (cur + " " + word).strip()
                if cur and self.tw(trial, size, bold, mono) > maxw:
                    lines.append(cur)
                    cur = word
                else:
                    cur = trial
            lines.append(cur)
        return lines

    def para(self, x, y, s, size=32, color=MUTED, maxw=600, bold=False, gap=1.4, mono=False):
        """Wrapped paragraph; returns the y below it."""
        for line in self.wrap(s, size, maxw, bold, mono):
            self.text(x, y, line, size, color, bold, mono)
            y += size * gap
        return y

    def box(self, x0, y0, x1, y1, fill=WHITE, outline=LINE, r=22, w=2, bar=None):
        self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], r * S, fill=fill, outline=outline, width=w * S)
        if bar:
            self.d.rounded_rectangle([x0 * S, y0 * S, (x0 + 12) * S, y1 * S], 6 * S, fill=bar)

    def card(self, x0, y0, x1, y1, title, body="", color=TEAL, tsize=38, bsize=30):
        """White card with a coloured left bar, a bold title and a wrapped body."""
        self.box(x0, y0, x1, y1, bar=color)
        self.text(x0 + 36, y0 + 24, title, tsize, INK, bold=True)
        if body:
            self.para(x0 + 36, y0 + 24 + tsize * 1.5, body, bsize, MUTED, x1 - x0 - 72)

    def pill(self, cx, cy, s, size=28, fill=TEAL, color=WHITE, padx=22, h=None):
        w = self.tw(s, size, True) + 2 * padx
        h = h or size + 24
        self.d.rounded_rectangle([(cx - w / 2) * S, (cy - h / 2) * S, (cx + w / 2) * S, (cy + h / 2) * S], h / 2 * S, fill=fill)
        self.text(cx, cy, s, size, color, bold=True, anchor="mm")

    def line(self, pts, color=INK, w=6):
        self.d.line([(x * S, y * S) for x, y in pts], fill=color, width=w * S, joint="curve")

    def head(self, tip, frm, color, size=28):
        import math
        a = math.atan2(tip[1] - frm[1], tip[0] - frm[0])
        p1 = (tip[0] - size * math.cos(a - 0.42), tip[1] - size * math.sin(a - 0.42))
        p2 = (tip[0] - size * math.cos(a + 0.42), tip[1] - size * math.sin(a + 0.42))
        self.d.polygon([(tip[0] * S, tip[1] * S), (p1[0] * S, p1[1] * S), (p2[0] * S, p2[1] * S)], fill=color)

    def arrow(self, pts, color=TEAL, w=7, both=False):
        """Polyline with an arrowhead at the end (and at the start when both)."""
        self.line(pts, color, w)
        self.head(pts[-1], pts[-2], color)
        if both:
            self.head(pts[0], pts[1], color)

    def oled(self, img, x, y, w):
        h = int(w * img.height / img.width)
        ratio = w * S / img.width
        mode = Image.Resampling.NEAREST if abs(ratio - round(ratio)) < 1e-6 else Image.Resampling.LANCZOS
        self.im.paste(img.resize((w * S, h * S), mode), (x * S, y * S))
        self.d.rectangle([x * S - 3, y * S - 3, (x + w) * S + 3, (y + h) * S + 3], outline=INK, width=6)
        return h

    def done(self):
        return self.im.resize((W, H), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------------------------- OLED screens

def crop_oled(name, side):
    """One of the two 640x320 screens in a manual figure (pair layout: 1440x450)."""
    im = Image.open(OLED / name).convert("RGB")
    x = 42 if side == 0 else 758
    return im.crop((x, 125, x + 640, 445))


def render_usb_ports(mixer_bus):
    """The Status > USB ports screen, drawn by the project's own OLED renderer from a sample status."""
    import render
    import sh1106
    import ui
    mixer = {"identity": "usb-1-2-0000:0001", "card": "CODEC", "name": "Mixer",
             "usb": {"bus": mixer_bus, "port": f"{mixer_bus}-2", "speed": 12, "by_port": True},
             "in": {"channels": 2, "fs_load": 196}, "out": {"channels": 2, "fs_load": 192}}
    if mixer_bus == 3:
        mixer["out"]["blocked"] = "USB full-speed budget: needs 192 B, 0 B of 1099 B free on bus 3"
        buses = [{"bus": 1, "fs_load": 0, "fs_demand": 0, "fs_budget": 1099},
                 {"bus": 3, "fs_load": 1099, "fs_demand": 1291, "fs_budget": 1099}]
    else:
        buses = [{"bus": 1, "fs_load": 388, "fs_demand": 388, "fs_budget": 1099},
                 {"bus": 3, "fs_load": 903, "fs_demand": 903, "fs_budget": 1099}]
    status = {"usb_buses": buses, "devices": [
        {"identity": "usb-1-1-0000:0002", "card": "GP150", "name": "Guitar Rig",
         "usb": {"bus": 1, "port": "1-1", "speed": 480}},
        {"identity": "usb-3-1-0000:0003", "card": "Tracker", "name": "Tracker",
         "usb": {"bus": 3, "port": "3-1", "speed": 12}, "in": {"channels": 8, "fs_load": 720},
         "out": {"channels": 2, "fs_load": 183}},
        mixer]}
    interface = ui.UI()
    interface.stack = [ui.USBPorts()]
    interface.hardware = {"wifi": {"state": "up", "signal": 88, "name": "Studio", "ip": "192.0.2.10"},
                          "usb_state": "configured", "devices": []}
    canvas = render.draw_rows(sh1106.Canvas(), interface.render(status))
    img = Image.new("RGB", (128, 64), "#02090d")
    for y in range(64):
        for x in range(128):
            if canvas.get(x, y):
                img.putpixel((x, y), (213, 245, 255))
    return img.resize((640, 320), Image.Resampling.NEAREST)


# ---------------------------------------------------------------------------------------------- slide helpers

def device_chip(c, x, y, w, h, title, sub="", color=TEAL):
    c.box(x, y, x + w, y + h, bar=color)
    c.text(x + 34, y + 18, title, 32, INK, bold=True)
    if sub:
        c.text(x + 34, y + 62, sub, 26, MUTED)


def term(c, x, y, w, lines, size=34):
    """Terminal panel; each line is (text, color)."""
    h = 40 + len(lines) * int(size * 1.6)
    c.box(x, y, x + w, y + h, fill=TERM, outline=TERM, r=20)
    for i, (s, col) in enumerate(lines):
        c.text(x + 36, y + 26 + i * int(size * 1.6), s, size, col, mono=True)
    return y + h


def bus_row(c, x, y, w, name, load, demand, budget, chips, hot=False):
    c.box(x, y, x + w, y + 168, outline=RED if hot else LINE, w=3 if hot else 2)
    c.text(x + 28, y + 14, f"Bus {name}", 30, INK, bold=True)
    c.text(x + w - 28, y + 14, f"FS {load}/{budget}" + ("  !" if hot else ""), 30, RED if hot else MUTED, bold=True, anchor="ra")
    bx0, bx1, by = x + 28, x + w - 28, y + 62
    c.box(bx0, by, bx1, by + 30, fill="#e6edf5", outline="#e6edf5", r=15)
    if load:
        c.box(bx0, by, bx0 + (bx1 - bx0) * min(load, budget) / budget, by + 30, fill=RED if hot else TEAL, outline=RED if hot else TEAL, r=15)
    c.text(x + 28, y + 110, chips, 26, MUTED)


def tick_bullets(c, x, y, items, size=32, maxw=800, color=TEAL, gap=22):
    for head, body in items:
        c.d.ellipse([x * S, (y + size * 0.42) * S, (x + 16) * S, (y + size * 0.42 + 16) * S], fill=color)
        c.text(x + 36, y, head, size, INK, bold=True)
        y = c.para(x + 36, y + size * 1.4, body, size - 4, MUTED, maxw - 36, gap=1.35) + gap
    return y


# ---------------------------------------------------------------------------------------------- the slides

def s_title(c, k):
    c.box(0, 0, 36, H, fill=TEAL, outline=TEAL, r=0)
    c.text(140, 250, "rpi5-audioface", 132, WHITE, bold=True)
    c.text(144, 410, "A Raspberry Pi 5 that turns many USB audio and MIDI devices", 46, "#cfe4f2")
    c.text(144, 475, "into one USB audio interface for your computer or sampler.", 46, "#cfe4f2")
    if k >= 2:
        for i, (label, col) in enumerate((("Host", BLUE), ("Raspberry Pi 5", TEAL), ("USB devices", PURPLE))):
            x = 144 + i * 560
            c.box(x, 640, x + 440, 780, fill=NIGHT, outline=col, r=26, w=4)
            c.text(x + 220, 710, label, 40, WHITE, bold=True, anchor="mm")
            if i < 2:
                c.arrow([(x + 450, 710), (x + 550, 710)], "#7fd1c7", both=True)
        c.text(144, 870, "An instructional overview  ·  GPL-3.0-or-later", 32, "#8fb0c8")


def s_what(c, k):
    cards = [("One interface for the host",
              "The host sees one class-compliant USB audio interface (UAC2): 26 in x 26 out, 44.1 kHz, 16-bit, plus 4 USB MIDI ports.", BLUE),
             ("Many devices behind it",
              "Mixers, guitar processors, synths and trackers plug into the Pi's USB-A ports. Each device gets its own channels.", TEAL),
             ("You decide the routing",
              "Sticky channel slots, a Hub mode with explicit routes, names, levels, mutes and 8 saved presets.", PURPLE),
             ("Control it from anywhere",
              "Use the OLED menu on the box, or MIDI over the same USB cable from the host. No network and no app needed.", AMBER)]
    for i, (t, b, col) in enumerate(cards[:k]):
        x, y = 100 + (i % 2) * 870, 230 + (i // 2) * 370
        c.card(x, y, x + 850, y + 340, t, b, col, tsize=40, bsize=34)


def s_flow(c, k):
    c.box(100, 320, 460, 740, bar=BLUE)
    c.text(146, 350, "Host", 48, INK, bold=True)
    c.para(146, 425, "Computer, DAW or standalone sampler", 32, MUTED, 290)
    c.para(146, 610, "Selects the interface called rpi-audio", 30, BLUE, 290, bold=True)
    c.box(700, 250, 1220, 800, bar=TEAL)
    c.text(746, 272, "Raspberry Pi 5", 44, INK, bold=True)
    for i, (t, sub) in enumerate((("USB gadget", "UAC2 audio + USB MIDI"), ("JACK + rpi-audiod", "slots, routes, levels"), ("USB host ports", "USB-A sockets"))):
        y = 350 + i * 145
        c.box(746, y, 1190, y + 122, fill="#eef5f9")
        c.text(776, y + 18, t, 34, INK, bold=True)
        c.text(776, y + 66, sub, 28, MUTED)
    c.box(1460, 250, 1820, 805, fill=PAPER, outline=PAPER)
    names = (("Mixer", "USB audio"), ("Guitar processor", "USB audio"), ("Synth / tracker", "USB audio + MIDI"), ("MIDI keyboard", "USB MIDI"))
    for i, (t, sub) in enumerate(names):
        device_chip(c, 1470, 250 + i * 145, 350, 122, t, sub, PURPLE)
    if k >= 2:
        c.arrow([(690, 470), (470, 470)], TEAL, both=False)
        c.arrow([(470, 590), (690, 590)], BLUE)
        c.text(580, 360, "USB-C", 34, INK, bold=True, anchor="ma")
        c.text(580, 404, "gadget port", 28, MUTED, anchor="ma")
        c.line([(1450, 310), (1450, 745)], MUTED, 6)
        for i in range(4):
            c.line([(1450, 311 + i * 145), (1470, 311 + i * 145)], MUTED, 6)
        c.arrow([(1450, 470), (1230, 470)], TEAL)
        c.arrow([(1230, 590), (1450, 590)], BLUE)
        c.text(1340, 360, "USB-A", 34, INK, bold=True, anchor="ma")
        c.text(1340, 404, "Pi is the host", 28, MUTED, anchor="ma")
    if k >= 3:
        c.box(300, 880, 340, 920, fill=TEAL, outline=TEAL, r=8)
        c.text(360, 880, "IN: devices to Pi to host (what the host records)", 32, INK)
        c.box(1250, 880, 1290, 920, fill=BLUE, outline=BLUE, r=8)
        c.text(1310, 880, "OUT: host to Pi to devices", 32, INK)


def s_hardware(c, k):
    c.text(100, 215, "You need", 44, TEAL, bold=True)
    tick_bullets(c, 100, 285, [
        ("Raspberry Pi 5 + power supply", "A 5 A USB-PD supply is best. With a 3 A supply the USB-A ports are limited to 600 mA in total. A Pi 4 works too."),
        ("USB-C power / data splitter", "The Pi's single USB-C port is both its power input and its gadget port. The splitter separates the two."),
        ("USB audio and MIDI devices", "On the Pi's USB-A ports. A host with a USB port, connected directly (not through a hub)."),
        ("Raspberry Pi OS, 64-bit", "On a microSD card. The Pi uses JACK; PipeWire is not needed."),
    ], 34, 820, TEAL, 18)
    if k >= 2:
        c.box(1030, 200, 1820, 930, fill=WHITE, outline=LINE)
        c.text(1070, 215, "Optional", 44, BLUE, bold=True)
        tick_bullets(c, 1070, 285, [
            ("OLED + rotary encoder", "128x64 screen, encoder with push, CONFIRM and BACK buttons: the on-box menu."),
            ("pHAT DAC", "Local line output and the 48 kHz clock for Hub mode."),
            ("Ethernet or Wi-Fi", "Setup, administration and optional network outputs."),
        ], 34, 700, BLUE, 18)


def s_cables(c, k):
    device_chip(c, 100, 230, 360, 130, "Power supply", "USB-C", AMBER)
    device_chip(c, 100, 700, 360, 130, "Host", "computer or sampler", BLUE)
    c.box(700, 330, 1120, 760, bar=TEAL)
    c.para(750, 350, "USB-C power / data splitter", 34, INK, 330, bold=True)
    c.text(910, 640, "one cable in,", 28, MUTED, anchor="ma")
    c.text(910, 676, "two ports out", 28, MUTED, anchor="ma")
    c.pill(690, 540, "POWER", 28, AMBER)
    c.pill(690, 678, "USB2 DATA", 28, BLUE)
    c.pill(1130, 563, "DATA POWER", 28, TEAL)
    device_chip(c, 1400, 330, 420, 230, "Raspberry Pi 5", "", TEAL)
    c.para(1436, 400, "USB-C port: power in and gadget (device mode)", 28, MUTED, 360)
    if k >= 1:
        c.arrow([(460, 295), (560, 295), (560, 540), (590, 540)], AMBER)
        c.arrow([(1250, 563), (1300, 563), (1300, 445), (1400, 445)], TEAL)
    if k >= 2:
        c.arrow([(590, 678), (560, 678), (560, 765), (470, 765)], BLUE, both=True)
    if k >= 3:
        device_chip(c, 1400, 700, 420, 130, "USB devices", "plug into the USB-A sockets", PURPLE)
        c.arrow([(1610, 700), (1610, 570)], PURPLE, both=True)
        c.para(100, 905, "Labels follow the splitter used in this project; other splitters may differ. Use data cables: charge-only cables do not work.", 28, MUTED, 1700)


def s_install(c, k):
    G, Y, M = "#8fe0c8", "#f4d58d", "#8aa4bd"
    term(c, 100, 215, 1720, [
        ("$ git clone https://github.com/trak3r-os/rpi5-audioface.git", G),
        ("$ cd rpi5-audioface", G),
        ("$ sudo ./install.sh", Y),
        ("$ sudo reboot        # only if the installer enabled the USB gadget overlay", M),
    ][:max(1, min(4, k + 2))], 36)
    if k >= 2:
        c.card(100, 560, 560, 910, "What it sets up", "The USB gadget and the rpi-audiod service, both started at boot. Existing settings in /etc/rpi-audio are kept.", TEAL, 36, 30)
    if k >= 3:
        c.card(590, 560, 1170, 910, "Update and remove", "Update: git pull && sudo ./install.sh\nRemove: sudo ./install.sh --uninstall", BLUE, 36, 30)
        c.card(1200, 560, 1820, 910, "Optional extras", "--network adds the network audio adapters.\n--hat adds the OLED meter helper.", PURPLE, 36, 30)


def s_connect(c, k):
    steps = [("1", "Plug the splitter's data side into the host", "Directly, not through a hub.", BLUE),
             ("2", "On the Pi, check the installation", None, TEAL),
             ("3", "On the host, pick the interface", "Look for an audio interface and MIDI ports named rpi-audio.", PURPLE)]
    for i, (n, t, b, col) in enumerate(steps[:k]):
        y = 220 + i * 215
        c.box(100, y, 1180, y + 190, bar=col)
        c.d.ellipse([140 * S, (y + 40) * S, 220 * S, (y + 120) * S], fill=col)
        c.text(180, y + 80, n, 44, WHITE, bold=True, anchor="mm")
        c.text(250, y + 24, t, 36, INK, bold=True)
        if b:
            c.para(250, y + 82, b, 30, MUTED, 880)
        else:
            c.text(250, y + 84, "rpi-audiod doctor", 32, TEAL, mono=True, bold=True)
            c.text(250, y + 130, "rpi-audiod status", 32, TEAL, mono=True, bold=True)
    if k >= 2:
        c.card(1230, 220, 1820, 410, "doctor", "One line per check: controller, services, governor, power.", TEAL, 34, 28)
        c.card(1230, 435, 1820, 640, "status", "The gadget, connected devices, channel blocks, levels, names and presets.", TEAL, 34, 28)
    if k >= 3:
        c.box(100, 880, 1820, 975, fill="#eaf1f8", outline="#eaf1f8", r=18)
        c.text(130, 927, "Tested: a Linux laptop and an Akai Force (example host; notes in docs/hosts/). macOS and Windows: not tested.", 28, INK, anchor="lm")


def strip(c, y, label, blocks, color_of):
    x0, cw = 160, 61
    c.text(100, y - 52, label, 30, INK, bold=True)
    for n in range(26):
        x = x0 + n * cw
        col = next((color for a, b, color, _ in blocks if a <= n + 1 <= b), None)
        c.box(x, y, x + cw - 4, y + 64, fill=col or "#e6edf5", outline=col or "#d5dfea", r=8, w=1)
        c.text(x + cw / 2 - 2, y + 32, str(n + 1), 24, WHITE if col else "#8aa0b5", bold=True, anchor="mm")
    for a, b, col, name in blocks:
        mid = x0 + ((a - 1) + b) / 2 * cw - 2
        c.text(mid, y + 74, name, 26, col, bold=True, anchor="ma")


def s_slots(c, k):
    blocks_in = [(1, 2, TEAL, "Mixer"), (3, 8, BLUE, "Guitar processor"), (9, 10, PURPLE, "Synth")]
    blocks_out = [(3, 4, TEAL, "Mixer"), (5, 8, BLUE, "Guitar processor")]
    strip(c, 290, "IN: Pi to host (26 channels)", blocks_in, None)
    strip(c, 480, "OUT: host to Pi (26 channels)", blocks_out, None)
    c.text(1820, 215, "example assignment", 26, MUTED, anchor="ra")
    if k >= 2:
        c.card(100, 640, 940, 920, "Sticky slots", "Each device keeps its block. Unplug it, reboot the Pi, plug it back: it gets the same channels, so your host project keeps working.", TEAL, 36, 30)
    if k >= 3:
        c.card(980, 640, 1820, 920, "MIDI gets cables", "Each MIDI port of a device gets its own gadget cable. Cable 1 is reserved as the control port. Cables are not MIDI channels.", PURPLE, 36, 30)


def s_modes(c, k):
    modes = [("USB host clock", "Original mode", "The Pi follows the host's sample clock. Each device gets sticky channels automatically.", BLUE),
             ("Hub", "DAC + USB + network", "The pHAT DAC runs a steady 48 kHz engine. You choose explicit routes, and the Pi keeps working with the host unplugged.", TEAL),
             ("Standalone DAC", "No host at all", "Route USB devices to each other and to the local DAC, without the USB audio bridge.", PURPLE)]
    for i, (t, sub, b, col) in enumerate(modes[:k]):
        x = 100 + i * 590
        c.box(x, 230, x + 550, 690, bar=col)
        c.text(x + 36, 256, t, 42, INK, bold=True)
        c.text(x + 36, 316, sub, 30, col, bold=True)
        c.para(x + 36, 380, b, 32, MUTED, 480)
    if k >= 3:
        c.text(100, 770, "Choose it in the OLED menu: Outputs > Audio mode. The Pi asks first, because audio pauses.", 32, INK)
        c.text(100, 826, "Network outputs (RTP/PCM, Link Audio) are send-only and start disabled.", 28, MUTED)


def s_hub(c, k):
    srcs = ["Mixer", "Guitar processor", "Synth", "USB host"]
    dsts = [("pHAT DAC", "listen locally"), ("USB host", "record over the cable"), ("Network RTP", "stereo send"), ("Link Audio", "stereo send")]
    for i, s in enumerate(srcs):
        c.box(100, 210 + i * 76, 460, 276 + i * 76, bar=TEAL)
        c.text(140, 243 + i * 76, s, 30, INK, bold=True, anchor="lm")
    c.box(640, 330, 960, 456, fill="#eaf6f4", outline=TEAL, w=3)
    c.text(800, 372, "Routes", 38, TEAL, bold=True, anchor="mm")
    c.text(800, 418, "source > destination", 26, MUTED, anchor="mm")
    c.arrow([(470, 393), (630, 393)], TEAL)
    for i, (d, sub) in enumerate(dsts):
        y = 210 + i * 76
        c.box(1160, y, 1560, y + 66, bar=BLUE)
        c.text(1200, y + 33, d, 30, INK, bold=True, anchor="lm")
        c.arrow([(970, 393), (1010, 393), (1010, y + 33), (1150, y + 33)], BLUE, w=5)
    c.para(1600, 260, "Several sources can feed one destination (they add up). One source can feed several. A device is never routed to itself.", 28, MUTED, 220, gap=1.3)
    if k >= 2:
        c.text(100, 535, "On the OLED: Send audio", 36, INK, bold=True)
        c.text(100, 595, "1. Choose the source", 30, TEAL, bold=True)
        c.oled(crop_oled("08-routes.png", 0), 100, 640, 560)
        c.text(740, 595, "2. Tick the destinations", 30, TEAL, bold=True)
        c.oled(crop_oled("08-routes.png", 1), 740, 640, 560)
        c.para(1360, 640, "A route waits, marked [~], until its device is present. Mute or change levels per device under Levels & mute.", 30, MUTED, 450)


def s_menu(c, k):
    for i, (t, sub, col, x) in enumerate((("Turn + push", "move, select", TEAL, 250), ("CONFIRM", "same as push", BLUE, 540), ("BACK", "return or cancel", BLUE, 830))):
        r = 70 if i == 0 else 50
        c.d.ellipse([(x - r) * S, (300 - r) * S, (x + r) * S, (300 + r) * S], fill=WHITE, outline=col, width=8 * S)
    if k >= 1:
        for t, sub, x in (("Turn + push", "move, select", 250), ("CONFIRM", "same as push", 540), ("BACK", "return or cancel", 830)):
            c.text(x, 392, t, 30, INK, bold=True, anchor="ma")
            c.text(x, 432, sub, 26, MUTED, anchor="ma")
    if k >= 2:
        c.box(100, 500, 1000, 960, bar=TEAL)
        items = [("Send audio", "route sources to destinations"), ("Outputs", "pHAT, USB host, network; Audio mode"),
                 ("Levels & mute", "per device"), ("MIDI", "route between devices"), ("Scenes", "8 slots: load and save"),
                 ("Connections", "host, Wi-Fi, devices and channels"), ("Status", "meters, buffers, events, USB ports"),
                 ("Settings", "sleep, saver, brightness, flip")]
        for i, (a, b) in enumerate(items):
            y = 525 + i * 52
            c.text(140, y, a, 29, TEAL if a == "Status" else INK, bold=True)
            c.text(400, y, b, 28, MUTED)
    if k >= 3:
        c.text(1180, 200, "Overview, with live meters", 28, MUTED)
        c.oled(crop_oled("04-overview.png", 1), 1180, 240, 640)
        c.text(1180, 590, "Connections", 28, MUTED)
        c.oled(crop_oled("05-connections.png", 1), 1180, 630, 640)


def s_usbports(c, k):
    c.text(100, 200, "Before: bus 3 is over budget", 30, RED, bold=True)
    c.oled(render_usb_ports(3), 100, 245, 560)
    if k >= 2:
        c.text(100, 600, "After: mixer moved to bus 1", 30, TEAL, bold=True)
        c.oled(render_usb_ports(1), 100, 645, 560)
    tick_bullets(c, 760, 215, [
        ("Bus 1  FS 388/1099", "Full-speed bytes per USB frame in use, against the budget of that controller."),
        ("p2 Mixer 12M", "The port, the device and its speed. 480M and 5G devices cost nothing."),
        ("! after a bus", "That bus is at or over its budget."),
        ("! after a port", "That device was refused: not enough bandwidth."),
    ][:2 if k == 1 else 4], 34, 1060, TEAL, 22)
    if k >= 2:
        c.text(760, 780, "Press a device for the reason, bus, port and its own load.", 30, INK, bold=True)
        c.text(760, 830, "Menu: Status > USB ports", 30, TEAL, bold=True)


def s_usbtips(c, k):
    c.text(100, 190, "Two USB controllers, two budgets", 36, INK, bold=True)
    x0, wd = 100, 840
    c.text(x0, 250, "Crowded", 32, RED, bold=True)
    bus_row(c, x0, 300, wd, "1", 0, 0, 1099, "Guitar processor 480M: free", False)
    bus_row(c, x0, 490, wd, "3", 1099, 1291, 1099, "Tracker 903 B + mixer 196 B; mixer playback refused", True)
    if k >= 2:
        x1 = 980
        c.text(x1, 250, "Spread out", 32, TEAL, bold=True)
        bus_row(c, x1, 300, wd, "1", 388, 388, 1099, "Guitar processor 480M: free; mixer 388 B")
        bus_row(c, x1, 490, wd, "3", 903, 903, 1099, "Tracker 903 B")
    if k >= 3:
        tick_bullets(c, 100, 720, [
            ("Spread full-speed devices", "Move one to a USB port of the other controller."),
            ("High-speed costs nothing", "Most modern interfaces are high-speed."),
        ], 32, 820, TEAL, 10)
        tick_bullets(c, 980, 720, [
            ("rpi-audiod checks first", "It sizes each full-speed device before opening it and says why one waits."),
            ("Serial-less devices", "Identified by port; one unique device moved to another port keeps its routes."),
        ], 32, 840, BLUE, 10)
        c.text(100, 992, "Budget measured on a Pi 4 (1099 B/frame); the Pi 5 value is not measured yet.", 22, MUTED)


def s_midi(c, k):
    c.text(100, 200, "Host side", 28, MUTED)
    c.text(1820, 200, "Pi side", 28, MUTED, anchor="ra")
    lanes = [("Cable 1", "control port > rpi-audiod", AMBER), ("Cable 2", "Guitar processor MIDI", TEAL), ("Cable 3", "Synth / tracker MIDI", PURPLE), ("Cable 4", "MIDI keyboard", BLUE)]
    for i, (t, sub, col) in enumerate(lanes):
        y = 245 + i * 108
        c.box(1010, y, 1820, y + 90, bar=col)
        c.text(1048, y + 45, t, 30, INK, bold=True, anchor="lm")
        c.text(1200, y + 45, sub, 28, MUTED, anchor="lm")
        c.arrow([(700, y + 45), (1000, y + 45)], col, w=5, both=True)
    c.box(100, 245, 600, 645, bar=BLUE)
    c.text(146, 270, "Host", 40, INK, bold=True)
    c.para(146, 335, "Any host with USB MIDI. On Linux: tools/midictl.py status", 28, MUTED, 420)
    if k >= 2:
        for i, (t, b, col, x) in enumerate((("SysEx text", "ping, status, mute, volume, name, preset, route", TEAL, 100),
                                            ("CC messages", "ch 16 and 15: level CC 32+N, mute CC 64+N", BLUE, 700),
                                            ("Program Change", "0 to 7 on ch 16 loads presets 1 to 8", PURPLE, 1300))):
            c.card(x, 700, x + 520, 920, t, b, col, 34, 28)
    if k >= 3:
        c.text(100, 960, "Devices can also be joined to each other with no host: midiroute joins their MIDI ports in the kernel.", 28, MUTED)


def s_scenes(c, k):
    c.text(100, 200, "Names, levels, mutes", 28, TEAL, bold=True)
    c.oled(crop_oled("09-levels-midi.png", 0), 100, 250, 540)
    c.text(690, 200, "Scenes: 8 slots", 28, TEAL, bold=True)
    c.oled(crop_oled("10-presets.png", 0), 690, 250, 540)
    c.text(1280, 200, "Confirm before saving", 28, TEAL, bold=True)
    c.oled(crop_oled("10-presets.png", 1), 1280, 250, 540)
    c.para(100, 560, "A scene stores routing, channel assignments, MIDI cables, mutes, levels, output switches and names.", 32, INK, 1700, bold=True)
    if k >= 2:
        term(c, 100, 680, 1000, [("rpi-audiod name IDENTITY Guitar", "#8fe0c8"), ("rpi-audiod volume IDENTITY out 80", "#8fe0c8"),
                                 ("rpi-audiod mute IDENTITY in on", "#8fe0c8"), ("rpi-audiod preset save 1 Live", "#f4d58d")], 30)
        c.para(1160, 690, "The same actions work from the OLED, the command line, or the host over MIDI (Program Change 0 to 7 loads a scene).", 30, MUTED, 650)


def s_end(c, k):
    c.box(0, 0, 36, H, fill=TEAL, outline=TEAL, r=0)
    c.text(140, 150, "Where to read more", 80, WHITE, bold=True)
    docs = [("README.md", "overview, install, hardware, USB budget"), ("docs/MANUAL.md", "illustrated user guide and build guide"),
            ("docs/MIDI.md", "control protocol: SysEx, CC, Program Change"), ("docs/DISPLAY.md", "the OLED and encoder, screen by screen"),
            ("docs/hosts/", "notes for specific hosts")]
    for i, (a, b) in enumerate(docs):
        y = 310 + i * 90
        c.text(140, y, a, 40, "#7fd1c7", bold=True, mono=True)
        c.text(640, y + 3, b, 36, "#dbe8f2")
    c.text(140, 810, "Something wrong? Run:  rpi-audiod doctor", 38, "#f4d58d")
    c.text(140, 900, REPO_URL, 44, WHITE, bold=True)
    c.text(140, 965, "Open source, GPL-3.0-or-later", 32, "#8fb0c8")


# (kicker, title, step durations in seconds, drawing function, dark background)
SLIDES = [
    (None, None, [3.2, 4.8], s_title, True),
    ("What it is", "One USB interface, many devices", [3.0, 3.0, 3.0, 3.4], s_what, False),
    ("Signal flow", "Host, Pi, devices", [4.0, 3.5, 3.5], s_flow, False),
    ("Hardware", "What you need", [4.5, 5.0], s_hardware, False),
    ("Cabling", "Power, data and devices", [3.5, 3.5, 4.5], s_cables, False),
    ("Install", "Two commands on the Pi", [3.8, 3.8, 5.0], s_install, False),
    ("Connect a host", "Plug in, check, select", [3.6, 3.6, 4.6], s_connect, False),
    ("Channels and slots", "Every device gets its own block", [4.4, 4.4, 4.2], s_slots, False),
    ("Audio modes", "Pick how the Pi routes audio", [3.5, 3.5, 4.5], s_modes, False),
    ("Hub routes", "Explicit routes, source to destination", [4.5, 6.0], s_hub, False),
    ("The OLED menu", "Turn, push, back", [3.0, 4.0, 4.5], s_menu, False),
    ("Status > USB ports", "See which bus each device is on", [5.0, 6.5], s_usbports, False),
    ("USB tips", "Spread full-speed devices across controllers", [4.0, 4.0, 6.0], s_usbtips, False),
    ("MIDI control", "Control the Pi from the host", [3.8, 4.4, 3.8], s_midi, False),
    ("Scenes and levels", "Name it, balance it, save it", [4.5, 5.5], s_scenes, False),
    (None, None, [7.0], s_end, True),
]


def render_stages(outdir):
    """Draw every reveal step of every slide to PNG; returns [(path, seconds, fade_after)]."""
    outdir.mkdir(parents=True, exist_ok=True)
    clips = []
    n = len(SLIDES)
    for i, (kicker, title, durs, fn, dark) in enumerate(SLIDES):
        for k, dur in enumerate(durs, 1):
            c = Cv(NIGHT if dark else PAPER)
            if not dark:
                c.text(100, 52, kicker.upper(), 28, TEAL, bold=True)
                c.text(100, 88, title, 60, INK, bold=True)
                c.text(100, 1034, f"rpi5-audioface   ·   {REPO_URL}", 24, MUTED)
                c.text(1820, 1034, f"{i + 1} / {n}", 24, MUTED, anchor="ra")
                c.box(0, 1074, W * (i + 1) / n, 1080, fill=TEAL, outline=TEAL, r=0)
            fn(c, k)
            path = outdir / f"slide{i + 1:02d}-{k}.png"
            c.done().save(path)
            last_step = k == len(durs)
            fade = 0.0 if (i == n - 1 and last_step) else (SLIDE_FADE if last_step else STAGE_FADE)
            clips.append((path, dur * SPEED, fade))
    return clips


def encode(clips, music_wav, out_mp4):
    """Chain the stills with xfade crossfades, then mux the AAC music bed."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for path, dur, fade in clips:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur + fade:.3f}", "-i", str(path)]
    cmd += ["-i", str(music_wav)]
    parts = [f"[{i}:v]format=yuv420p,setsar=1[v{i}]" for i in range(len(clips))]
    label, elapsed = "v0", 0.0
    for i in range(1, len(clips)):
        elapsed += clips[i - 1][1]
        fade = clips[i - 1][2]
        parts.append(f"[{label}][v{i}]xfade=transition=fade:duration={fade:.3f}:offset={elapsed:.3f}[x{i}]")
        label = f"x{i}"
    total = elapsed + clips[-1][1]
    parts.append(f"[{label}]fade=t=in:st=0:d=0.8,fade=t=out:st={total - 1.6:.3f}:d=1.6[vout]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", f"{len(clips)}:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out_mp4)]
    subprocess.run(cmd, check=True)
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "out/video"), help="output directory (git-ignored by default)")
    ap.add_argument("--frames", action="store_true", help="only render the slide PNGs")
    args = ap.parse_args()
    out = Path(args.out)
    clips = render_stages(out / "build")
    print(f"{len(clips)} stills in {out / 'build'}")
    if args.frames:
        return
    import music
    total = sum(d for _, d, _ in clips)
    wav = out / "build" / "music.wav"
    music.write_wav(wav, total)
    mp4 = out / "rpi5-audioface-overview.mp4"
    encode(clips, wav, mp4)
    print(f"wrote {mp4} ({total:.1f} s)")


if __name__ == "__main__":
    main()
