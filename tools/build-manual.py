#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the illustrated English guide from docs/MANUAL.md. Needs Pillow and Markdown; no Pi or network access."""

import copy
import base64
import html
import math
import re
import sys
from pathlib import Path

import markdown
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "manual"
IMAGES = OUT / "img"
sys.path.insert(0, str(ROOT / "bridge/rpi-audio-ui"))
import render  # noqa: E402
import sh1106  # noqa: E402
import ui  # noqa: E402

INK = "#183348"
MUTED = "#506878"
TEAL = "#087d76"
BLUE = "#2563ad"
PAPER = "#f3f7fa"
FONTS = Path("/usr/share/fonts/truetype/dejavu")


def font(size=24, bold=False):
    return ImageFont.truetype(str(FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def sheet(title, height=570):
    image = Image.new("RGB", (1440, height), PAPER)
    draw = ImageDraw.Draw(image)
    draw.text((42, 24), title, font=font(31, True), fill=INK)
    return image, draw


def box(draw, bounds, title, detail="", color=TEAL):
    x0, y0, x1, y1 = bounds
    draw.rounded_rectangle(bounds, 18, fill="white", outline=color, width=3)
    draw.rounded_rectangle((x0, y0, x0 + 9, y1), 4, fill=color)
    draw.text((x0 + 24, y0 + 20), title, font=font(27, True), fill=INK)
    if detail:
        lines = []
        for paragraph in detail.splitlines():
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}".strip()
                if line and draw.textlength(candidate, font=font(22)) > x1 - x0 - 48:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
        draw.multiline_text((x0 + 24, y0 + 66), "\n".join(lines), font=font(22), fill=MUTED, spacing=6)


def arrow(draw, start, end, label="", color=TEAL):
    draw.line((start, end), fill=color, width=5)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    points = [end] + [(end[0] - 16 * math.cos(angle + delta), end[1] - 16 * math.sin(angle + delta))
                      for delta in (-0.45, 0.45)]
    draw.polygon(points, fill=color)
    if label:
        middle = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        draw.text((middle[0], middle[1] - 33), label, font=font(20), fill=color, anchor="mm")


def save(image, name):
    image.save(IMAGES / name, optimize=True)


def diagrams():
    image, draw = sheet("Choose the audio mode in Outputs", 880)
    modes = [(155, "USB host mode", "Computer / Force", "Record and play over USB"),
             (405, "Hub: simultaneous outputs", "Local + USB + net", "Listen and record together"),
             (655, "Standalone mode", "pHAT DAC", "Line output to your speakers")]
    for y, mode, target, detail in modes:
        draw.text((44, y - 65), mode, font=font(26, True), fill=TEAL)
        box(draw, (44, y, 352, y + 140), "Your USB gear", "Guitar, mixer, keyboard")
        box(draw, (566, y, 866, y + 140), "Raspberry Pi", "rpi-audio")
        box(draw, (1076, y, 1395, y + 140), target, detail.replace(" to ", "\nto "))
        arrow(draw, (360, y + 75), (553, y + 75), "USB-A")
        arrow(draw, (874, y + 75), (1063, y + 75), "USB-C" if y == 155 else "Hub" if y == 405 else "I2S")
    save(image, "01-uses.png")

    image, draw = sheet("Connect the hardware", 680)
    box(draw, (45, 120, 360, 265), "Audio / MIDI gear", "Connect to USB-A")
    box(draw, (550, 120, 870, 265), "Pi 4 + OLED", "Encoder and buttons")
    box(draw, (1060, 120, 1395, 265), "USB host", "Computer or Force")
    arrow(draw, (369, 192), (537, 192), "USB-A")
    arrow(draw, (878, 192), (1047, 192), "USB data")
    box(draw, (45, 405, 360, 550), "Power supply", "Via splitter in host mode")
    box(draw, (550, 405, 870, 550), "pHAT DAC", "Hub / standalone output")
    box(draw, (1060, 405, 1395, 550), "Listening system", "Amplifier or active speakers")
    arrow(draw, (202, 397), (550, 278), "Power", BLUE)
    arrow(draw, (710, 278), (710, 392), "I2S")
    arrow(draw, (878, 477), (1047, 477), "Line out")
    draw.text((44, 605), "Data and power share the Pi's USB-C port: use the splitter wiring described in the guide.",
              font=font(23), fill=MUTED)
    save(image, "02-connections.png")

    image, draw = sheet("The controls", 470)
    draw.ellipse((100, 125, 320, 345), fill="white", outline=TEAL, width=8)
    draw.line((210, 150, 210, 200), fill=TEAL, width=8)
    draw.text((210, 375), "TURN + PRESS", font=font(26, True), fill=INK, anchor="mm")
    for x, label, detail in ((660, "CONFIRM", "Select / confirm"), (1130, "BACK", "Return / cancel")):
        draw.ellipse((x - 65, 170, x + 65, 300), fill="white", outline=BLUE, width=6)
        draw.text((x, 330), label, font=font(26, True), fill=INK, anchor="mm")
        draw.text((x, 372), detail, font=font(23), fill=MUTED, anchor="mm")
    draw.text((380, 214), "PUSH", font=font(25, True), fill=TEAL)
    save(image, "03-controls.png")

    image, draw = sheet("USB audio: two directions", 470)
    box(draw, (44, 150, 365, 310), "Guitar processor", "Example: 6 in / 4 out")
    box(draw, (556, 150, 876, 310), "Raspberry Pi", "Keeps channel assignments")
    box(draw, (1066, 150, 1395, 310), "Computer / Force", "Select rpi-audio")
    arrow(draw, (372, 195), (545, 195), "Capture")
    arrow(draw, (885, 195), (1055, 195), "IN 3-8")
    arrow(draw, (1055, 278), (885, 278), "OUT 5-8", BLUE)
    arrow(draw, (545, 278), (372, 278), "Playback", BLUE)
    draw.text((44, 380), "Channel numbers are examples. Use Connections to see the assignments on your Pi.",
              font=font(24), fill=MUTED)
    save(image, "07-usb.png")

    image, draw = sheet("Hub: one source, several outputs", 680)
    box(draw, (40, 265, 340, 415), "Audio source", "A device or USB host")
    box(draw, (530, 265, 830, 415), "One router", "Independent routes")
    arrow(draw, (350, 340), (520, 340))
    for y, label, detail in ((105, "pHAT DAC", "Listen locally"), (300, "USB host", "Record by cable"),
                             (495, "Network receiver", "RTP/PCM or Link Audio")):
        box(draw, (1055, y, 1395, y + 135), label, detail, BLUE)
        arrow(draw, (840, 340), (1042, y + 65), color=BLUE)
    save(image, "12-outputs.png")

    image, draw = sheet("Display and encoder wiring — physical pin numbers", 820)
    signals = [(1, "3.3 V supply"), (6, "Ground"), (3, "OLED SDA / GPIO 2"), (5, "OLED SCL / GPIO 3"),
               (11, "Encoder A / GPIO 17"), (13, "Encoder B / GPIO 27"), (15, "PUSH / GPIO 22"),
               (29, "CONFIRM / GPIO 5"), (31, "BACK / GPIO 6")]
    draw.text((44, 100), "Display board / controls", font=font(27, True), fill=INK)
    for n, (pin, label) in enumerate(signals):
        y = 175 + n * 54
        draw.text((52, y), label, font=font(25), fill=INK)
        draw.text((555, y), f"pin {pin}", font=font(25, True), fill=TEAL)
    selected = {pin for pin, _ in signals}
    draw.rounded_rectangle((880, 110, 1320, 725), 20, fill="white", outline=TEAL, width=3)
    draw.text((1100, 139), "Pi 40-pin header", font=font(26, True), fill=INK, anchor="mm")
    for row in range(20):
        y = 192 + row * 26
        for column in range(2):
            pin = row * 2 + column + 1
            x = 1005 + column * 190
            color = TEAL if pin in selected else "#c6d3dd"
            draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=color)
            draw.text((x - 26, y), str(pin), font=font(19), fill=INK, anchor="rm")
    draw.text((44, 755), "SH1106 128x64, I2C 0x3C. pHAT I2S uses GPIO 18, 19 and 21 separately.",
              font=font(24), fill=MUTED)
    save(image, "13-pins.png")


def examples():
    mixer = {"identity": "usb-mixer", "card": "CODEC", "name": "Mixer",
             "in": {"channels": 2, "rate": 48000, "start": 1, "running": True, "level": 80, "muted": False}}
    guitar = {"identity": "usb-guitar", "card": "GP150", "name": "Guitar Rig",
              "in": {"channels": 6, "rate": 48000, "start": 3, "running": True, "level": 85, "muted": False},
              "out": {"channels": 4, "rate": 48000, "start": 5, "running": True, "level": 80, "muted": False}}
    dac = {"identity": "local-dac", "card": "sndrpihifiberry", "name": "pHAT DAC", "local": True,
           "out": {"channels": 2, "rate": 48000, "running": True, "fixed_level": True}}
    hardware = {"wifi": {"state": "up", "signal": 88, "name": "Studio WiFi", "ip": "192.0.2.10"},
                "usb_state": "not attached", "devices": [dac]}
    idle = {"devices": [], "gadget_channels": 26, "midi": {"host_connected": False},
            "host_capture_rate": 0, "host_playback_rate": 0, "presets": []}
    host = {"devices": [mixer, guitar], "gadget_channels": 26, "jack_ready": True, "feeder": "jack",
            "host_capture_rate": 44100, "host_playback_rate": 44100,
            "presets": [{"slot": 1, "name": "Live", "saved": "example"},
                        {"slot": 2, "name": "Studio", "saved": "example"}],
            "midi": {"host_connected": True, "endpoints": [{"endpoint": "usb-guitar/0", "port": 2}]}}
    alone = copy.deepcopy(host)
    alone.update(engine_mode="hub", hub={"card": "sndrpihifiberry", "channels": 2, "rate": 48000},
                 host_capture_rate=0, host_playback_rate=0, midi=None)
    alone["devices"].append(dac)
    for identity, name in (("usb-host", "USB host"), ("network-rtp", "Network RTP"), ("network-link", "Link Audio")):
        alone["devices"].append({"identity": identity, "name": name, "virtual": True, "out": {"channels": 2}})
    outputs = [("local-dac", "pHAT DAC", "active", "I2S"), ("usb-host", "USB host", "waiting", "USB"),
               ("network-rtp", "Network RTP", "sending", "RTP/PCM"),
               ("network-link", "Link Audio", "waiting", "Link Audio")]
    alone["outputs"] = [{"identity": identity, "name": name, "enabled": True, "state": state,
                         "protocol": protocol, "channels": 2, "address": "239.69.1.1", "port": 5004,
                         "sdp": "/run/rpi-audio/network-rtp.sdp", "http_port": 8080}
                        for identity, name, state, protocol in outputs]
    alone["routes"] = [{"src": "usb-mixer", "dst": "local-dac", "waiting": None}]
    alone["midi_ports"] = [{"identity": "usb-keys", "name": "Keys", "port": 0, "in": True},
                           {"identity": "usb-guitar", "name": "Guitar Rig", "port": 0, "in": True, "out": True}]
    return hardware, idle, host, alone


def screen(screen, status, hardware, levels=None):
    interface = ui.UI()
    interface.stack = [screen]
    interface.hardware = hardware
    interface.levels = levels or {}
    return panel(interface.render(status))


def panel(rows):
    canvas = render.draw_rows(sh1106.Canvas(), rows)
    image = Image.new("RGB", (128, 64), "#02090d")
    for y in range(64):
        for x in range(128):
            if canvas.get(x, y):
                image.putpixel((x, y), (213, 245, 255))
    return image.resize((640, 320), Image.Resampling.NEAREST)


def pair(name, first, second):
    image, draw = sheet("Example screens — rendered by rpi-audio", 450)
    for x, (label, panel) in zip((42, 758), (first, second)):
        draw.text((x, 88), label, font=font(25, True), fill=INK)
        image.paste(panel, (x, 125))
    save(image, name)
    # Keep the OLED lettering readable on narrow screens rather than shrinking two displays side by side.
    mobile = Image.new("RGB", (720, 890), PAPER)
    mobile_draw = ImageDraw.Draw(mobile)
    mobile_draw.text((40, 25), "OLED examples", font=font(28, True), fill=INK)
    for y, (label, panel) in zip((90, 495), (first, second)):
        mobile_draw.text((40, y), label, font=font(25, True), fill=INK)
        mobile.paste(panel, (40, y + 45))
    (IMAGES / "mobile").mkdir(exist_ok=True)
    mobile.save(IMAGES / "mobile" / name, optimize=True)


def screenshots():
    hw, idle, host, alone = examples()
    live_hw = {**hw, "usb_state": "configured"}
    pair("04-overview.png", ("No host stream", screen(ui.Overview(), idle, hw)),
         ("Example active signal", screen(ui.Overview(), host, live_hw, {"in": 0.25, "out": 0.5})))
    home = ui.Home()
    home.cursor = 5
    pair("05-connections.png", ("1. Open Connections", screen(home, host, live_hw)),
         ("2. Choose a connection", screen(ui.Connections(), host, live_hw)))
    capabilities = ui.DeviceInfo("usb-guitar")
    mapping = ui.DeviceInfo("usb-guitar")
    mapping.cursor = 8
    pair("06-mappings.png", ("Device capabilities", screen(capabilities, host, live_hw)),
         ("Scroll down for mappings", screen(mapping, host, live_hw)))
    routes = ui.SendAudio()
    pair("08-routes.png", ("1. Choose the source", screen(routes, alone, hw)),
         ("2. Enable destinations", screen(ui.SendTargets("usb-mixer", 1), alone, hw)))
    device = ui.Device("usb-guitar")
    device.cursor, device.editing = 1, ("in", 85)
    pair("09-levels-midi.png", ("Edit a level, then press", screen(device, host, live_hw)),
         ("MIDI destinations for Keys", screen(ui.MidiTargets("usb-keys/0"), alone, hw)))
    presets = ui.Presets()
    presets.cursor = 1
    pair("10-presets.png", ("Choose a slot", screen(presets, host, live_hw)),
         ("Confirm before saving", screen(ui.Confirm("Save scene?", "Replace slot 2?", [], ""), host, live_hw)))
    pair("14-outputs.png", ("Output switches and states", screen(ui.Outputs(), alone, hw)),
         ("RTP connection details", screen(ui.OutputInfo("network-rtp"), alone, hw)))
    health_hw = {**hw, 'machine': {'cpu_pct': 23, 'memory_pct': 48, 'temperature': 46.5, 'uptime': 7200},
                 'pcm': {'sndrpihifiberry/out': {'buffer_size': 768, 'period_size': 256}}}
    alone['engine'] = {'rate': 48000, 'period': 256, 'periods': 3}
    pair('15-status.png', ('Machine health', screen(ui.MachineInfo(), alone, health_hw)),
         ('Inputs with real-peak layout', screen(ui.IOStatus('in'), alone, health_hw, {'p0': 0.25, 'p1': 0.5})))
    pair('16-status-saver.png',
         ('Status saver: machine', panel(ui.saver_rows('status', 0, status=alone, hardware=health_hw))),
         ('Status saver: buffers', panel(ui.saver_rows('status', 6, status=alone, hardware=health_hw))))
    pair("11-settings.png", ("Display preferences", screen(ui.Settings(), idle, hw)),
         ("WiFi details (example)", screen(ui.WifiInfo(), idle, hw)))


CSS = """
:root { color-scheme:light; --ink:#183348; --teal:#087d76; --line:#d9e3e9; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; scroll-padding-top:24px; }
body { margin:0; color:var(--ink); background:#f3f7fa;
 font:17px/1.7 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
a { color:#086b9d; text-underline-offset:3px; }
a:hover { color:var(--teal); }
.brand { padding:18px 5%; background:var(--ink); color:white; font-weight:700; letter-spacing:.05em; }
.layout { max-width:1440px; margin:auto; display:grid; grid-template-columns:260px minmax(0,1fr); gap:38px;
 padding:36px 28px 80px; }
nav { position:sticky; top:24px; align-self:start; max-height:90vh; overflow:auto;
 font-size:14px; line-height:1.5; padding:8px 12px; }
nav strong { display:block; color:var(--teal); margin-bottom:16px; }
nav a { display:block; padding:5px 0; color:var(--ink); text-decoration:none; }
.mobile-contents { display:none; }
main { min-width:0; background:white; padding:38px 44px; border:1px solid var(--line); border-radius:16px; }
h1 { font-size:2.7rem; line-height:1.15; letter-spacing:-.04em; margin:0 0 22px; }
h2 { margin:64px 0 18px; padding-top:28px; border-top:1px solid var(--line); font-size:1.65rem; line-height:1.3; }
h3 { margin-top:28px; font-size:1.18rem; }
p,li { max-width:80ch; }
li { margin:7px 0; padding-left:4px; }
img { display:block; width:100%; height:auto; margin:26px 0; border:1px solid var(--line); border-radius:9px; }
blockquote { margin:24px 0; padding:10px 20px; background:#edf7f5; border-left:4px solid var(--teal); }
blockquote p { margin:8px 0; }
table { border-collapse:collapse; width:100%; margin:24px 0; font-size:.92rem; }
th,td { text-align:left; vertical-align:top; padding:12px 15px; border-bottom:1px solid var(--line); }
th { background:#edf3f7; }
tr:nth-child(even) td { background:#fafcfd; }
code { font: .88em ui-monospace,SFMono-Regular,Consolas,monospace; background:#edf3f7; padding:2px 5px; }
pre { overflow:auto; padding:20px; background:#132c3c; color:#edf8ff; border-radius:8px; font-size:.88rem; }
pre code { padding:0; background:none; color:inherit; }
footer { padding:24px 5%; font-size:14px; color:#506878; }
@media(max-width:960px) { .layout { grid-template-columns:1fr; padding:16px; } nav { display:none; }
 .mobile-contents { display:block; padding:12px 0 22px; font-size:.9rem; }
 .mobile-contents summary { cursor:pointer; color:var(--teal); font-weight:600; }
 .mobile-contents a { display:block; padding:5px 0; } main { padding:24px 20px; }
 h1 { font-size:2.1rem; } table { display:block; overflow:auto; } }
@media print { body,main { background:white; } nav,.brand,footer { display:none; }
 .layout { display:block; padding:0; } main { padding:0; border:0; } h2 { break-before:page; }
 img,table { break-inside:avoid; } }
"""


def build_html():
    source = (DOCS / "MANUAL.md").read_text()
    body = markdown.markdown(source, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    body = body.replace('src="manual/img/', 'src="img/')
    for image in sorted((IMAGES / "mobile").glob("*.png")):
        pattern = rf'<img\b[^>]*src="img/{re.escape(image.name)}"[^>]*>'
        replacement = (f'<picture><source media="(max-width:640px)" srcset="img/mobile/{image.name}">'
                       r'\g<0></picture>')
        body = re.sub(pattern, replacement, body)

    def link(match):
        target = match[1]
        if re.match(r"(?:https?:|mailto:|#)", target):
            return match[0]
        target = target.removeprefix("manual/") if target.startswith("manual/") else "../" + target
        return f'href="{html.escape(target, quote=True)}"'

    body = re.sub(r'href="([^"]+)"', link, body)

    def inline_image(match):
        attribute, relative = match.groups()
        data = base64.b64encode((OUT / relative).read_bytes()).decode("ascii")
        return f'{attribute}="data:image/png;base64,{data}"'

    body = re.sub(r'(src|srcset)="(img/[^"]+)"', inline_image, body)
    headings = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    navigation = "\n".join(f'<a href="#{anchor}">{title}</a>' for anchor, title in headings if title != "Contents")
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="An illustrated, plain-language guide to the rpi-audio OLED and audio hub.">
<title>rpi-audio user guide</title><style>{CSS}</style></head><body>
<header class="brand">rpi-audio · USER GUIDE</header>
<div class="layout"><nav aria-label="Guide chapters"><strong>In this guide</strong>{navigation}</nav>
<main><details class="mobile-contents"><summary>Contents — choose a chapter</summary>{navigation}</details>
{body}</main></div>
<footer>Generated from docs/MANUAL.md and the current OLED renderer. No network access is required to read this guide.
</footer></body></html>'''
    (OUT / "index.html").write_text(document)


def main():
    IMAGES.mkdir(parents=True, exist_ok=True)
    diagrams()
    screenshots()
    build_html()
    print(f"Built {OUT.relative_to(ROOT) / 'index.html'} and {len(list(IMAGES.glob('*.png')))} figures")


if __name__ == "__main__":
    main()
