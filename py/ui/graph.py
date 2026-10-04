"""Graph tab: one midnight-to-midnight chart of battery SOC (left axis, %) with solar / load / grid import / grid
export power (right axis, kW), paged back through the history. Landscape layout of history_ui.c."""
from array import array

import lvgl as lv

from core import timeutil as T, tz
from . import common as C, kit

DAY_SLOTS = 24 * 3600 // 300
MAX_DAY_OFFSET = 30
NONE = 0x7FFFFFFF

C_BATT, C_SOLAR, C_LOAD, C_IMP, C_EXP = 0x02D001, 0xFF9800, 0x4DB6AD, 0xDC4646, 0xA280DB
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def bisect_left(arr, n, x):
    """First index in the first n (ascending) entries of arr with arr[i] >= x."""
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def join_gaps(vals, tss):
    """Linearly bridge runs of missing 5-minute slots between two real samples."""
    left = None
    for right in range(len(vals)):
        if vals[right] == NONE:
            continue
        if left is not None and right - left > 1 and tss[right] > tss[left]:
            v0, v1, span = vals[left], vals[right], right - left
            for k in range(left + 1, right):
                vals[k] = v0 + (v1 - v0) * (k - left) // span
        left = right


class GraphPage:
    def __init__(self, parent, app, shell):
        self.app, self.parent, self.shell = app, parent, shell
        self.tip_timer = None
        self.offset = 0
        self.hist_rev = -1
        self.built_key = None
        self._keep = []
        parent.set_style_bg_color(C.c(C.BG), 0)
        parent.set_style_bg_opa(lv.OPA.COVER, 0)
        parent.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        parent.set_style_pad_all(10, 0)
        parent.set_style_pad_row(6, 0)
        parent.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.busy = False

    def on_show(self):
        self.offset = 0
        self.refresh()

    def refresh(self):
        """Rebuild only when something the chart shows has changed (day, new history samples, clock/sizing)."""
        h = self.app.services["history"]
        ntp = self.app.services.get("ntp")
        key = (self.offset, h.rev, h.n, bool(ntp and ntp.synced), self.app.settings.get("sizing.inverter_kw", 25.0))
        if key != self.built_key:
            self.built_key = key
            self.rebuild()

    def older(self):
        if self.offset < MAX_DAY_OFFSET:
            self.offset += 1
        self.refresh()

    def newer(self):
        if self.offset > 0:
            self.offset -= 1
        self.refresh()

    def placeholder(self, text):
        l = C.label(self.parent, text, 20, C.MUTED)
        l.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        l.set_flex_grow(1)
        l.set_style_align(lv.ALIGN.CENTER, 0)

    def rebuild(self):
        import time
        t0 = time.ticks_ms()
        self._rebuild()
        self.app.log.info("graph: rebuilt in %d ms" % time.ticks_diff(time.ticks_ms(), t0))

    def _rebuild(self):
        p = self.parent
        p.clean()
        self._keep = []
        top = lv.obj(p)
        top.remove_style_all()
        top.set_size(lv.pct(100), lv.SIZE_CONTENT)
        top.set_flex_flow(lv.FLEX_FLOW.ROW)
        top.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        ntp = self.app.services.get("ntp")
        synced = ntp and ntp.synced
        now = T.unix_now()
        midnight = tz.day_start(tz.day_start(now) - self.offset * 86400 + 43200)      # local midnight, `offset` days back
        title = "Today"
        if synced:
            y, m, d, _h, _mi, _s, wd, _yd = T.civil(midnight + 43200 + tz.offset(midnight + 43200))
            title = "%s %02d %s" % (DAYS[wd], d, MONTHS[m - 1]) + (" (Today)" if self.offset == 0 else "")
        C.label(top, title, 24, C.TEXT)
        if not synced:
            self.placeholder("Waiting for time sync -- the chart needs\na real clock to align to today.")
            return
        btns = lv.obj(top)
        btns.remove_style_all()
        btns.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
        btns.set_flex_flow(lv.FLEX_FLOW.ROW)
        btns.set_style_pad_column(8, 0)
        prev = C.button(btns, "< Older", C.CARD, C.TEXT, self.older)
        nxt = C.button(btns, "Newer >", C.CARD, C.TEXT, self.newer)
        if self.offset >= MAX_DAY_OFFSET:
            prev.add_state(lv.STATE.DISABLED)
        if self.offset == 0:
            nxt.add_state(lv.STATE.DISABLED)
        h = self.app.services["history"]
        if h.n < 2:
            self.placeholder("Not enough history yet -- check back in a few minutes.\nOne point is recorded every 5 minutes.")
            return
        midnight_next = tz.day_start(midnight + 86400 + 43200)
        soc, solar, load = [NONE] * DAY_SLOTS, [NONE] * DAY_SLOTS, [NONE] * DAY_SLOTS
        gimp, gexp, sts = [NONE] * DAY_SLOTS, [NONE] * DAY_SLOTS, [0] * DAY_SLOTS
        have = False
        e_pv = e_imp = e_exp = e_bat = 0                   # watt-samples; x (5/60)/1000 -> kWh
        lo, hi = bisect_left(h.ts, h.n, midnight), bisect_left(h.ts, h.n, midnight_next)    # only this day's records
        for i in range(lo, hi):
            t = h.ts[i]
            if t == 0:
                continue
            slot = min((t - midnight) // 300, DAY_SLOTS - 1)
            soc[slot] = h.soc[i]
            solar[slot] = h.pv[i] // 100
            load[slot] = h.load[i] // 100
            g = h.grid[i]
            if g > 0:
                gimp[slot] = g // 100
            elif g < 0:
                gexp[slot] = -g // 100
            sts[slot] = t
            e_pv += max(h.pv[i], 0)
            e_imp += max(g, 0)
            e_exp += max(-g, 0)
            e_bat += max(-h.batt[i], 0)
            have = True
        if not have:
            self.placeholder("No data yet today -- check back soon." if self.offset == 0 else "No data recorded for this day.")
            return
        for arr in (soc, solar, load, gimp, gexp):
            join_gaps(arr, sts)
        k = 5.0 / 60 / 1000
        txt = "Solar %.1f   Import %.1f   Export %.1f   Battery used %.1f kWh" % (e_pv * k, e_imp * k, e_exp * k, e_bat * k)
        C.label(p, txt, 16, C.MUTED)
        self.day = (sts, soc, solar, load, gimp, gexp, midnight)
        inv_kw = float(self.app.settings.get("sizing.inverter_kw", 25.0))
        sec_max = int(inv_kw * 10)
        import board
        if board.portrait:
            self.mini_chart(p, "Battery", 100.0, "%", ((soc, C_BATT, 5),))
            self.mini_chart(p, "Solar & Load", inv_kw, "kW", ((load, C_LOAD, 2), (solar, C_SOLAR, 3)))
            self.mini_chart(p, "Grid", inv_kw, "kW", ((gexp, C_EXP, 2), (gimp, C_IMP, 2)))
        else:
            row = lv.obj(p)
            row.remove_style_all()
            row.set_size(lv.pct(100), lv.pct(75))
            row.set_flex_grow(1)
            row.set_flex_flow(lv.FLEX_FLOW.ROW)
            row.set_style_pad_column(8, 0)
            self.axis(row, 0.0, 100.0, "%", lv.FLEX_ALIGN.END)
            stack = lv.obj(row)
            stack.remove_style_all()
            stack.set_size(lv.pct(100), lv.pct(100))
            stack.set_flex_grow(1)
            stack.set_style_border_color(C.c(C.FIELD_BORDER), 0)
            stack.set_style_border_width(1, 0)
            stack.set_style_radius(6, 0)
            stack.remove_flag(lv.obj.FLAG.SCROLLABLE)
            base = self.chart(stack, 1000, sec_max)
            base.set_style_bg_color(C.c(0x0F172A), 0)
            base.set_style_bg_opa(lv.OPA.COVER, 0)
            base.set_style_line_color(C.c(0x1E293B), lv.PART.MAIN)
            base.set_div_line_count(5, 4)
            for vals, col, width, sec, opa in ((gexp, C_EXP, 3, True, 178), (gimp, C_IMP, 3, True, 178),
                                                (load, C_LOAD, 3, True, 178), (solar, C_SOLAR, 4, True, 255),
                                                (soc, C_BATT, 5, False, 255)):
                ov = self.chart(stack, 1000, sec_max)
                ov.set_style_bg_opa(lv.OPA.TRANSP, 0)
                ov.set_div_line_count(0, 0)
                ov.set_style_line_width(width, lv.PART.ITEMS)
                ov.set_style_line_opa(opa, lv.PART.ITEMS)
                ser = ov.add_series(kit.rgb(col), lv.chart.AXIS.SECONDARY_Y if sec else lv.chart.AXIS.PRIMARY_Y)
                self.feed(ov, ser, vals)
                ov.refresh()
            self.inspect_layer(stack)
            self.axis(row, 0.0, inv_kw, "kW", lv.FLEX_ALIGN.START)
        ax = lv.obj(p)
        ax.remove_style_all()
        ax.set_size(lv.pct(100), lv.SIZE_CONTENT)
        ax.set_flex_flow(lv.FLEX_FLOW.ROW)
        ax.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        for t in ("00:00", "06:00", "12:00", "18:00", "24:00"):
            C.label(ax, t, 16, C.MUTED)
        leg = lv.obj(p)
        leg.remove_style_all()
        leg.set_size(lv.pct(100), lv.SIZE_CONTENT)
        leg.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
        leg.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        leg.set_style_pad_row(6, 0)
        leg.set_style_pad_column(10, 0)
        leg.set_style_pad_bottom(14, 0)

        def last(arr, scale, fmt):
            for v in reversed(arr):
                if v != NONE:
                    return fmt % (v / scale)
            return "--"
        for name, col, val in (("Battery", C_BATT, last(soc, 10, "%.1f%%")), ("Solar", C_SOLAR, last(solar, 10, "%.2f kW")),
                               ("Load", C_LOAD, last(load, 10, "%.2f kW")), ("Grid Import", C_IMP, last(gimp, 10, "%.2f kW")),
                               ("Grid Export", C_EXP, last(gexp, 10, "%.2f kW"))):
            self.chip(leg, name, col, val)

    def inspect_layer(self, stack):
        """Tap the chart to read the values at that time; tap again (or wait a few seconds) to dismiss."""
        self.cursor = lv.obj(stack)
        self.cursor.remove_style_all()
        self.cursor.set_size(2, lv.pct(100))
        self.cursor.set_style_bg_color(C.c(0xF1F5F9), 0)
        self.cursor.set_style_bg_opa(lv.OPA._60, 0)
        self.cursor.add_flag(lv.obj.FLAG.HIDDEN)
        self.cursor.remove_flag(lv.obj.FLAG.CLICKABLE)
        self.tip = lv.label(stack)
        self.tip.set_style_bg_color(C.c(C.CARD), 0)
        self.tip.set_style_bg_opa(lv.OPA._90, 0)
        self.tip.set_style_text_color(C.c(C.TEXT), 0)
        self.tip.set_style_text_font(kit.font(16), 0)
        self.tip.set_style_radius(6, 0)
        self.tip.set_style_pad_all(6, 0)
        self.tip.add_flag(lv.obj.FLAG.HIDDEN)
        self.tip.remove_flag(lv.obj.FLAG.CLICKABLE)
        self.stack = stack
        C.on_click(stack, self.inspect)

    def inspect(self):
        import board
        sts, soc, solar, load, gimp, gexp, midnight = self.day
        a = lv.area_t()
        self.stack.get_coords(a)
        w = a.x2 - a.x1 + 1
        x = board._touch.x - a.x1
        if not 0 <= x < w:
            return
        if not self.tip.has_flag(lv.obj.FLAG.HIDDEN) and abs(self.cursor.get_x() - x) < 24:
            return self.hide_tip()
        slot = max(0, min(x * DAY_SLOTS // w, DAY_SLOTS - 1))
        for d in range(0, 8):                                      # nearest recorded slot (history can have gaps)
            for cand in (slot - d, slot + d):
                if 0 <= cand < DAY_SLOTS and sts[cand]:
                    slot = cand
                    break
            else:
                continue
            break
        if not sts[slot]:
            return
        tm = tz.local(sts[slot])

        def v(arr, scale, unit):
            return "--" if arr[slot] == NONE else "%.*f%s" % (1 if scale == 10 else 1, arr[slot] / scale, unit)
        self.tip.set_text("%02d:%02d   Battery %s   Solar %s   Load %s\nImport %s   Export %s" % (
            tm[3], tm[4], v(soc, 10, "%"), v(solar, 10, " kW"), v(load, 10, " kW"), v(gimp, 10, " kW"), v(gexp, 10, " kW")))
        self.cursor.set_pos(slot * w // DAY_SLOTS, 0)
        self.cursor.remove_flag(lv.obj.FLAG.HIDDEN)
        self.tip.remove_flag(lv.obj.FLAG.HIDDEN)
        self.tip.align(lv.ALIGN.TOP_LEFT if x > w // 2 else lv.ALIGN.TOP_RIGHT, 8 if x > w // 2 else -8, 6)
        if self.tip_timer:
            self.tip_timer.delete()
        self.tip_timer = lv.timer_create(lambda t: self.hide_tip(), 6000, None)
        self.tip_timer.set_repeat_count(1)

    def hide_tip(self):
        if self.tip_timer:
            self.tip_timer.delete()
            self.tip_timer = None
        try:
            self.tip.add_flag(lv.obj.FLAG.HIDDEN)
            self.cursor.add_flag(lv.obj.FLAG.HIDDEN)
        except Exception:
            pass                                       # page was rebuilt meanwhile

    def feed(self, chart, ser, vals):
        """Hand a series to LVGL as one int32 array (no copy, no per-point calls); the array is kept alive by the page."""
        arr = array("i", vals)
        self._keep.append(arr)
        try:
            chart.set_series_ext_y_array(ser, arr)
        except Exception:                                  # binding without the ext-array call: one call per point
            for k, v in enumerate(vals):
                chart.set_series_value_by_id(ser, k, v)

    def mini_chart(self, parent, title, axis_max, unit, series):
        """Portrait: one small chart per metric group (title, y axis column, framed chart with overlay series)."""
        C.label(parent, title, 16, C.MUTED)
        row = lv.obj(parent)
        row.remove_style_all()
        row.set_size(lv.pct(100), lv.SIZE_CONTENT)
        row.set_flex_grow(1)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_style_pad_column(8, 0)
        self.axis(row, 0.0, axis_max, unit, lv.FLEX_ALIGN.END)
        stack = lv.obj(row)
        stack.remove_style_all()
        stack.set_size(lv.pct(100), lv.pct(100))
        stack.set_flex_grow(1)
        stack.set_style_border_color(C.c(C.FIELD_BORDER), 0)
        stack.set_style_border_width(1, 0)
        stack.set_style_radius(6, 0)
        stack.remove_flag(lv.obj.FLAG.SCROLLABLE)
        top = int(axis_max * 10)
        base = self.chart(stack, top, top)
        base.set_style_bg_color(C.c(0x0F172A), 0)
        base.set_style_bg_opa(lv.OPA.COVER, 0)
        base.set_style_line_color(C.c(0x1E293B), lv.PART.MAIN)
        base.set_div_line_count(5, 4)
        for vals, col, width in series:
            ov = self.chart(stack, top, top)
            ov.set_style_bg_opa(lv.OPA.TRANSP, 0)
            ov.set_div_line_count(0, 0)
            ov.set_style_line_width(width, lv.PART.ITEMS)
            ser = ov.add_series(kit.rgb(col), lv.chart.AXIS.PRIMARY_Y)
            self.feed(ov, ser, vals)
            ov.refresh()

    def chart(self, stack, prim_max, sec_max):
        ch = lv.chart(stack)
        ch.remove_flag(lv.obj.FLAG.CLICKABLE)
        ch.set_pos(0, 0)
        ch.set_size(lv.pct(100), lv.pct(100))
        ch.set_style_border_width(0, 0)
        ch.set_style_pad_all(0, 0)
        ch.set_type(lv.chart.TYPE.LINE)
        ch.set_point_count(DAY_SLOTS)
        ch.set_axis_range(lv.chart.AXIS.PRIMARY_Y, 0, prim_max)
        ch.set_axis_range(lv.chart.AXIS.SECONDARY_Y, 0, sec_max)
        ch.set_update_mode(lv.chart.UPDATE_MODE.CIRCULAR)
        ch.set_style_size(0, 0, lv.PART.INDICATOR)
        return ch

    def axis(self, parent, lo, hi, unit, align):
        col = lv.obj(parent)
        col.remove_style_all()
        col.set_size(50, lv.pct(100))
        col.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        col.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, align, align)
        for v in (hi, hi - 0.25 * (hi - lo), (hi + lo) / 2, lo + 0.25 * (hi - lo), lo):
            C.label(col, "%.0f%s" % (v, unit), 16, C.MUTED)

    def chip(self, parent, name, col, val):
        chip = lv.obj(parent)
        chip.remove_style_all()
        chip.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
        chip.set_flex_flow(lv.FLEX_FLOW.ROW)
        chip.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        chip.set_style_pad_column(5, 0)
        sw = lv.obj(chip)
        sw.remove_style_all()
        sw.set_size(12, 12)
        sw.set_style_radius(3, 0)
        sw.set_style_bg_color(kit.rgb(col), 0)
        sw.set_style_bg_opa(lv.OPA.COVER, 0)
        C.label(chip, "%s %s" % (name, val), 16, C.TEXT)
