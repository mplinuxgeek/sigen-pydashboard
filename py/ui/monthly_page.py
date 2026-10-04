"""Monthly tab: Load / Solar / Grid Import / Grid Export per month as a grouped bar chart, six months a page.
The in-progress month is included and marked with an asterisk."""
import lvgl as lv

from . import common as C, kit
from .graph import MONTHS

WINDOW = 6
C_SOLAR, C_IMP, C_EXP, C_LOAD = 0xFF9800, 0xDC4646, 0xA280DB, 0x4DB6AD


class MonthlyPage:
    def __init__(self, parent, app, shell):
        self.app, self.parent = app, parent
        self.page = 0
        parent.set_style_bg_color(C.c(C.BG), 0)
        parent.set_style_bg_opa(lv.OPA.COVER, 0)
        parent.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        parent.set_style_pad_all(10, 0)
        parent.set_style_pad_row(6, 0)
        parent.remove_flag(lv.obj.FLAG.SCROLLABLE)

    def on_show(self):
        self.page = 0
        self.rebuild()

    def on_hide(self):
        self.parent.clean()

    def older(self):
        self.page += 1
        self.rebuild()

    def newer(self):
        if self.page > 0:
            self.page -= 1
        self.rebuild()

    def inspect(self):
        """Tap a month's bars: its four totals and the change on the same month last year."""
        import board
        a = lv.area_t()
        self.chart.get_coords(a)
        w = a.x2 - a.x1 + 1
        x = board._touch.x - a.x1
        n = len(self.vis)
        if not 0 <= x < w or n == 0:
            return
        r = self.vis[min(x * n // w, n - 1)]
        text = "%s '%02d:  Load %d   Solar %d   Import %d   Export %d kWh" % (MONTHS[r[1] - 1], r[0] % 100, r[5], r[2], r[3], r[4])
        prev = [q for q in self.rows if q[0] == r[0] - 1 and q[1] == r[1]]
        if prev:
            q = prev[0]

            def delta(new, old):
                return "n/a" if old <= 0 else "%+d%%" % int((new - old) * 100.0 / old + (0.5 if new >= old else -0.5))
            text += "\nvs %s '%02d:  Load %s   Solar %s   Import %s" % (MONTHS[q[1] - 1], q[0] % 100, delta(r[5], q[5]), delta(r[2], q[2]), delta(r[3], q[3]))
        self.readout.set_text(text)
        self.readout.set_style_text_color(C.c(C.TEXT), 0)

    def placeholder(self, text):
        l = C.label(self.parent, text, 20, C.MUTED)
        l.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        l.set_flex_grow(1)
        l.set_style_align(lv.ALIGN.CENTER, 0)

    def rebuild(self):
        p = self.parent
        p.clean()
        m = self.app.services["monthly"]
        rows = [list(r) for r in m.months()]          # [year, month, solar, import, export, load]
        cur = m.current()
        if cur:
            rows.append([cur["year"], cur["month"], cur["solar"], cur["grid_import"], cur["grid_export"], cur["load"]])
        top = lv.obj(p)
        top.remove_style_all()
        top.set_size(lv.pct(100), lv.SIZE_CONTENT)
        top.set_flex_flow(lv.FLEX_FLOW.ROW)
        top.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        C.label(top, "Monthly Usage", 24, C.TEXT)
        count = len(rows)
        if count == 0:
            self.placeholder("Not enough history yet -- monthly totals fill in\nas full calendar days pass. Check back tomorrow.")
            return
        max_page = (count - 1) // WINDOW
        self.page = max(0, min(self.page, max_page))
        end = max(0, min(count - self.page * WINDOW, count))
        start = max(end - WINDOW, 0)
        vis = rows[start:end]
        btns = lv.obj(top)
        btns.remove_style_all()
        btns.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
        btns.set_flex_flow(lv.FLEX_FLOW.ROW)
        btns.set_style_pad_column(8, 0)
        prev = C.button(btns, "< Older", C.CARD, C.TEXT, self.older)
        nxt = C.button(btns, "Newer >", C.CARD, C.TEXT, self.newer)
        if start == 0:
            prev.add_state(lv.STATE.DISABLED)
        if self.page == 0:
            nxt.add_state(lv.STATE.DISABLED)
        if not vis:
            self.placeholder("Nothing in this window.")
            return
        self.rows, self.vis = rows, vis
        self.readout = C.label(p, "Tap a month for its totals", 16, C.MUTED)
        self.readout.set_height(42)
        mx = max(max(r[2:6]) for r in vis)
        axis_max = 50 if mx <= 0 else int(-(-mx // 50) * 50)
        row = lv.obj(p)
        row.remove_style_all()
        row.set_size(lv.pct(100), lv.pct(100))
        row.set_flex_grow(1)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_style_pad_column(8, 0)
        col = lv.obj(row)
        col.remove_style_all()
        col.set_size(60, lv.pct(100))
        col.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        col.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.END, lv.FLEX_ALIGN.END)
        for i in range(5):
            C.label(col, "%.0f" % (axis_max - axis_max / 4 * i), 16, C.MUTED)
        ch = lv.chart(row)
        ch.remove_flag(lv.obj.FLAG.CLICKABLE)
        ch.set_flex_grow(1)
        ch.set_height(lv.pct(100))
        ch.set_style_bg_color(C.c(0x0F172A), 0)
        ch.set_style_bg_opa(lv.OPA.COVER, 0)
        ch.set_style_border_color(C.c(C.FIELD_BORDER), 0)
        ch.set_style_border_width(1, 0)
        ch.set_style_pad_all(0, 0)
        ch.set_style_line_color(C.c(0x1E293B), lv.PART.MAIN)
        ch.set_style_pad_column(24, 0)
        ch.set_style_pad_column(8, lv.PART.ITEMS)
        ch.set_type(lv.chart.TYPE.BAR)
        ch.set_div_line_count(5, 0)
        ch.set_point_count(len(vis))
        ch.set_axis_range(lv.chart.AXIS.PRIMARY_Y, 0, axis_max)
        for idx, colr in ((5, C_LOAD), (2, C_SOLAR), (3, C_IMP), (4, C_EXP)):
            ser = ch.add_series(kit.rgb(colr), lv.chart.AXIS.PRIMARY_Y)
            for k, r in enumerate(vis):
                ch.set_series_value_by_id(ser, k, int(r[idx] + 0.5))
        ch.refresh()
        ch.add_flag(lv.obj.FLAG.CLICKABLE)
        self.chart = ch
        C.on_click(ch, self.inspect)
        ax = lv.obj(p)
        ax.remove_style_all()
        ax.set_size(lv.pct(100), lv.SIZE_CONTENT)
        ax.set_style_pad_left(68, 0)
        ax.set_flex_flow(lv.FLEX_FLOW.ROW)
        ax.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        in_progress = cur is not None and end == count
        for i, r in enumerate(vis):
            txt = "%s '%02d" % (MONTHS[r[1] - 1], r[0] % 100) + ("*" if in_progress and i == len(vis) - 1 else "")
            l = C.label(ax, txt, 16, C.MUTED)
            l.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
            l.set_width(0)
            l.set_flex_grow(1)
        leg = lv.obj(p)
        leg.remove_style_all()
        leg.set_size(lv.pct(100), lv.SIZE_CONTENT)
        leg.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
        leg.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        leg.set_style_pad_row(6, 0)
        leg.set_style_pad_column(10, 0)
        leg.set_style_pad_bottom(14, 0)
        for name, colr in (("Load", C_LOAD), ("Solar", C_SOLAR), ("Grid Import", C_IMP), ("Grid Export", C_EXP)):
            chip = lv.obj(leg)
            chip.remove_style_all()
            chip.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
            chip.set_flex_flow(lv.FLEX_FLOW.ROW)
            chip.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
            chip.set_style_pad_column(5, 0)
            sw = lv.obj(chip)
            sw.remove_style_all()
            sw.set_size(12, 12)
            sw.set_style_radius(3, 0)
            sw.set_style_bg_color(kit.rgb(colr), 0)
            sw.set_style_bg_opa(lv.OPA.COVER, 0)
            C.label(chip, name, 16, C.TEXT)
        if in_progress:
            C.label(leg, "* current month, in progress", 16, C.MUTED)
