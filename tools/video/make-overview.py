#!/usr/bin/env python3
"""Render the rpi5-audioface overview film: animated scenes drawn frame by frame with Pillow, a procedural
music bed (music.py), and ffmpeg.

    python3 tools/video/make-overview.py                 # -> out/video/rpi5-audioface-overview.mp4 (1080p)
    python3 tools/video/make-overview.py --small         # also the 720p two-pass file under 9 MB
    python3 tools/video/make-overview.py --still 12.5    # one PNG of the film at 12.5 s (for checking layout)

Needs Python 3 with Pillow and numpy, DejaVu fonts, and ffmpeg. No network, no Pi, no downloaded assets: every
illustration is drawn in draw.py, the OLED screens come from docs/manual/img/ or from the project's own OLED
renderer (bridge/rpi-audio-ui), and the screenshots are the ones in docs/img/.
"""
import argparse
import math
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path as FsPath

from PIL import Image

HERE = FsPath(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "bridge/rpi-audio-ui"))

from draw import *  # noqa: E402,F401,F403  (the drawing kit: Cv, easing, cables, illustrations)

FPS, FADE = 25, 0.5
OUT = ROOT / "out/video"
MANUAL, IMG = ROOT / "docs/manual/img", ROOT / "docs/img"
IN_D, OUT_D = "#0b7f73", "#2563eb"
_IMGS = {}


def load(path):
    if path not in _IMGS:
        _IMGS[path] = Image.open(path).convert("RGB")
    return _IMGS[path]


def crop_oled(name, side):
    """One of the two 640x320 screens in a manual figure (pair layout: 1440x450)."""
    x = 42 if side == 0 else 758
    return load(MANUAL / name).crop((x, 125, x + 640, 445))


def render_usb_ports(mixer_bus):
    """The Status > USB ports screen, drawn by the project's own OLED renderer from a sample status."""
    import render
    import sh1106
    import ui
    mixer = {"identity": f"usb-{mixer_bus}-2-0000:0001", "card": "CODEC", "name": "Mixer",
             "usb": {"bus": mixer_bus, "port": f"{mixer_bus}-2", "speed": 12, "by_port": True},
             "in": {"channels": 2, "fs_load": 196}, "out": {"channels": 2, "fs_load": 192}}
    tracker = {"identity": "usb-3-1-0000:0003", "card": "Tracker", "name": "Tracker",
               "usb": {"bus": 3, "port": "3-1", "speed": 12}, "in": {"channels": 8, "fs_load": 720},
               "out": {"channels": 2, "fs_load": 183}}
    if mixer_bus == 3:   # the mixer behind the same hub as the tracker: they share one root port's budget
        mixer["usb"]["port"], tracker["usb"]["port"] = "3-1.2", "3-1.1"
        mixer["out"]["blocked"] = "USB full-speed budget: needs 192 B, 0 B of 1099 B free on port 3-1"
        ports = [{"port": "1-1", "bus": 1, "fs_load": 0, "fs_demand": 0, "fs_budget": 1099},
                 {"port": "3-1", "bus": 3, "fs_load": 1099, "fs_demand": 1291, "fs_budget": 1099}]
    else:
        ports = [{"port": "1-1", "bus": 1, "fs_load": 0, "fs_demand": 0, "fs_budget": 1099},
                 {"port": "1-2", "bus": 1, "fs_load": 388, "fs_demand": 388, "fs_budget": 1099},
                 {"port": "3-1", "bus": 3, "fs_load": 903, "fs_demand": 903, "fs_budget": 1099}]
    status = {"usb_ports": ports, "devices": [
        {"identity": "usb-1-1-0000:0002", "card": "GP150", "name": "Guitar Rig",
         "usb": {"bus": 1, "port": "1-1", "speed": 480}},
        tracker, mixer]}
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


# ------------------------------------------------------------------------------------------------ scene helpers

def head(c, t, title, color=INK, size=80, y=58):
    p = e_out(seg(t, 0.1, 0.6))
    with c.at(0, -26 * (1 - p), 1, p):
        c.text(960, y, title, size, color, True, anchor="ma")


def caps(c, t, items, size=50, y=948, color=MUTED, bold=True):
    """Bottom captions: (t_in, t_out or None, text). Each fades in, and out when it has an end."""
    for t0, t1, s in items:
        a = e_out(seg(t, t0, t0 + 0.45))
        if t1 is not None:
            a = min(a, 1 - e_io(seg(t, t1 - 0.3, t1)))
        if a > 0.01:
            with c.at(0, 14 * (1 - a), 1, a):
                c.text(960, y, s, size, color, bold, anchor="ma")


def notes(c, t, n=7, region=(120, 900), base=900, top=140, colors=(IN_C, OUT_C, MIDI_C, CTRL_C), size=64):
    for i in range(n):
        ph = (t * 0.11 + i / n) % 1
        x = region[0] + (region[1] - region[0]) * ((i * 0.37) % 1) + 28 * math.sin(t * 1.3 + i * 2)
        y = base - (base - top) * ph
        a = min(1.0, ph * 6, (1 - ph) * 4) * 0.8
        c.text(x, y, "♪♫"[i % 2], size, mix(colors[i % 4], c.bg, a), True, anchor="mm")


def label(c, x, y, s, t, t0, size=40, color=INK):
    fade_text(c, x, y, s, t, t0, size, color, True)


def tag(c, x, y, s, t, t0, fill, size=40):
    p = seg(t, t0, t0 + 0.45)
    if p > 0:
        with c.at(x, y, max(0.02, e_back(p)), clamp(p * 3)):
            c.pill(0, 0, s, size, fill=fill)


def usb_cable(c, pts, t, t0, dur=0.9, r=40, **kw):
    path = Path(pts, r)
    p = e_io(seg(t, t0, t0 + dur))
    cable(c, path, p, **kw)
    return path, p


def draw_term_lines(c, x, y, lines, t, t0, size=44, step=1.1):
    """Typed terminal lines: (text, colour). A new line starts every `step` seconds."""
    for i, (s, col) in enumerate(lines):
        ts = t0 + i * step
        if t < ts:
            break
        cursor = "▌" if int(t * 2.5) % 2 == 0 and (i == len(lines) - 1 or t < ts + 0.8) and col == "#7dd3fc" else ""
        c.text(x, y + i * size * 1.55, typed(s, t, ts, 26) + cursor, size, col, True, mono=True)


# ------------------------------------------------------------------------------------------------ scenes

def s_title(c, t):
    notes(c, t, 9, (120, 1800), 1000, 100)
    p = e_back(seg(t, 0.1, 0.8))
    with c.at(960, 150 + 0, p, clamp(p * 3)):
        c.text(0, 0, "rpi5-audioface", 128, INK, True, anchor="ma")
    show(c, pi5, 960, 600, t, 0.6, s=1.45, bob=8, dur=0.8)
    fade_text(c, 960, 860, "Your Raspberry Pi becomes a USB sound card", t, 1.6, 54, MUTED)
    fade_text(c, 960, 938, "and a hub for all your audio and MIDI gear", t, 2.4, 54, MUTED)


def s_one(c, t):
    head(c, t, "One cable to your host")
    show(c, laptop, 290, 520, t, 0.3, s=1.05, bob=0)
    show(c, pi5, 930, 560, t, 0.8, s=1.0)
    devs = [(mixer, 1590, 330, 0.75), (synth, 1590, 590, 0.7), (pedal, 1590, 840, 0.5)]
    for i, (fn, x, y, sc) in enumerate(devs):
        show(c, fn, x, y, t, 1.4 + 0.3 * i, s=sc)
    host, _ = usb_cable(c, [(500, 626), (724, 626)], t, 1.2, 0.6)
    ports = (-34, -12, 22, 44)
    chains = []
    for i, (fn, x, y, sc) in enumerate(devs):
        left = {mixer: -110, synth: -150, pedal: -80}[fn] * sc + x
        px, py = 930 + 206, 560 + ports[i]
        pa, _ = usb_cable(c, [(px, py), (1250 + i * 36, py), (1250 + i * 36, y), (left, y)], t, 2.0 + 0.3 * i, 0.9, r=34, w=10)
        chains.append(pa)
    ta = seg(t, 3.4, 4.2)
    pulses(c, host, t, IN_C, ta, rev=True, off=-13)
    pulses(c, host, t, OUT_C, ta, off=13)
    for pa in chains:
        pulses(c, pa, t, IN_C, ta, rev=True, off=-13, gap=170)
        pulses(c, pa, t, OUT_C, ta, off=13, gap=170)
    caps(c, t, [(0.9, 3.8, "Plug your gear into the Pi"), (4.2, None, "Your host sees one USB audio interface")])


def s_inout(c, t):
    head(c, t, "Sound goes both ways")
    show(c, laptop, 300, 560, t, 0.3, s=1.05)
    show(c, pi5, 880, 560, t, 0.7, s=0.85)
    show(c, pedal, 1560, 370, t, 1.1, s=0.62)
    show(c, speaker, 1560, 770, t, 1.3, s=1.0, play=seg(t, 3.5, 4.3))
    host, _ = usb_cable(c, [(500, 622), (705, 622)], t, 1.0, 0.5)
    a, _ = usb_cable(c, [(1050, 530), (1280, 530), (1280, 370), (1480, 370)], t, 1.6, 0.8, w=10)
    b, _ = usb_cable(c, [(1050, 600), (1350, 600), (1350, 780), (1500, 780)], t, 1.8, 0.8, w=10)
    ta = seg(t, 2.8, 3.6)
    pulses(c, host, t, IN_C, ta, rev=True, off=-14, speed=330)
    pulses(c, a, t, IN_C, ta, rev=True, speed=330)
    pulses(c, host, t, OUT_C, ta, off=14, speed=330)
    pulses(c, b, t, OUT_C, ta, speed=330)
    tag(c, 1180, 250, "IN  to the host", t, 3.0, IN_D, 44)
    tag(c, 1180, 880, "OUT  from the host", t, 3.6, OUT_D, 44)
    caps(c, t, [(0.9, 4.8, "Your gear plays into the host..."), (5.2, None, "...and the host plays out to your gear")])


def sdcard(c, t=0.0):
    c.poly([(-34, -46), (20, -46), (38, -28), (38, 46), (-34, 46)], "#2b3a55")
    c.rect(-22, -52, 26, -26, "#2b3a55")
    for i in range(4):
        c.rect(-26 + i * 14, -40, -18 + i * 14, -22, "#d4a93c")
    c.text(2, 18, "SD", 28, "#9fb3d1", True, anchor="mm")


def s_parts(c, t):
    head(c, t, "What you need")
    items = [("Pi 5 + SD card", 0), ("USB-C splitter", 1), ("5 V supply", 2), ("USB gear", 3), ("OLED + knob", 4)]
    for i, (name, k) in enumerate(items):
        x0 = 70 + i * 368
        p = e_back(seg(t, 0.4 + 0.5 * i, 1.0 + 0.5 * i))
        if p <= 0:
            continue
        with c.at(x0 + 170, 540 + 40 * (1 - clamp(p)), 1, clamp(p * 3)):
            c.card(-170, -290, 170, 290)
            if k == 0:
                with c.at(0, -90, 0.7):
                    pi5(c, t)
                with c.at(0, 80, 1.6):
                    sdcard(c)
            elif k == 1:
                with c.at(0, -40, 1.0):
                    splitter(c, t)
            elif k == 2:
                with c.at(-10, -40, 1.7):
                    psu(c, t)
            elif k == 3:
                with c.at(-20, -140, 0.72):
                    mixer(c, t)
                with c.at(30, 70, 0.8):
                    synth(c, t)
            else:
                with c.at(0, -130, 0.42):
                    oled_unit(c, t, crop_oled("04-overview.png", 1))
                with c.at(0, 50, 1.0):
                    encoder(c, t, t * 2)
            c.text(0, 218, name, 40, INK, True, anchor="mm")
            if k == 4:
                c.text(0, 262, "optional", 36, MUTED, False, anchor="mm")
    caps(c, t, [(5.0, None, "No soldering. Nothing to install on the host.")])


def s_install(c, t):
    head(c, t, "Install in two commands")
    p = e_out(seg(t, 0.3, 0.9))
    with c.at(0, 30 * (1 - p), 1, p):
        terminal(c, 220, 230, 1700, 800)
    lines = [("$ git clone <repo>", "#7dd3fc"), ("$ sudo ./install.sh", "#7dd3fc"),
             ("✓ gadget  ✓ audio daemon  ✓ ready", "#86efac"), ("$ rpiaudiod doctor".replace("rpiaudiod", "rpi-audiod"), "#7dd3fc"),
             ("All checks passed", "#86efac")]
    draw_term_lines(c, 270, 300, lines, t, 1.0, size=46, step=1.35)
    caps(c, t, [(1.0, 5.5, "Copy it. Install it."), (6.0, None, "Then ask the doctor if all is well")])


def s_connect(c, t):
    head(c, t, "Plug in. Power on.")
    show(c, laptop, 250, 320, t, 0.3, s=0.75)
    show(c, psu, 250, 830, t, 0.3, s=1.1)
    show(c, splitter, 700, 570, t, 0.7, s=0.8)
    show(c, pi5, 1190, 570, t, 0.9, s=0.8)
    show(c, mixer, 1700, 330, t, 5.4, s=0.6)
    show(c, synth, 1700, 800, t, 5.7, s=0.6)
    fade_text(c, 700, 660, "USB-C splitter", t, 1.0, 40, MUTED, False)
    tag(c, 250, 440, "1  Host", t, 1.4, IN_D, 44)
    host, _ = usb_cable(c, [(378, 330), (480, 330), (480, 546), (586, 546)], t, 1.8, 0.9, r=36)
    data, _ = usb_cable(c, [(814, 570), (910, 570), (910, 618), (1025, 618)], t, 3.0, 0.8, r=24)
    ta = seg(t, 3.4, 4.0)
    pulses(c, host, t, IN_C, ta, rev=True, off=-12, gap=150)
    pulses(c, host, t, OUT_C, ta, off=12, gap=150)
    tag(c, 250, 940, "2  Power", t, 3.6, "#b7791f", 44)
    pw, _ = usb_cable(c, [(346, 830), (480, 830), (480, 594), (586, 594)], t, 3.8, 0.9, r=36, color="#f3c77a", edge=AMBER)
    tp = seg(t, 4.6, 5.2)
    pulses(c, pw, t, AMBER, tp, speed=240, gap=120)
    pulses(c, data, t, AMBER, tp, speed=240, gap=120, off=0)
    pulses(c, data, t, IN_C, ta, rev=True, off=-12, gap=150)
    pulses(c, data, t, OUT_C, ta, off=12, gap=150)
    tag(c, 1700, 560, "3  Your gear", t, 5.6, PURPLE, 44)
    for i, y in enumerate((330, 800)):
        ys = 540 if i == 0 else 600
        p_, _ = usb_cable(c, [(1396, ys), (1500 + 30 * i, ys), (1500 + 30 * i, y), (1600 if i == 0 else 1590, y)], t, 6.0 + 0.3 * i, 0.9, r=30, w=10)
        tg = seg(t, 7.0, 7.6)
        pulses(c, p_, t, IN_C, tg, rev=True, off=-10, gap=120)
        pulses(c, p_, t, OUT_C, tg, off=10, gap=120)
    caps(c, t, [(7.4, None, "Any USB audio or MIDI device works")], y=985)


def s_slots(c, t):
    head(c, t, "26 slots each way")
    blocks = [("Mixer", BLUE), ("Tracker", PURPLE), ("Pedal", AMBER)]
    sizes = {0: (2, 8, 2), 1: (2, 2, 2)}
    x0, wslot, gap = 90, 62, 5.6
    for row, (name, y) in enumerate((("IN", 400), ("OUT", 760))):
        rp = e_out(seg(t, 0.3 + 0.25 * row, 0.9 + 0.25 * row))
        with c.at(0, 0, 1, rp):
            c.pill(190, y - 120, name, 46, IN_D if row == 0 else OUT_D, padx=30)
            c.text(300, y - 143, "device to host" if row == 0 else "host to device", 44, MUTED, True)
        for i in range(26):
            c.rect(x0 + i * (wslot + gap), y - 55, x0 + i * (wslot + gap) + wslot, y + 55, "#e5ecf4", LINE, r=12, w=2)
        pos = 0
        for k, (dn, col) in enumerate(blocks):
            n = sizes[row][k]
            ts = 1.6 + k * 1.4 + row * 4.2
            p = e_back(seg(t, ts, ts + 0.7))
            if p > 0:
                xa = x0 + pos * (wslot + gap)
                xb = x0 + (pos + n) * (wslot + gap) - gap
                with c.at((xa + xb) / 2, y, 1, clamp(p * 3)):
                    c.rect(-(xb - xa) / 2 * min(p, 1.05), -55, (xb - xa) / 2 * min(p, 1.05), 55, col, r=12)
                    if p >= 1:
                        c.text(0, 0, str(n), 50, WHITE, True, anchor="mm")
                if row == 0:
                    label(c, (xa + xb) / 2, y + 66, dn, t, ts + 0.3, 40, col)
            pos += n
    caps(c, t, [(1.2, 7.4, "Every device gets its own slots"), (8.0, None, "Plug in more gear, more slots fill up")], y=930)


def s_modes(c, t):
    head(c, t, "Pick a mode")
    cards = [("Host clock", "The host sets the pace", laptop, 0.75), ("Hub", "The Pi mixes it all", pi5, 0.72),
             ("Standalone DAC", "A plain USB sound card", speaker, 1.5)]
    for i, (title, sub, fn, sc) in enumerate(cards):
        x = 335 + i * 625
        p = e_back(seg(t, 0.5 + 0.8 * i, 1.2 + 0.8 * i))
        if p <= 0:
            continue
        hi = seg(t, 4.0 + 1.6 * i, 4.4 + 1.6 * i) * (1 - seg(t, 5.4 + 1.6 * i, 5.8 + 1.6 * i)) if i < 2 else seg(t, 7.2, 7.6)
        with c.at(x, 520 + 40 * (1 - clamp(p)), 1 + 0.03 * hi, clamp(p * 3)):
            c.card(-285, -250, 285, 290, edge=mix(TEAL, LINE, hi) if hi > 0 else LINE)
            with c.at(0, -70, sc):
                fn(c, t)
            if i == 0:
                c.circle(160, -170, 36, WHITE, MUTED, w=5)
                c.line([(160, -170), (160, -194)], MUTED, 5)
                c.line([(160, -170), (180, -162)], MUTED, 5)
            c.text(0, 130, title, 54, INK, True, anchor="mm")
            c.text(0, 205, sub, 40, MUTED, False, anchor="mm")
    caps(c, t, [(8.4, None, "Change it any time from the OLED")], y=930)


def s_oled(c, t):
    head(c, t, "Turn. Press. Done.")
    imgs = [crop_oled("04-overview.png", 1), crop_oled("05-connections.png", 1), crop_oled("08-routes.png", 0)]
    k = min(int(clamp(t - 1.0, 0, 8) // 2.6), 2)
    zoom = 1.0 + 0.05 * seg(t, 1.0, 9.0)
    p = e_back(seg(t, 0.3, 1.0))
    with c.at(600, 520, 1.15 * zoom * max(0.1, p), clamp(p * 3)):
        c.rect(-350, -200, 350, 200, "#1b2a3a", "#0d1620", r=26, w=4)
        c.rect(-324, -164, 324, 164, "#02090d")
        fr = (t - 1.0) % 2.6
        for j in (k, k - 1):
            if j < 0:
                continue
            a = e_io(seg(fr, 0, 0.3)) if j == k else 1 - e_io(seg(fr, 0, 0.3))
            if k == 0:
                a = 1.0
            with c.at(0, 0, 1, a):
                c.pic(imgs[j], -320, -160, 640)
    p2 = show(c, encoder, 1530, 440, t, 1.0, s=1.5, ang=t * 2.2)
    if p2 >= 1:
        a = 0.5 + 0.5 * math.sin(t * 2.2)
        c.text(1530, 300, "↻", 90, mix(TEAL, c.bg, 0.4 + 0.5 * a), True, anchor="mm")
    tag(c, 1530, 670, "turn to move", t, 2.0, IN_D, 44)
    tag(c, 1530, 770, "press to choose", t, 3.0, PURPLE, 44)
    for tt in (3.4, 5.2, 7.0):
        ring(c, 1530, 440, 80, t, tt, PURPLE, 0.8)
    caps(c, t, [(1.0, None, "No keyboard or screen needed")])


def lane(c, y, name, t, t0):
    p = e_out(seg(t, t0, t0 + 0.6))
    with c.at(0, 0, 1, p):
        c.rect(140, y - 100, 1800, y + 100, "#c9d4e1", r=26)
        for x in range(180, 1780, 90):
            c.rect(x, y - 3, x + 46, y + 3, "#f4f7fb", r=3)
        c.text(140, y - 150, name, 44, INK, True)


def car(c, x, y, w, name, col, h=140):
    with c.at(x, y):
        c.rect(0, -h / 2, w, h / 2, col, r=30)
        c.circle(54, h / 2, 22, "#1b2733")
        c.circle(w - 54, h / 2, 22, "#1b2733")
        c.text(w / 2, -4, name, 48, WHITE, True, anchor="mm")


def s_lanes(c, t):
    head(c, t, "USB has two lanes")
    fade_text(c, 960, 160, "The Pi 5 has two USB controllers", t, 0.5, 42, MUTED, False)
    lane(c, 400, "Lane A", t, 0.3)
    lane(c, 740, "Lane B", t, 0.5)
    # tracker (big) parks at the right end of lane B
    ptk = e_out(seg(t, 1.2, 2.6))
    car(c, lerp(-1250, 640, ptk), 740, 1150, "Tracker", PURPLE)
    # mixer: too long for what is left of lane B, so it overhangs; then it takes lane A
    if t >= 3.4:
        if t < 7.0:
            x, y = lerp(-620, 80, e_out(seg(t, 3.4, 4.6))), 740
            bad = t > 4.6
        else:
            pq = e_io(seg(t, 7.0, 8.2))
            x, y = lerp(80, 120, pq) + 1000 * e_io(seg(t, 8.0, 9.4)), lerp(740, 400, pq)
            bad = False
        car(c, x, y, 560, "Mixer", RED if bad else BLUE)
    if 4.6 < t < 7.2:
        with c.at(380, 640, max(0.02, e_back(seg(t, 4.6, 5.1)))):
            c.pill(0, 0, "Full!", 60, fill=RED)
    if t > 9.4:
        with c.at(700, 400, max(0.02, e_back(seg(t, 9.4, 10.0)))):
            c.pill(0, 0, "Fits ✓", 60, fill=GREEN)
    caps(c, t, [(0.9, 3.4, "Full-speed devices share a lane"), (5.0, 7.2, "This one is too big for lane B"),
                (7.6, None, "Plug it into the other lane. Done.")], y=900)


def s_check(c, t):
    head(c, t, "The OLED shows each lane")
    a, b = render_usb_ports(3), render_usb_ports(1)
    p = e_back(seg(t, 0.3, 1.0))
    zoom = 1.0 + 0.06 * seg(t, 1.0, 7.0)
    sw = e_io(seg(t, 3.4, 4.0))
    with c.at(960, 520, 1.45 * zoom * max(0.1, p), clamp(p * 3)):
        c.rect(-350, -200, 350, 200, "#1b2a3a", "#0d1620", r=26, w=4)
        c.rect(-324, -164, 324, 164, "#02090d")
        c.pic(a, -320, -160, 640)
        with c.at(0, 0, 1, sw):
            c.pic(b, -320, -160, 640)
    if t < 3.7:
        tag(c, 960, 905, "Lane B is full", t, 1.0, RED, 48)
    else:
        tag(c, 960, 905, "Moved to lane A: all fits", t, 4.0, GREEN, 48)


def s_midi(c, t):
    head(c, t, "MIDI comes along")
    show(c, laptop, 300, 520, t, 0.3, s=1.0)
    show(c, pi5, 960, 560, t, 0.7, s=0.95)
    show(c, midi_keys, 1560, 340, t, 1.2, s=0.8)
    show(c, synth, 1560, 700, t, 1.5, s=0.75)
    cols = [CTRL_C, MIDI_C, MIDI_C, MIDI_C]
    pa = []
    for i in range(4):
        y = 510 + i * 34
        pth, _ = usb_cable(c, [(500, y), (764, y)], t, 1.6 + 0.15 * i, 0.6, r=0, color=mix(cols[i], PAPER, 0.8), edge=cols[i], w=8)
        pa.append(pth)
        with c.at(0, 0, 1, seg(t, 2.2, 2.7)):
            c.text(540, y + 2, str(i + 1), 28, cols[i], True, anchor="mm")
    ta = seg(t, 3.0, 3.6)
    pulses(c, pa[0], t, CTRL_C, ta, r=9, gap=120, rev=True)
    pulses(c, pa[0], t, CTRL_C, ta, r=9, gap=120, off=0)
    pulses(c, pa[1], t, MIDI_C, ta, r=9, gap=120, rev=True)
    pulses(c, pa[2], t, MIDI_C, ta, r=9, gap=120)
    a, _ = usb_cable(c, [(1130, 520), (1300, 520), (1300, 340), (1415, 340)], t, 2.0, 0.8, r=34)
    b, _ = usb_cable(c, [(1130, 580), (1340, 580), (1340, 700), (1440, 700)], t, 2.2, 0.8, r=34)
    pulses(c, a, t, MIDI_C, ta, rev=True, gap=150)
    pulses(c, b, t, MIDI_C, ta, gap=150)
    with c.at(0, 0, 1, seg(t, 3.4, 4.0)):
        c.pill(520, 740, "1  control", 40, "#a8641a", padx=22)
        c.pill(520, 820, "2-4  notes", 40, PURPLE, padx=22)
    caps(c, t, [(1.0, 4.0, "4 MIDI cables inside the same USB cable"), (4.6, None, "Cable 1 is for controlling the Pi")])


def s_scenes(c, t):
    head(c, t, "Save a setup. Recall it.")
    cur = int(clamp(t - 1.8, 0, 99) // 1.1) % 8 if t > 1.8 else -1
    names = ["Live", "Studio", "", "", "", "", "", ""]
    for i in range(8):
        col, row = i % 4, i // 4
        x, y = 90 + col * 250, 330 + row * 250
        p = e_back(seg(t, 0.4 + 0.12 * i, 0.9 + 0.12 * i))
        if p <= 0:
            continue
        hi = 1.0 if cur == i else 0.0
        with c.at(x + 110, y + 100, max(0.02, p) * (1 + 0.07 * hi), clamp(p * 3)):
            c.card(-110, -100, 110, 100, fill=TEAL if hi else WHITE, edge=TEAL if hi else LINE, r=24)
            c.text(0, -14 if names[i] else 0, str(i + 1), 84, WHITE if hi else TEAL, True, anchor="mm")
            if names[i]:
                c.text(0, 62, names[i], 40, WHITE if hi else INK, True, anchor="mm")
    p = e_back(seg(t, 1.2, 1.9))
    with c.at(1450, 500, 1.0, clamp(p * 3)):
        c.pic(crop_oled("10-presets.png", 0), -320, -160, 640, border="#0d1620", r=10, bw=8)
        c.text(0, 200, "on the OLED", 42, MUTED, True, anchor="ma")
        if t > 6.0:
            c.text(0, 262, "or from your host", 42, MUTED, True, anchor="ma")
    caps(c, t, [(1.4, None, "8 setups, one tap each")])


def s_doctor(c, t):
    head(c, t, "Something odd? Ask the doctor")
    p = e_out(seg(t, 0.3, 0.9))
    with c.at(0, 30 * (1 - p), 1, p):
        terminal(c, 220, 240, 1700, 800)
    lines = [("$ rpi-audiod doctor", "#7dd3fc"), ("✓ USB gadget is up", "#86efac"), ("✓ host is connected", "#86efac"),
             ("✓ 3 devices running", "#86efac"), ("! USB lane B is full", "#fbbf24")]
    draw_term_lines(c, 270, 310, lines, t, 1.0, size=46, step=1.0)
    caps(c, t, [(1.0, None, "It tells you what is wrong, and why")])


def s_section(c, t):
    notes(c, t, 6, (120, 1800), 1000, 100, size=56)
    fade_text(c, 960, 120, "EXAMPLE HOST", t, 0.2, 52, "#7dd3fc")
    p = e_back(seg(t, 0.3, 1.0))
    with c.at(960, 190, p, clamp(p * 3)):
        c.text(0, 0, "Akai Force", 140, WHITE, True, anchor="ma")
    show(c, force, 960, 640, t, 0.8, s=1.25, bob=6, dur=0.9)
    fade_text(c, 960, 930, "How one real host uses rpi5-audioface", t, 1.8, 54, "#c3d3e6", False)


def s_force_host(c, t):
    head(c, t, "The Force sees a sound card")
    show(c, force, 440, 580, t, 0.3, s=0.85, bob=0)
    show(c, pi5, 1110, 580, t, 0.8, s=0.8)
    show(c, mixer, 1640, 350, t, 1.8, s=0.55)
    show(c, pedal, 1640, 560, t, 2.0, s=0.42)
    show(c, synth, 1640, 800, t, 2.2, s=0.5)
    host, _ = usb_cable(c, [(670, 628), (945, 628)], t, 1.2, 0.7)
    tag(c, 810, 520, "USB", t, 1.8, "#374357", 44)
    ta = seg(t, 3.0, 3.8)
    pulses(c, host, t, IN_C, ta, rev=True, off=-13, gap=140)
    pulses(c, host, t, OUT_C, ta, off=13, gap=140)
    for i, y in enumerate((350, 560, 800)):
        pth, _ = usb_cable(c, [(1276, 560 + (-20 + 20 * i)), (1390, 560 + (-20 + 20 * i)), (1390, y), (1500, y)], t, 2.4 + 0.2 * i, 0.7, r=28, w=10)
        pulses(c, pth, t, IN_C, ta, rev=True, off=-12, gap=140)
        pulses(c, pth, t, OUT_C, ta, off=12, gap=140)
    caps(c, t, [(1.0, 5.0, "A 26-in, 26-out USB audio interface"), (5.6, None, "The first host we tested")])


def s_force_panel(c, t):
    head(c, t, "The Panel: control it from MPC")
    shot = load(IMG / "panel-on-force.png")
    regions = [(0, 0, 1280, 800), (300, 90, 1100, 590), (20, 205, 660, 605), (230, 340, 590, 565), (0, 0, 1280, 800)]
    times = [0.0, 2.8, 5.6, 8.4, 11.2]
    k = max(i for i, tt in enumerate(times) if t >= tt - 0.001) if t < times[-1] else len(times) - 1
    if k >= len(times) - 1:
        box = regions[-1]
    else:
        u = e_io(seg(t, times[k] + 0.2, times[k] + 1.2))
        a0, a1 = regions[k], regions[k + 1]
        box = tuple(lerp(x, y, u) for x, y in zip(a0, a1))
        box = tuple(a0 if t < 0 else box)
    p = e_out(seg(t, 0.2, 0.9))
    box = tuple(round(v) for v in box)
    # keep the crop inside the image and 16:10
    with c.at(0, 24 * (1 - p), 1, p):
        c.pic(shot, 80, 240, 1130, src=box, border=LINE, r=10, bw=6)
    items = [(2.8, "Presets", PURPLE), (5.6, "Devices", BLUE), (8.4, "Faders and mutes", TEAL)]
    for ts, s, col in items:
        pr = e_back(seg(t, ts, ts + 0.6))
        if pr > 0:
            with c.at(1250, 330 + items.index((ts, s, col)) * 110, max(0.02, pr), clamp(pr * 3)):
                c.circle(26, 0, 22, col)
                c.text(70, 0, s, 50, INK, True, anchor="lm")
    pn = e_back(seg(t, 10.0, 10.8))
    if pn > 0:
        with c.at(1250, 610, 1, clamp(pn * 3)):
            with c.at(0, 0, max(0.02, pn)):
                c.pic(load(IMG / "panel-name-picker.png"), 0, 0, 480, border=LINE, r=10, bw=5)
    caps(c, t, [(0.8, None, "A plugin that runs on the Force screen")], y=985, size=46)


def s_force_io(c, t):
    head(c, t, "Get the Force's own jacks back")
    on = seg(t, 6.0, 6.6)
    show(c, force, 540, 520, t, 0.3, s=0.95, jacks=None)
    # redraw jacks on top, grey then teal (state changes with time)
    with c.at(540, 520, 0.95):
        for x in FORCE_OUT_X + (FORCE_HP_X,):
            c.circle(x, 170, 13, mix(TEAL, "#3b4350", on), "#07090c", w=2)
        for x in FORCE_IN_X:
            c.circle(x, -170, 13, mix(IN_C, "#3b4350", on), "#07090c", w=2)
    show(c, pi5, 1450, 520, t, 0.8, s=0.8)
    host, _ = usb_cable(c, [(810, 560), (1244, 568)], t, 1.4, 0.8, r=0)
    pulses(c, host, t, OUT_C, seg(t, 2.4, 3.0), off=12, gap=150)
    pulses(c, host, t, IN_C, seg(t, 2.4, 3.0), rev=True, off=-12, gap=150)
    for i, x in enumerate((420, 700)):
        show(c, speaker, x, 860, t, 5.6 + 0.2 * i, s=0.55, play=on)
    if on > 0:
        for i, x in enumerate((FORCE_OUT_X[0], FORCE_OUT_X[2])):
            xx = 540 + x * 0.95
            pth = Path([(xx, 520 + 170 * 0.95 + 14), (xx, 780)], None)
            pulses(c, pth, t, OUT_C, on, speed=200, gap=60, r=7)
    if t < 5.6:
        tag(c, 960, 250, "MPC uses the Pi: Force jacks are off", t, 3.4, "#7a8798", 44)
    else:
        tag(c, 960, 250, "Outputs add-on: jacks are back", t, 6.2, IN_D, 44)
    ring(c, 540, 520 + 170 * 0.95, 80, t, 6.2, TEAL, 1.0)
    caps(c, t, [(0.8, 5.4, "While MPC plays through the Pi, the Force jacks go silent"),
                (6.4, 10.4, "A small add-on brings them back, as well"),
                (11.0, None, "A separate project. Installed on its own.")], size=44, y=968)


def s_force_pick(c, t):
    head(c, t, "Pick what you need")
    cards = [("The Force as host", "needs only rpi5-audioface", force, 0.3, IN_D),
             ("The Panel", "optional MPC plugin", None, 0.34, PURPLE),
             ("Outputs add-on", "optional, installed on its own", None, 0.3, OUT_D)]
    for i, (title, sub, fn, sc, col) in enumerate(cards):
        x = 340 + i * 620
        p = e_back(seg(t, 0.5 + 0.9 * i, 1.2 + 0.9 * i))
        if p <= 0:
            continue
        with c.at(x, 560 + 40 * (1 - clamp(p)), 1, clamp(p * 3)):
            c.card(-280, -250, 280, 290)
            with c.at(0, -90, 1):
                if i == 0:
                    with c.at(0, 0, 0.42):
                        force(c, t)
                elif i == 1:
                    c.pic(load(IMG / "panel-on-force.png"), -190, -110, 380, border=LINE, r=6, bw=3)
                else:
                    with c.at(0, 0, 0.42):
                        force(c, t, jacks=1)
            c.text(0, 90, title, 50, INK, True, anchor="mm")
            c.text(0, 160, sub, 36, MUTED, False, anchor="mm")
            pill = seg(t, 1.6 + 0.9 * i, 2.1 + 0.9 * i)
            if pill > 0:
                with c.at(0, 232, max(0.02, e_back(pill))):
                    c.pill(0, 0, "✓  works alone" if i else "✓  start here", 36, col)
    caps(c, t, [(4.6, None, "None of these depend on each other")], y=925)


def s_end(c, t):
    notes(c, t, 4, (60, 400), 1000, 100, size=56)
    notes(c, t, 4, (1520, 1860), 1000, 100, size=56)
    p = e_back(seg(t, 0.1, 0.8))
    with c.at(960, 170, p, clamp(p * 3)):
        c.text(0, 0, "rpi5-audioface", 120, WHITE, True, anchor="ma")
    show(c, pi5, 960, 560, t, 0.5, s=1.2, bob=6)
    fade_text(c, 960, 800, "github.com/trak3r-os/rpi5-audioface", t, 1.3, 56, "#7dd3fc", True)
    fade_text(c, 960, 890, "Free software · GPL-3.0-or-later", t, 2.0, 46, "#c3d3e6", False)


DARK = {s_section, s_end}
SCENES = [(s_title, 7), (s_one, 11), (s_inout, 9), (s_parts, 9), (s_install, 10), (s_connect, 10), (s_slots, 11),
          (s_modes, 11), (s_oled, 10), (s_lanes, 13), (s_check, 7), (s_midi, 10), (s_scenes, 9), (s_doctor, 7),
          (s_section, 5), (s_force_host, 10), (s_force_panel, 13), (s_force_io, 14), (s_force_pick, 8), (s_end, 7)]
TOTAL = sum(d for _, d in SCENES)
STARTS = [sum(d for _, d in SCENES[:i]) for i in range(len(SCENES))]


def scene_frame(i, t):
    fn = SCENES[i][0]
    c = Cv(NIGHT if fn in DARK else PAPER)
    fn(c, t)
    return c.done()


def frame_at(sec):
    i = max(k for k, s in enumerate(STARTS) if s <= sec + 1e-9)
    t = sec - STARTS[i]
    im = scene_frame(i, t)
    if i > 0 and t < FADE:
        prev = scene_frame(i - 1, SCENES[i - 1][1] + t)
        im = Image.blend(prev, im, e_io(t / FADE))
    return im


def render_job(n):
    sec = n / FPS
    if sec > TOTAL - 0.4:      # fade the last 0.4 s to black
        im = frame_at(min(sec, TOTAL - 1e-3))
        return Image.blend(im, Image.new("RGB", im.size, NIGHT), seg(sec, TOTAL - 0.4, TOTAL)).tobytes()
    return frame_at(sec).tobytes()


def encode(out, wav, crf=18):
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(TOTAL * FPS)
    with Pool() as pool:
        for k, data in enumerate(pool.imap(render_job, range(n), chunksize=4)):
            proc.stdin.write(data)
            if k % 500 == 0:
                print(f"  frame {k}/{n}", flush=True)
    proc.stdin.close()
    if proc.wait():
        sys.exit("ffmpeg failed")


def small(src, out):
    """720p two-pass H.264 with AAC 64k, sized to stay under 9,000,000 bytes."""
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                         "default=nw=1:nk=1", str(src)]))
    vkbps = int((8_600_000 * 8 / dur - 64_000) / 1000)
    log = str(OUT / "pass")
    base = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", "scale=1280:720:flags=lanczos", "-c:v", "libx264",
            "-preset", "slow", "-b:v", f"{vkbps}k", "-pix_fmt", "yuv420p", "-passlogfile", log]
    subprocess.check_call(base + ["-pass", "1", "-an", "-f", "mp4", "/dev/null"])
    subprocess.check_call(base + ["-pass", "2", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)])
    for f in OUT.glob("pass*.log*"):
        f.unlink()
    print(f"{out}: {out.stat().st_size} bytes at {vkbps} kbit/s video")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT / "rpi5-audioface-overview.mp4"))
    ap.add_argument("--small", action="store_true", help="also write the 720p two-pass file under 9 MB")
    ap.add_argument("--still", type=float, help="write one PNG at this time (seconds) and stop")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.still is not None:
        p = OUT / f"still-{a.still:07.2f}.png"
        frame_at(a.still).save(p)
        print(p)
        return
    import music
    wav = OUT / "build-music.wav"
    music.write_wav(wav, TOTAL)
    encode(FsPath(a.out), wav)
    print(f"{a.out}: {FsPath(a.out).stat().st_size} bytes, {TOTAL} s")
    if a.small:
        small(FsPath(a.out), OUT / "rpi5-audioface-overview-9mb.mp4")


if __name__ == "__main__":
    main()
