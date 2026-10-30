#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generates the panel's native MPC skin (TUI.json, Q-Links, PNGs) and desktop previews. Original artwork.

    skin.py <out-dir>          skin folder '<vendor> - VST - <name>' under out-dir, build/params.h, previews

Static text is baked with Titillium Web (OFL, fonts/OFL.txt). Live text is MPC's own Label (also Titillium Web);
its size is an MPC font height, which is 1.52 x the em size [ext: sd88me docs/COMMUNITY_SKINS.md], and the
previews draw it that way. Pillow only; no other dependency.
"""
import json
import pathlib
import shutil
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "vendor/mpc-vst-plugins/tools"))
import gen_vst  # noqa: E402
import panel_def as D  # noqa: E402

W, H = D.W, D.H
# one accent (mint) on a cool dark base; red appears only as the "muted" signal
BG, CARD, CARD2, LINE = "0D1014", "161A20", "1C2128", "2A313B"
INK, DIM, FAINT = "EEF2F6", "98A2B0", "5E6877"
ACCENT, ACCENT_DK, ON_ACCENT = "3BE3C4", "0F3B34", "05231E"
RED = "F2616B"
S = 3  # supersampling for baked art

VENDOR, NAME = "rpi-audio", "rpi-audio Panel"
FOLDER = f"{VENDOR} - VST - {NAME}"
MPC_EM = 1.52  # MPC live-text height = 1.52 x em


def font(size, weight="SemiBold"):
    return ImageFont.truetype(str(HERE / "fonts" / f"TitilliumWeb-{weight}.ttf"), size)


class SS:
    """RGBA canvas drawn at S x and reduced, for smooth edges."""

    def __init__(self, w, h, bg=(0, 0, 0, 0)):
        self.w, self.h = w, h
        self.im = Image.new("RGBA", (w * S, h * S), bg)
        self.d = ImageDraw.Draw(self.im)

    def rr(self, box, r, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = box
        fill = fill and "#" + fill if isinstance(fill, str) else fill
        self.d.rounded_rectangle((x0 * S, y0 * S, x1 * S - 1, y1 * S - 1), r * S, fill=fill,
                                 outline=outline and "#" + outline, width=max(1, int(width * S)))

    def line(self, pts, color, width=1):
        self.d.line([(x * S, y * S) for x, y in pts], fill="#" + color, width=max(1, int(width * S)), joint="curve")

    def ellipse(self, box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = box
        self.d.ellipse((x0 * S, y0 * S, x1 * S, y1 * S), fill=fill and "#" + fill, outline=outline and "#" + outline,
                       width=max(1, int(width * S)))

    def text(self, xy, s, size, color, weight="SemiBold", anchor="mm", track=0.0):
        f = font(size * S, weight)
        x, y = xy[0] * S, xy[1] * S
        if not track:
            self.d.text((x, y), s, font=f, fill="#" + color, anchor=anchor)
            return
        widths = [f.getlength(c) + track * S for c in s]
        total = sum(widths) - track * S
        x -= total / 2 if anchor[0] == "m" else total if anchor[0] == "r" else 0
        for c, wd in zip(s, widths):
            self.d.text((x, y), c, font=f, fill="#" + color, anchor="l" + anchor[1])
            x += wd

    def done(self):
        return self.im.resize((self.w, self.h), Image.LANCZOS)


def text_fit(s, height, weight="SemiBold"):
    """Width in px of live text of MPC font height `height`."""
    return font(height / MPC_EM, weight).getlength(s)


# ---- artwork ----------------------------------------------------------------------------------------

def background():
    im = Image.new("RGB", (W, H), "#" + BG)
    d = ImageDraw.Draw(im)
    for y in range(H):  # faint vertical falloff
        c = int(8 * (1 - y / H))
        d.line((0, y, W, y), fill=(13 + c, 16 + c, 20 + c))
    d.rectangle((0, 0, W, 92), fill="#10141A")
    d.line((0, 92, W, 92), fill="#" + LINE)
    im = im.convert("RGBA")
    c = SS(W, H)
    # logo: a rounded mint tile with three level bars
    c.rr((24, 22, 68, 66), 11, fill=ACCENT)
    for i, hh in enumerate((14, 24, 18)):
        x = 33 + i * 11
        c.rr((x, 44 - hh / 2, x + 6, 44 + hh / 2), 3, fill=ON_ACCENT)
    c.text((80, 36), "rpi-audio", 30, INK, "Bold", "lm")
    c.text((342, 15), "PRESETS", 12, FAINT, "SemiBold", "lm", track=2.2)
    c.line([(324, 22), (324, 76)], LINE, 1)
    for s in range(D.STRIPS):  # empty slots, covered by a strip's card when a device is there
        x = D.strip_x(s)
        c.rr((x, D.STRIP_Y, x + D.STRIP_W, D.STRIP_Y + D.STRIP_H), 14, fill="0F1318", outline="1B2129", width=1.5)
        c.text((x + D.STRIP_W / 2, D.STRIP_Y + D.STRIP_H / 2 - 8), str(s + 1), 44, "1C232C", "Bold")
        c.text((x + D.STRIP_W / 2, D.STRIP_Y + D.STRIP_H / 2 + 28), "NO DEVICE", 13, "3A4350", "SemiBold", track=2.0)
    c.text((32, D.FOOT_Y + 26), "ON PROJECT LOAD", 13, FAINT, "SemiBold", "lm", track=2.2)
    hint = ["Tap a device name to label it.", "Turn SAVE on, then tap a preset to store the routing."]
    for i, t in enumerate(hint):
        c.text((W - 32, D.FOOT_Y + 18 + i * 20), t, 14, FAINT, "Regular", "rm")
    im.alpha_composite(c.done())
    return im


def strip_card():
    c = SS(D.STRIP_W, D.STRIP_H)
    c.rr((0, 0, D.STRIP_W, D.STRIP_H), 14, fill=CARD, outline=LINE, width=1.5)
    c.line([(26, 1.2), (D.STRIP_W - 26, 1.2)], ACCENT, 2.4)  # live-strip accent edge
    c.line([(12, 78), (D.STRIP_W - 12, 78)], LINE, 1)
    c.line([(12, 125), (D.STRIP_W - 12, 125)], "20262E", 1)
    c.line([(98, D.FADER_Y - D.DIM_TOP + 4), (98, D.STRIP_H - 12)], "20262E", 1)
    c.line([(D.STRIP_W - 24, 25), (D.STRIP_W - 19, 31), (D.STRIP_W - 14, 25)], FAINT, 2)  # "tap to pick" chevron
    for x, tag in zip(D.COL_X, ("IN", "OUT")):
        c.text((x + D.COL_W - 11, D.VALUE_Y + 15), "%", 15, FAINT, "SemiBold")
        c.text((x + D.COL_W / 2, D.FADER_Y - 10), tag, 12, FAINT, "SemiBold", track=2.2)  # which column is which
    return c.done()


def fader_strip():
    w, h, n = D.COL_W, D.FADER_H, D.FADER_FRAMES
    top, bot = 22, h - 22
    strip = Image.new("RGBA", (w, h * n), (0, 0, 0, 0))
    for i in range(n):
        c = SS(w, h)
        v = i / (n - 1)
        yy = bot - (bot - top) * v
        cx = w / 2
        c.rr((cx - 5, top - 6, cx + 5, bot + 6), 5, fill="0A0D11", outline="232A33")
        for t in range(5):  # scale ticks
            ty = top + (bot - top) * t / 4
            c.line([(8, ty), (17, ty)], "3A4350", 1.5)
            c.line([(w - 17, ty), (w - 8, ty)], "3A4350", 1.5)
        if v > 0:
            c.rr((cx - 3, yy, cx + 3, bot + 3), 3, fill=ACCENT)
        c.rr((10, yy - 15, w - 10, yy + 15), 9, fill="E9EEF3", outline="8E99A7", width=1.2)
        c.line([(24, yy), (w - 24, yy)], ON_ACCENT if v > 0 else "7A8594", 2.5)
        c.line([(24, yy - 7), (w - 24, yy - 7)], "BCC5CF", 1)
        c.line([(24, yy + 7), (w - 24, yy + 7)], "BCC5CF", 1)
        strip.paste(c.done(), (0, i * h))
    return strip


def button_pair(w, h, label, size=16, number=None, kind="plain"):
    """(off, on) images. plain: dark / mint-outlined; solid: dark / filled mint; mute: dark / red."""
    out = []
    for on in (0, 1):
        c = SS(w, h)
        if kind == "solid":
            fill, edge, ink = (ACCENT, ACCENT, ON_ACCENT) if on else (CARD2, LINE, DIM)
        elif kind == "mute":
            fill, edge, ink = (RED, RED, "2A0A0E") if on else (CARD2, LINE, DIM)
        else:
            fill, edge, ink = (ACCENT_DK, ACCENT, ACCENT) if on else (CARD2, LINE, INK if kind == "option" else DIM)
        c.rr((0.75, 0.75, w - 0.75, h - 0.75), 9, fill=fill, outline=edge, width=1.5)
        if number is not None:
            c.text((10, 11), str(number), 12, ACCENT if on else FAINT, "Bold", "lm")
        while label and size > 10 and font(size, "Bold").getlength(label) > w - 12:
            size -= 1
        if label:
            c.text((w / 2 + (8 if kind == "solid" else 0), h / 2), label, size, ink, "Bold")
        if kind == "solid":  # record-style dot beside SAVE
            c.ellipse((w / 2 - 36, h / 2 - 6, w / 2 - 24, h / 2 + 6),
                      fill=ON_ACCENT if on else None, outline=ink, width=2)
        out.append(c.done())
    return out


def dim_overlay():
    w, h = D.COL_W + 8, D.MUTE_Y + D.MUTE_H - D.FADER_Y + D.DIM_TOP + 6
    c = SS(w, h)
    c.rr((0, 0, w, h), 10, fill=(22, 26, 32, 205))
    return c.done()


def popup_panel():
    w, h = D.STRIP_W, D.POP_H
    c = SS(w, h)
    c.rr((0, 0, w, h), 12, fill="0F1318", outline=ACCENT_DK, width=2)
    return c.done()


# ---- native skin JSON -----------------------------------------------------------------------------

def bounds(x, y, w, h, focus="No", condition=None, visible="Always"):
    return dict(version=2, acceptsHWFocus=focus, showWhenDataModelInvalid="Show", whenVisible=visible,
                boundsType="Absolute", bounds=f"{x} {y} {w} {h}",
                additionalInvalidatingHandles=[] if condition is None else [condition])


def component(kind, data, box, name="", mapping=None, focus="No", condition=None, visible="Always"):
    return {"version": 2, "componentData": {"version": 1, "name": name, "type": kind, "data": data},
            "handle remapping": {"version": 1, "map": mapping or []},
            "bounds": bounds(*box, focus, condition, visible)}


def action(event, handler, additional=""):
    return {"version": 2, "onAction": event, "handler": handler,
            "handleName": "" if handler == "Show Overlay" else "Data",
            "additionalData": additional, "handle remapping": {"version": 1, "map": []}}


def local(key, children, actions=None):
    clear = {"version": 1, "colour": "0", "image": ""}
    return {"key": key, "value": {"version": 4, "actions": actions or [],
                                  "backgroundData": {"version": 1, "focussed": clear, "unfocussed": clear},
                                  "ignoreMousePresses": False, "disableCoarseDataWheel": False, "repeats": 1,
                                  "hideQLinkBounds": True, "componentsData": children}}


def label(box, height, colour, just="horizontallyCentred verticallyCentred", handle="Data", weight="SemiBold"):
    font = {"version": 1, "name": "Titillium Web", "style": weight, "height": float(height)}
    return component("Label", {"version": 1, "textStyle": {
        "version": 1, "font": font, "colour": "ff" + colour, "justification": just, "case": "Original"},
        "type": "Value", "handleName": handle}, box, "Value")


def focus(w, h):
    return component("Focus", {"version": 1, "backgroundColour": "00000000", "outlineColour": "00000000",
                               "backgroundInset": 2.0, "outlineThickness": 0.0}, (0, 0, w, h), "Focus",
                     visible="WhenFocussed")


def button_child(on, off, w, h, button_id=1, group=1):
    return component("Button", {"version": 2, "onImage": on, "offImage": off, "buttonId": button_id,
                                "numButtonsInGroup": group, "handleName": "Data", "gestureBehaviour": "Instant"},
                     (0, 0, w, h), "Button")


def cond(param, option, count):
    return f"IndexedEnabling/{option}/{count}/Parameter {D.INDEX[param]}"


class Skin:
    def __init__(self, out):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.defs, self.kids, self.top, self.assets = {}, [], [], {}
        self.regions = []  # (name, box) for validation

    def save(self, name, image):
        image.save(self.out / name, optimize=True)
        self.assets[name] = image
        return name

    def define(self, key, children, actions=None):
        self.defs.setdefault(key, local(key, children, actions))

    def place(self, key, name, param, box, extra=None, condition=None, focus="No", top=False):
        mapping = [{"key": "Data", "value": f"Parameter {D.INDEX[param]}"}]
        for handle, target in (extra or {}).items():
            mapping.append({"key": handle, "value": f"Parameter {D.INDEX[target]}"})
        (self.top if top else self.kids).append(component(key, {"version": 1, "handleName": "Data"}, box, name,
                                                          mapping, focus, condition))
        self.regions.append((name, box))

    def text(self, name, param, box, height, colour, just="horizontallyCentred verticallyCentred", condition=None,
             weight="SemiBold"):
        x, y, w, h = box
        key = f"Txt_{w}x{h}_{int(height)}_{colour}_{just.split()[0]}_{weight}"
        self.define(key, [label((0, 0, w, h), height, colour, just, weight=weight)])
        self.place(key, name, param, box, condition=condition)

    def image(self, name, file, param, box, condition, top=False):
        key = f"Img_{file[:-4]}"
        self.define(key, [component("Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": file},
                                    (0, 0, box[2], box[3]), "Image")])
        self.place(key, name, param, box, condition=condition, top=top)

    # -- parts --

    def build(self):
        self.save("background.png", background().convert("RGB"))
        self.kids.append(component("Image", {"version": 2, "imageType": "Regular", "colour": "0",
                                             "image": "background.png"}, (0, 0, W, H), "Background"))
        self.header()
        for s in range(D.STRIPS):
            self.strip(s)
        self.footer()
        for s in range(D.STRIPS):
            self.picker(s)
        children = self.kids + self.top
        self.defs["PanelPage"] = local("PanelPage", children)

    def header(self):
        lx, ly, lw, lh = D.HEAD["link"]
        self.text("Link", "link", (lx, ly, lw, lh), 26, DIM, "left verticallyCentred")
        w, h = D.HEAD["preset_w"], D.HEAD["preset_h"]
        for k in range(D.PRESETS):
            off, on = button_pair(w, h, "", number=k + 1)
            self.save(f"preset_{k + 1}_off.png", off)
            self.save(f"preset_{k + 1}_on.png", on)
            key = f"PresetBtn_{k + 1}"
            # the name label lies over the button and takes the touch, so the row toggles on Mouse Down
            self.define(key, [focus(w, h), button_child(f"preset_{k + 1}_on.png", f"preset_{k + 1}_off.png", w, h),
                              label((6, 18, w - 12, h - 22), 24, INK, handle="Text")],
                        [action("Mouse Down", "Toggle Switch"), action("Enter Pressed", "Toggle Switch")])
            self.place(key, f"Preset {k + 1}", f"preset_{k + 1}", (D.preset_x(k), D.HEAD["presets_y"], w, h),
                       extra={"Text": f"preset_name_{k + 1}"}, focus="Yes" if k == 0 else "No")
        sx, sy, sw, sh = D.HEAD["save"]
        off, on = button_pair(sw, sh, "SAVE", 19, kind="solid")
        self.save("save_off.png", off)
        self.save("save_on.png", on)
        self.define("SaveBtn", [button_child("save_on.png", "save_off.png", sw, sh)],
                    [action("Mouse Down", "Q-Link"), action("Enter Pressed", "Toggle Switch")])
        self.place("SaveBtn", "Save", "save", (sx, sy, sw, sh), focus="Yes")

    def strip(self, s):
        n, x0, y0 = s + 1, D.strip_x(s), D.STRIP_Y
        k = lambda f: f"s{n}_{f}"  # noqa: E731
        present = cond(k("present"), 1, 2)
        self.image(f"S{n} Card", "strip_card.png", k("present"), (x0, y0, D.STRIP_W, D.STRIP_H), present)
        # the name is the popup field: Data = the list's open flag, Text = the name
        self.define("NameField", [focus(168, 38), label((0, 0, 168, 38), 30, INK, handle="Text")],
                    [action("Mouse Down", "Toggle Switch"), action("Enter Pressed", "Toggle Switch")])
        self.place("NameField", f"S{n} Name", k("kind__open"), (x0 + 8, y0 + 10, 168, 38), extra={"Text": k("name")},
                   condition=present, focus="Yes")
        self.text(f"S{n} State", k("state"), (x0 + 10, y0 + 50, D.STRIP_W - 20, 24), 22, DIM, condition=present)
        for d, tag in enumerate(("in", "out")):
            self.text(f"S{n} {tag.upper()} Range", k(f"{tag}_range"), (x0 + 10, y0 + D.RANGE_Y[d], 176, 22), 22, INK,
                      "left verticallyCentred", present, "Bold")
            self.text(f"S{n} {tag.upper()} Names", k(f"{tag}_names"), (x0 + 10, y0 + D.NAMES_Y[d], 176, 20), 20, DIM,
                      "left verticallyCentred", present, "Regular")
        for d, tag in enumerate(("in", "out")):
            shown = cond(k(f"{tag}_vis"), 1, 3)
            cx = x0 + D.COL_X[d]
            fw, fh = D.COL_W, D.FADER_H + 4 + D.VALUE_H
            self.define("Fader", [component("Knob", {"version": 5, "knobType": "FilmStrip", "filmStrip": "fader.png",
                                                     "numFrames": D.FADER_FRAMES, "invert": False,
                                                     "dragOrientation": "Vertical", "handleName": "Data"},
                                            (0, 0, D.COL_W, D.FADER_H), "Fader"),
                                  label((0, D.FADER_H + 4, D.COL_W - 22, D.VALUE_H), 34, INK)],
                        [action("Mouse Down", "Q-Link"), action("Double Click", "Show Overlay", "knob overlay"),
                         action("Enter Pressed", "Show Overlay", "knob overlay")])
            self.place("Fader", f"S{n} {tag.upper()} Level", k(f"{tag}_level"), (cx, y0 + D.FADER_Y, fw, fh),
                       condition=shown, focus="Yes")
            self.define("Mute", [button_child("mute_on.png", "mute_off.png", D.COL_W, D.MUTE_H)],
                        [action("Mouse Down", "Q-Link"), action("Enter Pressed", "Toggle Switch")])
            self.place("Mute", f"S{n} {tag.upper()} Mute", k(f"{tag}_mute"), (cx, y0 + D.MUTE_Y, D.COL_W, D.MUTE_H),
                       condition=shown, focus="Yes")
            self.image(f"S{n} {tag.upper()} Dim", "dim.png", k(f"{tag}_vis"),
                       (cx - 4, y0 + D.FADER_Y - D.DIM_TOP, D.COL_W + 8,
                        D.MUTE_Y + D.MUTE_H - D.FADER_Y + D.DIM_TOP + 6),
                       cond(k(f"{tag}_vis"), 2, 3))

    def footer(self):
        for o, (x, y, w, h) in enumerate(D.onload_rects()):
            label_text = "NONE" if o == 0 else str(o)
            off, on = button_pair(w, h, label_text, 16, kind="plain")
            self.save(f"onload_{o}_off.png", off)
            self.save(f"onload_{o}_on.png", on)
            key = f"OnLoad_{o}"
            self.define(key, [button_child(f"onload_{o}_on.png", f"onload_{o}_off.png", w, h, o, D.PRESETS + 1)],
                        [action("Mouse Down", "Q-Link")])
            self.place(key, f"On Load {label_text}", "onload", (x, y, w, h), focus="Yes" if o == 0 else "No")

    def picker(self, s):
        n, x0, y0 = s + 1, D.strip_x(s), D.STRIP_Y
        opened = cond(f"s{n}_kind__open", 1, 2)
        self.image(f"S{n} Type List", "popup_panel.png", f"s{n}_kind__open", (x0, y0 + D.POP_Y, D.STRIP_W, D.POP_H),
                   opened, top=True)
        rects, close = D.option_rects(s)
        for o, (x, y, w, h) in enumerate(rects):
            key = f"TypeOpt_{o}"
            self.define(key, [button_child(f"opt_{o}_on.png", f"opt_{o}_off.png", w, h, o, len(D.KINDS))],
                        [action("Mouse Down", "Q-Link")])
            self.place(key, f"S{n} Type {D.KINDS[o]}", f"s{n}_kind", (x0 + x, y0 + y, w, h), condition=opened, top=True)
        key = "TypeClose"
        self.define(key, [button_child("close.png", "close.png", close[2], close[3])],
                    [action("Mouse Down", "Toggle Switch"), action("Enter Pressed", "Toggle Switch")])
        self.place(key, f"S{n} Type Close", f"s{n}_kind__open", (x0 + close[0], y0 + close[1], close[2], close[3]),
                   condition=opened, top=True)

    def assets_common(self):
        self.save("strip_card.png", strip_card())
        self.save("fader.png", fader_strip())
        off, on = button_pair(D.COL_W, D.MUTE_H, "MUTE", 17, kind="mute")
        self.save("mute_off.png", off)
        self.save("mute_on.png", on)
        self.save("dim.png", dim_overlay())
        self.save("popup_panel.png", popup_panel())
        for o, (x, y, w, h) in enumerate(D.option_rects(0)[0]):
            off, on = button_pair(w, h, D.KINDS[o], 16, kind="option")
            self.save(f"opt_{o}_off.png", off)
            self.save(f"opt_{o}_on.png", on)
        close = D.option_rects(0)[1]
        c = SS(close[2], close[3])
        c.rr((0.75, 0.75, close[2] - 0.75, close[3] - 0.75), 9, fill="12171D", outline=LINE, width=1.5)
        c.text((close[2] / 2, close[3] / 2), "CLOSE", 14, DIM, "Bold", track=2.0)
        self.save("close.png", c.done())


def qlink_map(index):
    order = [13, 9, 5, 1, 14, 10, 6, 2, 15, 11, 7, 3, 16, 12, 8, 4]  # physical knob slots, banks 1 then 2
    out = {f"Q-Link {i}": -1 for i in range(1, 17)}
    for slot, key in enumerate(D.QLINK_KEYS):
        out[f"Q-Link {order[slot]}"] = index[key]
    return out


def write_skin(root, version):
    folder = root / FOLDER
    if folder.exists():
        shutil.rmtree(folder)
    skin = Skin(folder / "Plugin Skins")
    skin.assets_common()
    skin.build()
    tui = {"pageData": {"version": 1, "componentDefinitions": {"version": 2,
           "importFiles": ["/usr/share/Akai/Content/Synths/Generic/Generic Knob Overlay.json"],
           "localComponentDefinitions": list(skin.defs.values())},
           "info": {"version": 1, "type": "CompleteDescription"},
           "tabs": [{"version": 3, "tabName": "PANEL", "fnKeyIndex": 0, "fnKeySubIndex": 0,
                     "qlinkBoundsData": ["0 0 0 0"], "componentName": "PanelPage",
                     "initialSize": f"0 0 {W} {H}", "scale": 1.0}]}}
    coremap = qlink_map(D.INDEX)
    qmap = {"version": 4, "info": {"version": 1, "type": "CompleteDescription"},
            "Screen Mode Q-Links": {"version": 4, "map": [
                {"Tab": 1, "SubTab": 1, "Bank Direction": "Column", "Q-Links": coremap}]},
            "Program Mode Q-Links": coremap}
    for name, data in (("TUI.json", tui), ("Q-Links.json", qmap), ("Q-Links - 8by1.json", qmap)):
        (skin.out / name).write_text(json.dumps(data, indent=2) + "\n")
    (folder / "version.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<plugincontent version="1.0"><identifier>rpi-audio.vst.rpiaudiopanel'
        f'</identifier><version>{version}</version></plugincontent>\n')
    return folder, skin


def validate(skin):
    out, errors = skin.out, []
    tui = json.loads((out / "TUI.json").read_text())
    defs = {d["key"]: d["value"] for d in tui["pageData"]["componentDefinitions"]["localComponentDefinitions"]}
    refs = set()

    def walk(comps, where):
        for c in comps:
            data, b = c["componentData"]["data"], c["bounds"]["bounds"]
            x, y, w, h = map(int, b.split())
            for attr in ("image", "filmStrip", "onImage", "offImage"):
                if data.get(attr):
                    refs.add(data[attr])
            if data.get("filmStrip"):
                im = Image.open(out / data["filmStrip"])
                if im.width != w or im.height != h * data["numFrames"] or im.height > 16384:
                    errors.append("filmstrip geometry " + where)
            for m in c["handle remapping"]["map"]:
                if m["value"].startswith("Parameter ") and not 0 <= int(m["value"].split()[-1]) < len(D.PARAMS):
                    errors.append("bad parameter in " + where)

    for key, d in defs.items():
        walk(d["componentsData"], key)
    for name, (x, y, w, h) in skin.regions:
        if min(x, y) < 0 or w <= 0 or h <= 0 or x + w > W or y + h > H:
            errors.append("out of canvas: " + name)
    for r in refs:
        if not (out / r).is_file():
            errors.append("missing asset " + r)
    q = json.loads((out / "Q-Links.json").read_text())["Screen Mode Q-Links"]["map"][0]["Q-Links"]
    used = [v for v in q.values() if v >= 0]
    if len(used) != 16 or len(set(used)) != 16:
        errors.append("Q-Link map")
    assert not errors, "\n".join(errors)
    return {"assets": len(refs), "components": len(skin.regions), "defs": len(defs)}


# ---- desktop preview ---------------------------------------------------------------------------------

def live(im, box, s, height, colour, just="c", weight="SemiBold", warn=None):
    d = ImageDraw.Draw(im)
    f = font(height / MPC_EM, weight)
    x, y, w, h = box
    if warn is not None and f.getlength(s) > w:
        warn.append(f"text too wide ({f.getlength(s):.0f} > {w}px): {s!r}")
    if just == "c":
        d.text((x + w / 2, y + h / 2), s, font=f, fill="#" + colour, anchor="mm")
    else:
        d.text((x, y + h / 2), s, font=f, fill="#" + colour, anchor="lm")


def preview(skin, scene, warn):
    """Composite of the same PNGs and boxes as the native skin, with `scene` supplying the live text and values."""
    A = skin.assets
    im = A["background.png"].convert("RGBA")

    def paste(name, pos):
        im.alpha_composite(A[name].convert("RGBA"), pos)

    lx, ly, lw, lh = D.HEAD["link"]
    live(im, (lx, ly, lw, lh), scene["link"], 26, DIM, "l", warn=warn)
    for k in range(D.PRESETS):
        x, y = D.preset_x(k), D.HEAD["presets_y"]
        paste(f"preset_{k + 1}_{'on' if scene.get('pressed') == k else 'off'}.png", (x, y))
        live(im, (x + 6, y + 18, D.HEAD["preset_w"] - 12, D.HEAD["preset_h"] - 22), scene["presets"][k], 24,
             INK if scene["presets"][k] != "-" else FAINT, warn=warn)
    paste("save_on.png" if scene.get("save") else "save_off.png", D.HEAD["save"][:2])
    for o, (x, y, w, h) in enumerate(D.onload_rects()):
        paste(f"onload_{o}_{'on' if scene.get('onload', 0) == o else 'off'}.png", (x, y))
    for s, st in enumerate(scene["strips"]):
        if not st:
            continue
        x0, y0 = D.strip_x(s), D.STRIP_Y
        paste("strip_card.png", (x0, y0))
        live(im, (x0 + 8, y0 + 10, 168, 38), st["name"], 30, INK, warn=warn)
        live(im, (x0 + 10, y0 + 50, D.STRIP_W - 20, 24), st["state"], 22, DIM, warn=warn)
        for d, tag in enumerate(("in", "out")):
            live(im, (x0 + 10, y0 + D.RANGE_Y[d], 176, 22), st[f"{tag}_range"], 22, INK, "l", "Bold", warn)
            live(im, (x0 + 10, y0 + D.NAMES_Y[d], 176, 20), st[f"{tag}_names"], 20, DIM, "l", "Regular", warn)
            cx = x0 + D.COL_X[d]
            if st[f"{tag}_vis"] == 2:
                paste("dim.png", (cx - 4, y0 + D.FADER_Y - D.DIM_TOP))
                continue
            frame = round(st[f"{tag}_level"] / 100 * (D.FADER_FRAMES - 1))
            fader = A["fader.png"].crop((0, frame * D.FADER_H, D.COL_W, (frame + 1) * D.FADER_H))
            im.alpha_composite(fader.convert("RGBA"), (cx, y0 + D.FADER_Y))
            live(im, (cx, y0 + D.FADER_Y + D.FADER_H + 4, D.COL_W - 22, D.VALUE_H), str(st[f"{tag}_level"]), 34, INK,
                 warn=warn)
            paste(f"mute_{'on' if st[f'{tag}_mute'] else 'off'}.png", (cx, y0 + D.MUTE_Y))
        if scene.get("picker") == s:
            paste("popup_panel.png", (x0, y0 + D.POP_Y))
            rects, close = D.option_rects(s)
            for o, (x, y, w, h) in enumerate(rects):
                paste(f"opt_{o}_{'on' if o == st.get('kind', -1) else 'off'}.png", (x0 + x, y0 + y))
            c = A["close.png"]
            im.alpha_composite(c.convert("RGBA"), (x0 + close[0], y0 + close[1]))
    return im.convert("RGB")


SCENES = {
    "preview": dict(
        link="44.1 kHz | 26x26", presets=["Live", "Studio", "-", "-", "-", "-", "-", "-"], onload=1,
        strips=[
            dict(name="Mixer", state="running", in_range="IN 1-2", in_names="Main L, Main R", in_vis=1,
                 in_level=100, in_mute=0, out_range="OUT 3-4", out_names="Main L, Main R", out_vis=1,
                 out_level=72, out_mute=0, kind=10),
            dict(name="Valeton GP-150", state="running", in_range="IN 3-8", in_names="Out L, Out R, FX L, FX R",
                 in_vis=1, in_level=64, in_mute=1, out_range="OUT 5-8", out_names="Send 1, Send 2, Ret...",
                 out_vis=1, out_level=88, out_mute=0, kind=14),
            dict(name="Tracker", state="running", in_range="IN 9-20", in_names="Master L, Master R, Trk 1, Trk 2",
                 in_vis=1, in_level=100, in_mute=0, out_range="OUT 9-10", out_names="Main L, Main R", out_vis=1,
                 out_level=100, out_mute=0, kind=13),
            None, None, None]),
}


def previews(skin, dest):
    warn = []
    scene = SCENES["preview"]
    preview(skin, scene, warn).save(dest / "preview.png", optimize=True)
    picker = dict(scene, picker=1)
    picker["strips"] = [dict(s, kind=s["kind"]) if s else None for s in scene["strips"]]
    preview(skin, picker, warn).save(dest / "preview-picker.png", optimize=True)
    saving = dict(scene, save=True, pressed=None)
    preview(skin, saving, warn).save(dest / "preview-save.png", optimize=True)
    missing = dict(link="Pi not found", presets=["-"] * 8, strips=[None] * 6)
    preview(skin, missing, warn).save(dest / "preview-nopi.png", optimize=True)
    odd = dict(scene)
    odd["strips"] = [dict(scene["strips"][1], name="Mic preamp (USB audio)", state="waiting: USB budget", out_vis=2,
                          out_range="-", out_names="")] + [None] * 5
    preview(skin, odd, warn).save(dest / "preview-edge.png", optimize=True)
    return sorted(set(warn))


def main():
    out = pathlib.Path(sys.argv[1]).resolve()
    cfg = gen_vst.load(str(HERE / "vst.json"))
    gen_vst.check_lock(str(HERE), D.PARAMS)
    out.mkdir(parents=True, exist_ok=True)
    gen_vst.gen_params(cfg, D.PARAMS, str(out / "params.h"))
    (out / "pluginlist-entry.xml").write_text(gen_vst.entry(cfg) + "\n")
    (out / "params.json").write_text(json.dumps(D.PARAMS, indent=1) + "\n")
    v = int(cfg["version"])
    folder, skin = write_skin(out / "skin", f"{v // 1000}.{v % 1000 // 100}.{v % 100}.0")
    report = validate(skin)
    warn = previews(skin, out)
    print(f"skin: {report['components']} placed components, {report['defs']} definitions, {report['assets']} assets; "
          f"{len(D.PARAMS)} parameters; previews in {out}")
    for w in warn:
        print("preview note:", w)


if __name__ == "__main__":
    main()
