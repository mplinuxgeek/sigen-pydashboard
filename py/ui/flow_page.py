"""Flow tab: solar, grid, battery and home drawn as four rings joined by the flows between them, in three views:
Now (live power, with dots moving along the active flows), Today (energy since midnight) and Month (energy over the
billing period). The split of energy between the rings comes from core/flows.py; this file only draws it."""
import asyncio
import math

import lvgl as lv

from core import flows, timeutil as T, tz
from . import common as C, kit

SOL, HOME, GRID_IN, GRID_OUT, BATT, DIS = 0xFBBF24, 0x2DD4BF, 0x818CF8, 0xC084FC, 0x22C55E, 0xEF4444
IDLE, RING_BG = 0x1E293B, 0x0B1220
MODES = ("Now", "Today", "Month")
LINE_MIN, LINE_MAX = 3, 12
DOT = 10
SPEED_PX, ANIM_MS = 9, 120
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _rgb(v):
    return kit.rgb(v)


def _rect(parent, x, y, w, h, color, radius=0):
    o = lv.obj(parent)
    o.remove_style_all()
    o.set_pos(x, y)
    o.set_size(w, h)
    o.set_style_bg_color(_rgb(color), 0)
    o.set_style_bg_opa(lv.OPA.COVER, 0)
    o.set_style_radius(radius, 0)
    o.remove_flag(lv.obj.FLAG.SCROLLABLE)
    o.remove_flag(lv.obj.FLAG.CLICKABLE)
    return o


def _rot_rect(parent, cx, cy, w, h, deg, color):
    """Small icon part: a w x h bar centred on (cx, cy), rotated by deg."""
    o = _rect(parent, cx - w // 2, cy - h // 2, w, h, color)
    o.set_style_transform_pivot_x(w // 2, 0)
    o.set_style_transform_pivot_y(h // 2, 0)
    o.set_style_transform_rotation(int(deg * 10), 0)
    return o


def draw_sun(parent, cx, cy, color):
    for deg in (0, 45, 90, 135):
        _rot_rect(parent, cx, cy, 3, 28, deg, color)
    ring = _rect(parent, cx - 9, cy - 9, 18, 18, RING_BG, 9)              # clear gap between the rays and the core
    _rect(parent, cx - 6, cy - 6, 12, 12, color, 6)
    return ring


def draw_pylon(parent, cx, cy, color):
    _rect(parent, cx - 13, cy - 13, 26, 3, color)                             # top arm
    _rect(parent, cx - 8, cy - 5, 16, 3, color)                               # second arm
    _rot_rect(parent, cx - 6, cy + 4, 3, 28, 12, color)                       # legs
    _rot_rect(parent, cx + 6, cy + 4, 3, 28, -12, color)
    _rect(parent, cx - 1, cy - 13, 3, 10, color)                              # spire


class Edge:
    """One flow line: thin track when idle, coloured and thicker when energy moves, with a value pill and travelling dots."""

    def __init__(self, parent, steps, label_at):
        # steps in travel order: ("l", x0, y0, x1, y1) straight (horizontal or vertical) | ("a", cx, cy, r, from_deg, to_deg)
        self.steps = steps
        self.parts = []
        self.path = []
        for s in steps:
            if s[0] == "l":
                o = _rect(parent, 0, 0, 1, 1, IDLE)
            else:
                o = lv.arc(parent)
                o.remove_style_all()
                o.remove_flag(lv.obj.FLAG.CLICKABLE)
                o.set_style_arc_width(0, lv.PART.INDICATOR)
                o.set_style_arc_rounded(False, lv.PART.MAIN)
                o.set_rotation(0)
            self.parts.append(o)
            self._extend_path(s)
        self.cum = [0.0]
        for i in range(1, len(self.path)):
            (x0, y0), (x1, y1) = self.path[i - 1], self.path[i]
            self.cum.append(self.cum[-1] + math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2))
        self.length = self.cum[-1]
        self.pill = lv.label(parent)
        self.pill.set_style_text_font(kit.font(14), 0)
        self.pill.set_style_bg_color(_rgb(RING_BG), 0)
        self.pill.set_style_bg_opa(lv.OPA._90, 0)
        self.pill.set_style_radius(8, 0)
        self.pill.set_style_pad_hor(6, 0)
        self.pill.set_style_pad_ver(1, 0)
        self.pill.set_text("")
        self.pill.add_flag(lv.obj.FLAG.HIDDEN)
        self.label_at = label_at
        self.dots = []
        for _ in range(3):
            d = _rect(parent, 0, 0, DOT, DOT, SOL, DOT // 2)
            d.add_flag(lv.obj.FLAG.HIDDEN)
            self.dots.append(d)
        self.active = False
        self.reverse = False
        self.paint(IDLE, LINE_MIN, 0)

    def _extend_path(self, s):
        if s[0] == "l":
            pts = [(s[1], s[2]), (s[3], s[4])]
        else:
            _k, cx, cy, r, a0, a1 = s
            n = max(2, abs(a1 - a0) // 10)
            pts = [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
                   for i in range(n + 1)]
        self.path.extend(pts if not self.path else pts[1:])

    def paint(self, color, w, ndots):
        w = int(w)
        for s, o in zip(self.steps, self.parts):
            if s[0] == "l":
                x0, y0, x1, y1 = s[1:]
                if y0 == y1:
                    o.set_pos(min(x0, x1), y0 - w // 2)
                    o.set_size(abs(x1 - x0) + 1, w)
                else:
                    o.set_pos(x0 - w // 2, min(y0, y1))
                    o.set_size(w, abs(y1 - y0) + 1)
                o.set_style_bg_color(_rgb(color), 0)
            else:
                _k, cx, cy, r, a0, a1 = s
                d = 2 * r + w
                o.set_size(d, d)
                o.set_pos(cx - r - w // 2, cy - r - w // 2)
                o.set_bg_angles(min(a0, a1), max(a0, a1))
                o.set_style_arc_width(w, lv.PART.MAIN)
                o.set_style_arc_color(_rgb(color), lv.PART.MAIN)
        self.active = ndots > 0
        for i, dot in enumerate(self.dots):
            if i < ndots:
                dot.set_style_bg_color(_rgb(color), 0)
                dot.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                dot.add_flag(lv.obj.FLAG.HIDDEN)

    def set_text(self, text, color):
        if not text:
            self.pill.add_flag(lv.obj.FLAG.HIDDEN)
            return
        self.pill.set_text(text)
        self.pill.set_style_text_color(_rgb(color), 0)
        self.pill.remove_flag(lv.obj.FLAG.HIDDEN)
        self.pill.update_layout()
        self.pill.set_pos(self.label_at[0] - self.pill.get_width() // 2, self.label_at[1] - self.pill.get_height() // 2)

    def point_at(self, s):
        """Position `s` pixels along the path (from the far end when reversed)."""
        if self.reverse:
            s = self.length - s
        s = max(0.0, min(s, self.length))
        i = 1
        while i < len(self.cum) - 1 and self.cum[i] < s:
            i += 1
        seg = self.cum[i] - self.cum[i - 1] or 1.0
        f = (s - self.cum[i - 1]) / seg
        (x0, y0), (x1, y1) = self.path[i - 1], self.path[i]
        return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f

    def move_dots(self, phase):
        n = sum(1 for d in self.dots if not d.has_flag(lv.obj.FLAG.HIDDEN))
        for k in range(n):
            x, y = self.point_at((phase + k * self.length / n) % self.length)
            self.dots[k].set_pos(int(x) - DOT // 2, int(y) - DOT // 2)


class Node:
    """A ring with an icon, up to two value lines inside and a name beside it."""

    def __init__(self, parent, cx, cy, R, color, name, icon, name_at):
        self.R = R
        ring = self.ring = lv.obj(parent)
        ring.remove_style_all()
        ring.set_pos(cx - R, cy - R)
        ring.set_size(2 * R, 2 * R)
        ring.set_style_radius(lv.RADIUS_CIRCLE, 0)
        ring.set_style_bg_color(_rgb(RING_BG), 0)
        ring.set_style_bg_opa(lv.OPA.COVER, 0)
        ring.set_style_border_color(_rgb(color), 0)
        ring.set_style_border_width(4, 0)
        ring.set_style_border_opa(lv.OPA.COVER, 0)
        ring.remove_flag(lv.obj.FLAG.SCROLLABLE)
        ring.remove_flag(lv.obj.FLAG.CLICKABLE)
        self.icon_color = color
        self.icon = None
        c = R - 4                                          # centre in the ring's content box (the border takes 4 px)
        if icon == "sun":
            draw_sun(ring, c, c - 26, color)
        elif icon == "pylon":
            draw_pylon(ring, c, c - 24, color)
        else:
            self.icon = kit.label(ring, c, c - 40, kit.CENTER, kit.font(24), color, icon, 2 * R - 12)
        self.l1 = kit.label(ring, c, c - 8, kit.CENTER, kit.font(18), kit.TITLE, "--", 2 * R - 12)
        self.l2 = kit.label(ring, c, c + 16, kit.CENTER, kit.font(16), kit.LABEL, "", 2 * R - 12)
        for lbl in (self.l1, self.l2):
            lbl.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        self.name = kit.label(parent, name_at[0], name_at[1], name_at[2], kit.font(16), kit.LABEL, name, 120)
        self.name.set_style_text_letter_space(2, 0)

    def set(self, l1, c1, l2="", c2=kit.LABEL):
        kit.set_text(self.l1, l1, c1)
        kit.set_text(self.l2, l2, c2)


class FlowPage:
    def __init__(self, parent, app, shell):
        import board
        self.app, self.parent, self.shell = app, parent, shell
        self.W, self.H = board.W, board.H
        self.portrait = board.portrait
        self.mode = 0
        self.active = False
        self.phase = 0
        self.timer = self.anim = None
        self.cache = {}                                    # mode -> (key, totals)
        self.busy = False
        self.vals = None
        parent.set_style_bg_color(C.c(C.BG), 0)
        parent.set_style_bg_opa(lv.OPA.COVER, 0)
        parent.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.build_header()
        self.build_diagram()
        self.note = kit.label(parent, 12, self.H - 26, kit.LEFT, kit.font(14), kit.LABEL, "", self.W - 24)

    # ---- layout --------------------------------------------------------------------------------------
    def build_header(self):
        p = self.parent
        head = lv.obj(p)
        head.remove_style_all()
        head.set_pos(0, 0)
        head.set_size(self.W, 52)
        head.set_style_pad_hor(10, 0)
        head.set_flex_flow(lv.FLEX_FLOW.ROW)
        head.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        head.remove_flag(lv.obj.FLAG.SCROLLABLE)
        C.label(head, "Energy Flow", 24, C.TEXT)
        row = lv.obj(head)
        row.remove_style_all()
        row.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_style_pad_column(6 if self.portrait else 8, 0)
        self.mode_btns = []
        for i, name in enumerate(MODES):
            b = C.button(row, name, C.CARD, C.TEXT, lambda i=i: self.set_mode(i), h=38)
            if self.portrait:
                b.set_style_pad_hor(10, 0)
            self.mode_btns.append(b)
        self.paint_buttons()

    def paint_buttons(self):
        for i, b in enumerate(self.mode_btns):
            on = i == self.mode
            b.set_style_bg_color(C.c(C.ACCENT if on else C.CARD), 0)
            b.get_child(0).set_style_text_color(C.c(C.ACCENT_TEXT if on else C.TEXT), 0)

    def build_diagram(self):
        p, W, H = self.parent, self.W, self.H
        R = 52 if self.portrait else 56
        cx = W // 2
        top = 56
        sy, by_ = top + R + 2, H - R - 34
        gy = (sy + by_) // 2
        gx, hx = R + (10 if self.portrait else 14), W - R - (10 if self.portrait else 14)
        dx = int(R * 0.72)
        ytop, ybot = gy - 20, gy + 20
        rdy = int(math.sqrt(R * R - dx * dx))
        r = int(min(72, ytop - (sy + rdy) - 14, cx - dx - (gx + R) - 26))
        self.geo = (cx, sy, by_, gy, gx, hx, R)
        E = {}
        mid = lambda a, b: (a + b) // 2                                             # noqa: E731
        lab = {}
        if self.portrait:                         # short horizontal runs: put the value pills on the long vertical ones
            top_y = int((sy + rdy - 6) + ((ytop - r) - (sy + rdy - 6)) * 0.4)
            low0, low1 = ybot + r, by_ - rdy + 6
            low_y = int(low0 + (low1 - low0) * 0.55)
            lab = {"sh": (cx + dx, top_y), "sg": (cx - dx, top_y), "gb": (cx - dx, low_y), "bh": (cx + dx, low_y),
                   "sb": (cx, int(sy + R + (by_ - R - sy - R) * 0.3))}
        # lines first so the rings sit on top of their ends
        E["sh"] = Edge(p, [("l", cx + dx, sy + rdy - 6, cx + dx, ytop - r), ("a", cx + dx + r, ytop - r, r, 180, 90),
                           ("l", cx + dx + r, ytop, hx - R + 6, ytop)], lab.get("sh", (mid(cx + dx + r, hx - R), ytop)))
        E["sg"] = Edge(p, [("l", cx - dx, sy + rdy - 6, cx - dx, ytop - r), ("a", cx - dx - r, ytop - r, r, 0, 90),
                           ("l", cx - dx - r, ytop, gx + R - 6, ytop)], lab.get("sg", (mid(gx + R, cx - dx - r), ytop)))
        E["sb"] = Edge(p, [("l", cx, sy + R - 6, cx, by_ - R + 6)], lab.get("sb", (cx, mid(sy + R, ytop - 8))))
        E["gh"] = Edge(p, [("l", gx + R - 6, gy, hx - R + 6, gy)], (mid(gx + R, cx - dx - r) + 22, gy))
        E["gb"] = Edge(p, [("l", gx + R - 6, ybot, cx - dx - r, ybot), ("a", cx - dx - r, ybot + r, r, 270, 360),
                           ("l", cx - dx, ybot + r, cx - dx, by_ - rdy + 6)], lab.get("gb", (mid(gx + R, cx - dx - r), ybot)))
        E["bh"] = Edge(p, [("l", cx + dx, by_ - rdy + 6, cx + dx, ybot + r), ("a", cx + dx + r, ybot + r, r, 180, 270),
                           ("l", cx + dx + r, ybot, hx - R + 6, ybot)], lab.get("bh", (mid(cx + dx + r, hx - R), ybot)))
        E["bg"] = E["gb"]                                                           # same line, other direction
        self.edges = E
        self.n_solar = Node(p, cx, sy, R, SOL, "SOLAR", "sun", (cx + R + 10, sy - 10, kit.LEFT))
        self.n_grid = Node(p, gx, gy, R, GRID_IN, "GRID", "pylon", (gx, gy + R + 6, kit.CENTER))
        self.n_home = Node(p, hx, gy, R, HOME, "HOME", lv.SYMBOL.HOME, (hx, gy + R + 6, kit.CENTER))
        self.n_batt = Node(p, cx, by_, R, BATT, "BATTERY", lv.SYMBOL.BATTERY_FULL, (cx + R + 10, by_ - 10, kit.LEFT))

    # ---- data ----------------------------------------------------------------------------------------
    def set_mode(self, i):
        if i == self.mode:
            return
        self.mode = i
        self.paint_buttons()
        self.refresh()

    def on_show(self):
        self.active = True
        self.refresh()
        if self.timer is None:
            self.timer = lv.timer_create(lambda t: self.refresh(), 3000, None)
            self.anim = lv.timer_create(lambda t: self.step(), ANIM_MS, None)
        self.timer.resume()
        self.anim.resume()

    def on_hide(self):
        self.active = False
        if self.timer:
            self.timer.pause()
            self.anim.pause()

    def period(self):
        """(start, end) unix seconds for the cumulative views."""
        now = T.unix_now()
        if self.mode == 1:
            return tz.day_start(now), now + 1
        m = self.app.services.get("monthly")
        return (m.billing_start_epoch() if m else None) or tz.day_start(now), now + 1

    def refresh(self):
        if not self.active:
            return
        if self.mode == 0:
            self.show_live()
            return
        h = self.app.services["history"]
        key = (self.mode, h.rev, h.n, tz.day_start(T.unix_now()))
        hit = self.cache.get(self.mode)
        if hit and hit[0] == key:
            self.show_energy(hit[1])
            return
        if hit:
            self.show_energy(hit[1])                       # stale numbers beat a blank screen while the new ones are worked out
        else:
            self.note.set_text("Adding up the history...")
        if not self.busy and T.clock_valid() and h.n:
            self.busy = True
            asyncio.create_task(self.compute(self.mode, key))

    async def compute(self, mode, key):
        try:
            t0, t1 = self.period()
            res = await flows.totals(self.app.services["history"], t0, t1)
            res["t0"] = t0
            self.cache[mode] = (key, res)
        finally:
            self.busy = False
        if self.active and self.mode == mode:
            self.show_energy(res)

    def show_live(self):
        s = self.app.services["state"]
        g = s.get
        if s.last_commit_ms is None:
            self.note.set_text("Waiting for the first reading from the inverter...")
        else:
            self.note.set_text("Live power. Lines widen and dots move with the flow.")
        pv, load, batt, grid = g("pv_power", 0.0), g("load_power", 0.0), g("batt_power", 0.0), g("grid_power", 0.0)
        e = flows.split(pv, load, batt, grid)
        n = flows.nodes(pv, load, batt, grid)
        dec = self.app.settings.get("ui.kw_dec", 2) == 1 and 1 or 2
        kw = lambda v: "%.*f kW" % (dec, v)                                        # noqa: E731
        soc = g("soc")
        self.n_solar.set(kw(n["solar"]), SOL if n["solar"] > 0.05 else kit.LABEL)
        self.n_home.set(kw(n["home"]), HOME)
        if n["g_out"] > 0.05:
            self.n_grid.set(kw(n["g_out"]), GRID_OUT, "exporting", GRID_OUT)
        elif n["g_in"] > 0.05:
            self.n_grid.set(kw(n["g_in"]), GRID_IN, "importing", GRID_IN)
        else:
            self.n_grid.set(kw(0), kit.LABEL, "idle")
        sub = "" if soc is None else "%.0f%%" % soc
        if n["b_in"] > 0.05:
            self.n_batt.set("+" + kw(n["b_in"]), BATT, sub, kit.LABEL)
        elif n["b_out"] > 0.05:
            self.n_batt.set("-" + kw(n["b_out"]), DIS, sub, kit.LABEL)
        else:
            self.n_batt.set(kw(0), kit.LABEL, sub, kit.LABEL)
        self.set_battery_icon(soc)
        inv = float(self.app.settings.get("sizing.inverter_kw", 25.0))
        self.apply(e, inv, 0.05, lambda v: "%.1f kW" % v, True)

    def show_energy(self, t):
        t0 = t.get("t0") or 0
        loc = tz.local(t0) if t0 else None
        what = "Today so far" if self.mode == 1 else "Billing period"
        if loc and self.mode == 2:
            what += " since %d %s" % (loc[2], MONTHS[loc[1] - 1])
        self.note.set_text("%s, energy in kWh (%d readings)" % (what, t.get("samples", 0)))
        f = lambda v: "%.*f" % (0 if v >= 100 else 1, v)                           # noqa: E731
        self.n_solar.set(f(t["solar"]) + " kWh", SOL)
        self.n_home.set(f(t["home"]) + " kWh", HOME)
        self.n_grid.set("In " + f(t["g_in"]), GRID_IN, "Out " + f(t["g_out"]), GRID_OUT)
        self.n_batt.set("+" + f(t["b_in"]), BATT, "-" + f(t["b_out"]), DIS)
        self.set_battery_icon(None)
        top = max([t[k] for k in flows.EDGES] + [0.5])
        self.apply({k: t[k] for k in flows.EDGES}, top, 0.05, lambda v: f(v), False)

    def set_battery_icon(self, soc):
        if self.n_batt.icon is None:
            return
        sym = lv.SYMBOL.BATTERY_FULL
        if soc is not None:
            sym = (lv.SYMBOL.BATTERY_EMPTY if soc < 10 else lv.SYMBOL.BATTERY_1 if soc < 35 else lv.SYMBOL.BATTERY_2 if soc < 60
                   else lv.SYMBOL.BATTERY_3 if soc < 85 else lv.SYMBOL.BATTERY_FULL)
        kit.set_text(self.n_batt.icon, sym, BATT)

    def apply(self, e, vmax, floor, fmt, moving):
        """Paint the six flows. e: edge values, vmax: what a full-width line means, moving: draw travelling dots."""
        E = self.edges
        colors = {"sh": SOL, "sb": SOL, "sg": SOL, "gh": GRID_IN, "gb": GRID_IN, "bg": BATT, "bh": BATT}
        gb_rev = e["bg"] > e["gb"]
        pairs = {"sh": e["sh"], "sg": e["sg"], "sb": e["sb"], "gh": e["gh"], "bh": e["bh"], "gb": max(e["gb"], e["bg"])}
        for name, v in pairs.items():
            edge = E[name]
            if v >= floor:
                col = BATT if (name == "gb" and gb_rev) else colors[name]
                w = LINE_MIN + (LINE_MAX - LINE_MIN) * math.sqrt(min(v / vmax, 1.0)) if vmax > 0 else LINE_MIN
                edge.reverse = name == "gb" and gb_rev
                edge.paint(col, w, (1 if w < 6 else 2 if w < 9 else 3) if moving else 0)
                edge.set_text(fmt(v), col)
            else:
                edge.reverse = False
                edge.paint(IDLE, LINE_MIN, 0)
                edge.set_text("", IDLE)

    def step(self):
        """Advance the dots (Now view only; they stay hidden otherwise)."""
        if not self.active or self.mode != 0:
            return
        self.phase = (self.phase + SPEED_PX) % 100000
        for name in ("sh", "sb", "sg", "gh", "gb", "bh"):
            e = self.edges[name]
            if e.active:
                e.move_dots(self.phase)
