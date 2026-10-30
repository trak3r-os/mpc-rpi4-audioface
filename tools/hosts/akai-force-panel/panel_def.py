# SPDX-License-Identifier: GPL-3.0-or-later
"""Single source for the panel's parameter list, page geometry and Q-Link maps.

The parameter order mirrors src/panel_layout.h (saved projects and Q-Link maps bind by index: append only).
tests/unit.cpp compares the generated params.h with that header, so a drift fails the build.
"""

STRIPS, PRESETS = 6, 8
KINDS = ["Default", "Guitar", "Bass", "Synth", "Keys", "Drums", "Drum machine", "Sampler", "Vocal", "Mic",
         "Mixer", "Line", "FX", "Tracker", "Custom"]          # "Custom" is readback only (no button)
FIELDS = ["name", "state", "present", "in_vis", "out_vis", "in_range", "in_names", "in_level", "in_mute",
          "out_range", "out_names", "out_level", "out_mute", "kind", "kind__open"]


def text(key, name):
    return {"key": key, "name": name, "min": 0, "max": 1, "default": 0, "display": "string"}


def level(key, name):
    return {"key": key, "name": name, "min": 0, "max": 100, "default": 100, "unit": "%", "display": "int"}


def enum(key, name, options, **kw):
    return {"key": key, "name": name, "options": options, "default": 0, **kw}


def parameters():
    p = [text("link", "Link")]
    p += [{"key": f"preset_{k}", "name": f"Preset {k}", "min": 0, "max": 1, "default": 0, "momentary": True,
           "hold_ms": 150} for k in range(1, PRESETS + 1)]
    p += [text(f"preset_name_{k}", f"Preset {k} Name") for k in range(1, PRESETS + 1)]
    p += [enum("save", "Save", ["Off", "On"]),
          enum("onload", "On Project Load", ["None"] + [f"Preset {k}" for k in range(1, PRESETS + 1)])]
    for s in range(1, STRIPS + 1):
        n = f"S{s}"
        p += [text(f"s{s}_name", f"{n} Name"), text(f"s{s}_state", f"{n} State"),
              enum(f"s{s}_present", f"{n} Present", ["No", "Yes"]),
              enum(f"s{s}_in_vis", f"{n} IN Shown", ["Hidden", "Shown", "Dimmed"]),
              enum(f"s{s}_out_vis", f"{n} OUT Shown", ["Hidden", "Shown", "Dimmed"]),
              text(f"s{s}_in_range", f"{n} IN Range"), text(f"s{s}_in_names", f"{n} IN Names"),
              level(f"s{s}_in_level", f"{n} IN Level"), enum(f"s{s}_in_mute", f"{n} IN Mute", ["Off", "On"]),
              text(f"s{s}_out_range", f"{n} OUT Range"), text(f"s{s}_out_names", f"{n} OUT Names"),
              level(f"s{s}_out_level", f"{n} OUT Level"), enum(f"s{s}_out_mute", f"{n} OUT Mute", ["Off", "On"]),
              enum(f"s{s}_kind", f"{n} Type", KINDS),
              enum(f"s{s}_kind__open", f"{n} Type List", ["Closed", "Open"], popup_of=f"s{s}_kind")]
    return p


PARAMS = parameters()
INDEX = {p["key"]: i for i, p in enumerate(PARAMS)}
assert len(PARAMS) == 19 + STRIPS * len(FIELDS)

# Q-Links: bank 1 = IN levels of strips 1-6 and OUT levels of strips 1-2; bank 2 = OUT levels of strips 3-6
# and the IN mutes of strips 1-4. Slot k is the k-th knob of the 16 (two banks of 8).
QLINK_KEYS = ([f"s{s}_in_level" for s in range(1, 7)] + [f"s{s}_out_level" for s in (1, 2)] +
              [f"s{s}_out_level" for s in range(3, 7)] + [f"s{s}_in_mute" for s in range(1, 5)])
assert len(QLINK_KEYS) == 16

# ---- geometry (canvas 1280 x 628) ----------------------------------------------------------------------
W, H = 1280, 628
STRIP_X0, STRIP_W, STRIP_GAP, STRIP_Y, STRIP_H = 32, 196, 8, 104, 440
COL_X = (8, 104)           # IN / OUT fader columns inside a strip
COL_W = 84
HEAD = dict(link=(80, 56, 232, 24), presets_x=340, presets_y=30, preset_w=92, preset_h=56, preset_gap=8,
            save=(1148, 30, 108, 56))
FOOT_Y, FOOT_H = 562, 52
FADER_Y, FADER_H, FADER_FRAMES = 190, 158, 64
DIM_TOP = 20               # the dimming overlay starts this far above the fader (it covers the IN/OUT tag)
VALUE_Y, VALUE_H = 352, 34     # strip-local y of the value label, below the fader
MUTE_Y, MUTE_H = 390, 42
RANGE_Y = (82, 128)        # IN / OUT range rows (strip-local y), height 22
NAMES_Y = (104, 150)       # IN / OUT channel-name rows, height 20
POP_Y, POP_H = 52, 372
OPT_W, OPT_H, OPT_GAP = 88, 38, 6


def strip_x(s):
    return STRIP_X0 + s * (STRIP_W + STRIP_GAP)


def preset_x(k):
    return HEAD["presets_x"] + k * (HEAD["preset_w"] + HEAD["preset_gap"])


ONLOAD_X0 = 232
ONLOAD_BOX = dict(none=(84, 40), num=(52, 40), gap=6)


def onload_rects():
    """[(x, y, w, h)] for None, 1..8."""
    out, x = [], ONLOAD_X0
    for o in range(PRESETS + 1):
        w = ONLOAD_BOX["none"][0] if o == 0 else ONLOAD_BOX["num"][0]
        out.append((x, FOOT_Y + 6, w, ONLOAD_BOX["none"][1]))
        x += w + ONLOAD_BOX["gap"]
    return out


def option_rects(s):
    """(x, y, w, h) of the 14 type buttons, 2 columns x 7, in strip-local coordinates, then the close button."""
    rects = []
    for o in range(len(KINDS) - 1):
        col, row = o % 2, o // 2
        rects.append((8 + col * (OPT_W + 4), POP_Y + 8 + row * (OPT_H + OPT_GAP), OPT_W, OPT_H))
    close = (8, POP_Y + 8 + 7 * (OPT_H + OPT_GAP), 2 * OPT_W + 4, 40)
    return rects, close
