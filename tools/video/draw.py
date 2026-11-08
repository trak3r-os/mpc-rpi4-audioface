"""Drawing kit for the overview video: an antialiased 1920x1080 canvas with a transform stack, easing helpers,
animated cables with travelling signal pulses, and the device illustrations (all drawn here, no photos).

Everything is drawn at S times the output size and reduced, which gives smooth edges with plain Pillow.
Coordinates are "logical" pixels of a 1920x1080 frame; `Cv.at()` pushes a translate/scale/opacity so an
illustration can be drawn around (0, 0) and popped in at any position and size.
"""
import math
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, S = 1920, 1080, 2
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
ROOT = Path(__file__).resolve().parents[2]

PAPER, INK, MUTED, LINE, WHITE = "#f4f7fb", "#17304a", "#4d6178", "#cfdbe8", "#ffffff"
NIGHT, NAVY = "#10243a", "#17304a"
TEAL, BLUE, PURPLE, AMBER, RED, GREEN = "#0e9f8e", "#3b82f6", "#8b6fd6", "#e08a2e", "#d64545", "#22a06b"
IN_C, OUT_C, MIDI_C, CTRL_C, PINK = "#14b8a6", "#3b82f6", "#a855f7", "#f59e0b", "#ec4899"
CABLE, CABLE_EDGE = "#aebfd1", "#8497ad"


# ------------------------------------------------------------------------------------------------ easing

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def seg(t, a, b):
    """Progress 0..1 of time t through the window [a, b]."""
    return clamp((t - a) / (b - a)) if b > a else (1.0 if t >= a else 0.0)


def e_out(p):
    return 1 - (1 - clamp(p)) ** 3


def e_io(p):
    p = clamp(p)
    return p * p * (3 - 2 * p)


def e_back(p, s=1.7):
    """Ease-out with a small overshoot: 0 to 1, peaking near 1.1."""
    p = clamp(p)
    q = p - 1
    return 1 + (s + 1) * q ** 3 + s * q ** 2


def lerp(a, b, p):
    return a + (b - a) * p


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mix(c1, c2, a):
    """Colour c1 at opacity a over colour c2."""
    if a >= 0.999:
        return c1
    return "#%02x%02x%02x" % tuple(round(x * a + y * (1 - a)) for x, y in zip(rgb(c1), rgb(c2)))


# ------------------------------------------------------------------------------------------------ canvas

_PIC_CACHE = {}


class Cv:
    _fonts = {}

    def __init__(self, bg=PAPER):
        self.bg = bg
        self.im = Image.new("RGB", (W * S, H * S), bg)
        self.d = ImageDraw.Draw(self.im)
        self.ox = self.oy = 0.0
        self.k = 1.0
        self.a = 1.0

    # transform stack ------------------------------------------------------------------------------
    @contextmanager
    def at(self, x=0.0, y=0.0, s=1.0, a=1.0):
        saved = (self.ox, self.oy, self.k, self.a)
        self.ox += x * self.k
        self.oy += y * self.k
        self.k *= s
        self.a *= a
        try:
            yield self
        finally:
            self.ox, self.oy, self.k, self.a = saved

    def col(self, c):
        return mix(c, self.bg, self.a) if self.a < 0.999 else c

    def px(self, x, y):
        return ((self.ox + x * self.k) * S, (self.oy + y * self.k) * S)

    def lw(self, w):
        return max(1, round(w * self.k * S))

    # primitives -----------------------------------------------------------------------------------
    def rect(self, x0, y0, x1, y1, fill=None, outline=None, r=0, w=2):
        r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        (a, b), (c, d) = self.px(x0, y0), self.px(x1, y1)
        self.d.rounded_rectangle([a, b, c, d], r * self.k * S, fill=self.col(fill) if fill else None,
                                 outline=self.col(outline) if outline else None, width=self.lw(w))

    def circle(self, x, y, r, fill=None, outline=None, w=2):
        (a, b), (c, d) = self.px(x - r, y - r), self.px(x + r, y + r)
        self.d.ellipse([a, b, c, d], fill=self.col(fill) if fill else None,
                       outline=self.col(outline) if outline else None, width=self.lw(w))

    def arc(self, x, y, r, a0, a1, color, w=6):
        (a, b), (c, d) = self.px(x - r, y - r), self.px(x + r, y + r)
        self.d.arc([a, b, c, d], a0, a1, fill=self.col(color), width=self.lw(w))

    def poly(self, pts, fill):
        self.d.polygon([self.px(x, y) for x, y in pts], fill=self.col(fill))

    def line(self, pts, color, w=6, caps=True):
        P = [self.px(x, y) for x, y in pts]
        self.d.line(P, fill=self.col(color), width=self.lw(w), joint="curve")
        if caps:
            rr = w * self.k * S / 2
            for x, y in (P[0], P[-1]):
                self.d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=self.col(color))

    def font(self, size, bold=False, mono=False):
        key = (max(1, round(size)), bold, mono)
        if key not in Cv._fonts:
            name = ("DejaVuSansMono" if mono else "DejaVuSans") + ("-Bold" if bold else "") + ".ttf"
            Cv._fonts[key] = ImageFont.truetype(str(FONT_DIR / name), key[0])
        return Cv._fonts[key]

    def tw(self, s, size, bold=False, mono=False):
        """Width of a string in logical pixels at the given size (ignores the current scale)."""
        return self.font(size * S, bold, mono).getlength(s) / S

    def text(self, x, y, s, size=40, color=INK, bold=False, mono=False, anchor="la"):
        self.d.text(self.px(x, y), s, font=self.font(size * self.k * S, bold, mono), fill=self.col(color), anchor=anchor)

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

    def para(self, x, y, s, size=40, color=MUTED, maxw=600, bold=False, gap=1.32, anchor="la"):
        for line in self.wrap(s, size, maxw, bold):
            self.text(x, y, line, size, color, bold, anchor=anchor)
            y += size * gap
        return y

    def pill(self, cx, cy, s, size=40, fill=TEAL, color=WHITE, padx=28, bold=True):
        w = self.tw(s, size, bold) + 2 * padx
        h = size * 1.5
        self.rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, fill=fill, r=h / 2)
        self.text(cx, cy + size * 0.02, s, size, color, bold, anchor="mm")
        return w

    def card(self, x0, y0, x1, y1, fill=WHITE, edge=LINE, r=26):
        self.rect(x0 + 4, y0 + 8, x1 + 4, y1 + 8, fill=mix("#9fb3c8", self.bg, 0.22), r=r)
        self.rect(x0, y0, x1, y1, fill=fill, outline=edge, r=r, w=2)

    def pic(self, img, x, y, w, src=None, border=None, r=0, bw=5, cache=True):
        """Paste a PIL image with its top-left at (x, y), w logical pixels wide. Returns the height."""
        im = img.crop(src) if src else img
        h = w * im.height / im.width
        wp, hp = max(1, round(w * self.k * S)), max(1, round(h * self.k * S))
        key = (id(img), wp, hp)
        if cache and not src and key in _PIC_CACHE:
            rs = _PIC_CACHE[key]
        else:
            rs = im.resize((wp, hp), Image.Resampling.BICUBIC)
            if cache and not src:
                _PIC_CACHE[key] = rs
        X, Y = self.px(x, y)
        if self.a < 0.999:
            self.im.paste(rs, (round(X), round(Y)), Image.new("L", rs.size, int(255 * self.a)))
        else:
            self.im.paste(rs, (round(X), round(Y)))
        if border:
            self.d.rounded_rectangle([X - 1, Y - 1, X + wp + 1, Y + hp + 1], r * self.k * S, outline=self.col(border),
                                     width=self.lw(bw))
        return h

    def done(self):
        return self.im.reduce(S)


# ------------------------------------------------------------------------------------------------ cables

def rounded(pts, r, n=8):
    if len(pts) < 3 or r <= 0:
        return [tuple(p) for p in pts]
    pts = [pts[0]] + [q for k, q in enumerate(pts[1:], 1) if math.dist(q, pts[k - 1]) > 1e-6]
    if len(pts) < 3:
        return [tuple(q) for q in pts]
    out = [tuple(pts[0])]
    for i in range(1, len(pts) - 1):
        a, p, b = pts[i - 1], pts[i], pts[i + 1]
        la, lb = math.dist(a, p), math.dist(p, b)
        rr = min(r, la / 2, lb / 2)
        s = (p[0] + (a[0] - p[0]) * rr / la, p[1] + (a[1] - p[1]) * rr / la)
        e = (p[0] + (b[0] - p[0]) * rr / lb, p[1] + (b[1] - p[1]) * rr / lb)
        for j in range(n + 1):
            u = j / n
            out.append(((1 - u) ** 2 * s[0] + 2 * u * (1 - u) * p[0] + u * u * e[0],
                        (1 - u) ** 2 * s[1] + 2 * u * (1 - u) * p[1] + u * u * e[1]))
    out.append(tuple(pts[-1]))
    return out


def bezier(p0, p1, p2, p3, n=40):
    return [tuple((1 - u) ** 3 * a + 3 * u * (1 - u) ** 2 * b + 3 * u * u * (1 - u) * c + u ** 3 * d
                  for a, b, c, d in zip(p0, p1, p2, p3)) for u in (i / n for i in range(n + 1))]


class Path:
    """A polyline with rounded corners that knows its length and can be sampled."""

    def __init__(self, pts, r=40):
        self.p = pts if r is None else rounded(pts, r)
        self.cum = [0.0]
        for a, b in zip(self.p, self.p[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.L = self.cum[-1]

    def at(self, d):
        d = clamp(d, 0, self.L)
        for i in range(1, len(self.cum)):
            if self.cum[i] >= d:
                a, b = self.p[i - 1], self.p[i]
                seglen = max(1e-6, self.cum[i] - self.cum[i - 1])
                u = (d - self.cum[i - 1]) / seglen
                return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u,
                        (b[0] - a[0]) / seglen, (b[1] - a[1]) / seglen)
        x, y = self.p[-1]
        return x, y, 1.0, 0.0

    def upto(self, prog):
        d = self.L * clamp(prog)
        pts = [self.p[0]]
        for i in range(1, len(self.p)):
            if self.cum[i] <= d:
                pts.append(self.p[i])
            else:
                x, y, _, _ = self.at(d)
                pts.append((x, y))
                break
        return pts


def cable(c, path, prog=1.0, color=CABLE, edge=CABLE_EDGE, w=12):
    if prog <= 0.001:
        return
    pts = path.upto(prog)
    c.line(pts, edge, w + 5)
    c.line(pts, color, w)


def pulses(c, path, t, color, amp=1.0, prog=1.0, speed=300.0, gap=190.0, rev=False, r=11, off=0.0, glyph=None):
    """Signal dots travelling along a cable. rev flows from the end back to the start."""
    if amp <= 0.01 or prog < 0.999 and rev:
        return
    n = int(path.L // gap) + 2
    cyc = n * gap
    for i in range(n):
        d = (t * speed + i * gap) % cyc
        if d > path.L * prog:
            continue
        al = min(1.0, d / 50, (path.L * prog - d) / 50) * amp
        x, y, dx, dy = path.at(path.L - d if rev else d)
        x, y = x - dy * off, y + dx * off
        if glyph:
            c.text(x, y, glyph, 50, mix(color, c.bg, al), True, anchor="mm")
        else:
            c.circle(x, y, r * 2.1 * al, fill=mix(color, c.bg, 0.26 * al))
            c.circle(x, y, r * al, fill=color if al > 0.99 else mix(color, c.bg, al))


def ring(c, x, y, r, t, t0, color=CTRL_C, dur=0.9):
    p = seg(t, t0, t0 + dur)
    if 0 < p < 1:
        c.circle(x, y, r * (0.8 + 0.9 * e_out(p)), outline=mix(color, c.bg, 1 - p), w=7)


# ------------------------------------------------------------------------------------------------ illustrations
# Each draws around (0, 0) at scale 1; `t` is seconds for the little idle animations.

def knob(c, x, y, r, ang, body="#2b2f36", notch="#e2e8f0"):
    c.circle(x, y, r, fill=body, outline="#0e1218", w=2)
    c.line([(x + r * 0.25 * math.cos(ang), y + r * 0.25 * math.sin(ang)),
            (x + r * 0.85 * math.cos(ang), y + r * 0.85 * math.sin(ang))], notch, max(2, r * 0.2), caps=True)


WHITE_KEY_BLACK = (0, 1, 3, 4, 5)


def keys(c, x0, y0, x1, y1, t, n, press=True):
    """A strip of piano keys with one key animated."""
    kw = (x1 - x0) / n
    lit = int(t * 2.2) % n if press else -1
    for i in range(n):
        c.rect(x0 + i * kw, y0, x0 + (i + 1) * kw, y1, fill="#a7f3d0" if i == lit else "#f1f5f9", outline="#94a3b8", w=1)
    for i in range(n - 1):
        if i % 7 in WHITE_KEY_BLACK:
            c.rect(x0 + (i + 1) * kw - kw * 0.3, y0, x0 + (i + 1) * kw + kw * 0.3, y0 + (y1 - y0) * 0.6, fill="#1f2937", r=2)


def pi5(c, t=0.0):
    PCB, PCB_D, HOLE = "#23a05f", "#17794a", "#d9efe3"
    c.rect(-190, -125, 190, 125, PCB, PCB_D, r=18, w=4)
    for x, y in ((-166, -101), (166, -101), (-166, 101), (166, 101)):
        c.circle(x, y, 8, HOLE, PCB_D)
    c.rect(-120, -119, 100, -91, "#1b2733", r=4)
    for i in range(20):
        c.circle(-112 + i * 11, -111, 2.7, "#e7c35b")
        c.circle(-112 + i * 11, -99, 2.7, "#e7c35b")
    c.rect(-72, -36, 12, 44, "#c7d0d9", "#8b97a4", r=8, w=2)
    c.rect(-62, -26, 2, 34, "#9aa6b3", r=5)
    c.text(-30, 4, "Pi 5", 26, "#243447", True, anchor="mm")
    c.rect(44, -34, 98, 6, "#222d3a", r=4)
    c.rect(-132, -30, -88, 22, "#222d3a", r=4)
    c.rect(130, -118, 206, -60, "#c9d2db", "#8b97a4", r=6, w=2)
    c.rect(170, -108, 200, -70, "#1b2733", r=3)
    for y0, y1, wins in ((-46, 0, (-34, -12)), (10, 56, (22, 44))):
        c.rect(130, y0, 206, y1, "#c9d2db", "#8b97a4", r=6, w=2)
        for j, wy in enumerate(wins):
            c.rect(152, wy - 8, 204, wy + 8, "#2f6fd6" if j == 0 else "#1b2733", r=3)
    c.rect(-206, 44, -168, 76, "#c9d2db", "#8b97a4", r=12, w=2)
    c.rect(-200, 54, -174, 66, "#1b2733", r=5)
    c.circle(-150, 100, 5, "#ff4d4d")
    c.circle(-134, 100, 5, "#7CFC9A" if int(t * 4) % 3 else "#2b6b3c")


PI_USBC = (-206, 60)
PI_USB = (206, -34), (206, -12), (206, 22), (206, 44)


def laptop(c, t=0.0, screen=None):
    c.rect(-170, -120, 170, 70, "#2a3646", "#1a2330", r=16, w=3)
    c.rect(-156, -106, 156, 56, "#0f1b2a", r=6)
    if screen:
        screen(c)
    else:
        for i in range(22):
            h = 8 + 36 * (0.5 + 0.5 * math.sin(t * 3.2 + i * 0.7))
            c.rect(-138 + i * 12.5, 20 - h, -130 + i * 12.5, 20 + h * 0.2, fill=IN_C if i % 2 else OUT_C, r=3)
        c.circle(-140, -92, 4, "#ff6b6b")
        c.circle(-126, -92, 4, "#fbbf24")
        c.circle(-112, -92, 4, "#4ade80")
    c.rect(-206, 76, 206, 96, "#c7d0d9", "#9aa6b3", r=10, w=2)
    c.rect(-34, 76, 34, 84, "#9aa6b3", r=4)


def mixer(c, t=0.0):
    c.rect(-110, -85, 110, 85, "#3d5068", "#27384c", r=14, w=3)
    for i, x in enumerate((-75, -25, 25, 75)):
        knob(c, x, -52, 12, t * 0.6 + i, "#cbd5e1", "#27384c")
        c.rect(x - 4, -22, x + 4, 66, "#1d2a3a", r=4)
        y = 22 + 26 * math.sin(t * 1.7 + i * 1.3)
        c.rect(x - 14, y - 8, x + 14, y + 8, "#e2e8f0", "#94a3b8", r=4, w=1)
        c.circle(x, -78, 3, "#4ade80" if (int(t * 3) + i) % 3 else "#166534")


def pedal(c, t=0.0):
    c.rect(-80, -115, 80, 115, "#e08a2e", "#a8631a", r=20, w=3)
    c.rect(-56, -94, 56, -46, "#13202e", r=8)
    for i in range(9):
        h = 6 + 30 * (0.5 + 0.5 * math.sin(t * 4 + i))
        c.rect(-46 + i * 11, -50 - h, -40 + i * 11, -50, "#34d399" if h < 28 else "#fbbf24", r=1)
    for i, x in enumerate((-45, 0, 45)):
        knob(c, x, -6, 15, t * 0.5 + i * 2)
    c.circle(-45, 36, 5, "#ff3b30" if int(t * 2) % 2 else "#7f1d1d")
    c.circle(45, 36, 5, "#7f1d1d" if int(t * 2) % 2 else "#ff3b30")
    for x in (-38, 38):
        c.circle(x, 78, 24, "#cfd6de", "#8b97a4", w=3)


def synth(c, t=0.0):
    c.rect(-150, -78, 150, 78, "#5b4a99", "#3b2f6b", r=14, w=3)
    for i in range(6):
        knob(c, -118 + i * 28, -50, 10, t * 0.7 + i * 1.3, "#e9e4f8", "#3b2f6b")
    c.rect(34, -66, 136, -34, "#13202e", r=6)
    c.line([(40 + i * 5, -50 + 10 * math.sin(t * 5 + i * 0.5)) for i in range(18)], "#a7f3d0", 2.5, caps=False)
    keys(c, -138, 0, 138, 66, t, 10)


def tracker(c, t=0.0):
    c.rect(-100, -100, 100, 100, "#2f3b4d", "#1c2533", r=16, w=3)
    c.rect(-80, -86, 80, -46, "#0f1b2a", r=6)
    for i in range(7):
        c.rect(-70 + i * 21, -78, -56 + i * 21, -72 + 14 * ((i * 5 + int(t * 3)) % 3), "#38bdf8" if i % 2 else "#a78bfa", r=2)
    cols = ("#38bdf8", "#f472b6", "#fbbf24", "#34d399")
    for r_ in range(4):
        for k in range(4):
            lit = 0.5 + 0.5 * math.sin(t * 3 + r_ * 1.1 + k * 0.8)
            c.rect(-76 + k * 40, -28 + r_ * 40, -46 + k * 40, 2 + r_ * 40, fill=mix(cols[(r_ + k) % 4], "#2f3b4d", 0.35 + 0.65 * lit), r=5)


def midi_keys(c, t=0.0):
    c.rect(-170, -62, 170, 62, "#2b2f36", "#14171c", r=14, w=3)
    for i in range(4):
        lit = (int(t * 3) + i) % 4 == 0
        c.rect(-152 + (i % 2) * 30, -44 + (i // 2) * 30, -128 + (i % 2) * 30, -22 + (i // 2) * 30,
               "#fb7185" if lit else "#7f1d3a", r=4)
    knob(c, -128, 36, 9, t, "#475569")
    knob(c, -98, 36, 9, t * 0.8, "#475569")
    keys(c, -84, -50, 158, 50, t, 10)


def psu(c, t=0.0):
    c.rect(-60, -40, 60, 40, "#2b2f36", "#14171c", r=10, w=3)
    c.rect(60, -9, 92, 9, "#9aa6b3", r=4)
    c.text(0, 2, "5 V", 30, "#e2e8f0", True, anchor="mm")


def splitter(c, t=0.0):
    c.rect(-130, -70, 130, 70, "#374357", "#232d3d", r=14, w=3)
    for y in (-30, 30):
        c.rect(-142, y - 12, -118, y + 12, "#c9d2db", "#8b97a4", r=5, w=2)
    c.rect(118, -12, 142, 12, "#c9d2db", "#8b97a4", r=5, w=2)
    c.circle(-40, -40, 5, "#fbbf24")
    c.circle(-40, 40, 5, "#60a5fa")


SPLIT_L1, SPLIT_L2, SPLIT_R = (-142, -30), (-142, 30), (142, 0)


def speaker(c, t=0.0, play=1.0):
    c.rect(-50, -72, 50, 72, "#3d5068", "#27384c", r=14, w=3)
    c.circle(0, -30, 18, "#cbd5e1")
    c.circle(0, 26, 34, "#cbd5e1", "#27384c", w=3)
    c.circle(0, 26, 15 + 2 * play * math.sin(t * 9), "#27384c")
    for i in range(3):
        p = ((t * 0.9 + i / 3) % 1) * play
        if p > 0:
            c.arc(50, 0, 24 + 70 * p, -50, 50, mix(OUT_C, c.bg, 1 - p), 6)


def network(c, t=0.0):
    c.circle(0, 36, 9, "#3d5068")
    for i, r in enumerate((30, 56, 82)):
        lit = int(t * 2.2) % 4 > i
        c.arc(0, 36, r, 225, 315, "#3d5068" if lit else "#c3d0de", 11)


def oled_unit(c, t=0.0, img=None):
    c.rect(-340, -190, 340, 190, "#1b2a3a", "#0d1620", r=24, w=4)
    c.rect(-324, -164, 324, 164, "#02090d", r=6)
    if img is not None:
        c.pic(img, -320, -160, 640)


def encoder(c, t=0.0, ang=0.0):
    c.circle(0, 0, 72, "#c7d0d9", "#8b97a4", w=3)
    for i in range(24):
        a = i * math.pi / 12
        c.line([(66 * math.cos(a), 66 * math.sin(a)), (72 * math.cos(a), 72 * math.sin(a))], "#8b97a4", 3, caps=False)
    c.circle(0, 0, 52, "#2b2f36", "#0e1218", w=3)
    c.line([(26 * math.cos(ang), 26 * math.sin(ang)), (44 * math.cos(ang), 44 * math.sin(ang))], "#e2e8f0", 8)


def round_button(c, t=0.0, color="#e2e8f0"):
    c.circle(0, 0, 48, "#8b97a4")
    c.circle(0, -4, 44, color, "#8b97a4", w=3)


def force(c, t=0.0, jacks=None):
    """A generic pad-and-screen groovebox. jacks: None, 0 (own audio off) or 1 (add-on active)."""
    c.rect(-270, -170, 270, 170, "#15181d", "#07090c", r=24, w=4)
    c.rect(-246, -148, 246, -34, "#0e2740", "#1e3a5a", r=8, w=2)
    cols = ("#38bdf8", "#f472b6", "#fbbf24", "#34d399", "#a78bfa")
    for i in range(10):
        for j in range(3):
            lit = 0.55 + 0.45 * math.sin(t * 2 + i * 0.7 + j)
            c.rect(-232 + i * 46, -134 + j * 33, -196 + i * 46, -110 + j * 33, mix(cols[(i + j) % 5], "#0e2740", lit), r=3)
    for r_ in range(4):
        for k in range(8):
            lit = 0.5 + 0.5 * math.sin(t * 2.6 + r_ * 1.3 + k * 0.9)
            c.rect(-230 + k * 58, -16 + r_ * 38, -184 + k * 58, 16 + r_ * 38, mix(cols[(r_ * 3 + k) % 5], "#15181d", 0.3 + 0.6 * lit), r=5)
    if jacks is not None:
        for x in (-160, -110, -60, -10, 70):          # outputs and headphones, bottom edge
            c.circle(x, 170, 12, "#3b4350" if jacks == 0 else TEAL, "#07090c", w=2)
        for x in (-30, 30):                           # inputs, top edge
            c.circle(x, -170, 12, "#3b4350" if jacks == 0 else IN_C, "#07090c", w=2)


FORCE_OUT_X, FORCE_HP_X, FORCE_IN_X = (-160, -110, -60, -10), 70, (-30, 30)


# ------------------------------------------------------------------------------------------------ helpers shared by scenes

def show(c, fn, x, y, t, t0, s=1.0, bob=0.0, dur=0.6, a=1.0, **kw):
    """Pop an illustration in at t0 with a little overshoot, then let it bob. Returns its progress."""
    p = seg(t, t0, t0 + dur)
    if p <= 0:
        return 0.0
    yy = y + (bob * math.sin(t * 1.8 + x * 0.01) if p >= 1 else 0)
    with c.at(x, yy, s * max(0.02, e_back(p)), clamp(p * 3) * a):
        fn(c, t, **kw)
    return p


def fade_text(c, x, y, s, t, t0, size=40, color=INK, bold=True, anchor="ma", rise=14):
    p = e_out(seg(t, t0, t0 + 0.5))
    if p > 0:
        with c.at(0, rise * (1 - p), 1, p):
            c.text(x, y, s, size, color, bold, anchor=anchor)


def typed(s, t, t0, cps=24.0):
    return s[:int(max(0.0, t - t0) * cps)]


def terminal(c, x0, y0, x1, y1):
    c.rect(x0, y0, x1, y1, "#0d1a2a", "#0d1a2a", r=22)
    for i, col in enumerate(("#ff6b6b", "#fbbf24", "#4ade80")):
        c.circle(x0 + 34 + i * 30, y0 + 30, 9, col)
