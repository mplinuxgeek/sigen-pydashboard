"""Dashboard tile: four quadrants (Battery, Solar, Load, Grid), each with live power, a fill bar and daily totals.
Landscape 800x480 layout, ported from dashboard_ui.c."""
import asyncio
import time

import lvgl as lv

from core import prefs, state as st, timeutil as T, tz
from core.fmt import ago
from . import kit
from .kit import (LEFT, RIGHT, CENTER, NO_DATA, LABEL, TITLE, DIV, SOL_FILL, SOL_BORDER, LOAD_FILL, LOAD_BORDER,
                  IMP_FILL, IMP_BORDER, EXP_FILL, EXP_BORDER, BATT_BORDER, DISCHARGE_RED, TRACK_BG, BAR_BORDER,
                  rect, label, set_text, font)

MDI_WIFI, MDI_CLOCK, MDI_HOME_BATT = "", "", ""
SPLIT_SOLAR, SPLIT_BATT, SPLIT_GRID = "", "", ""
BLINK_MS = 150
BAR_H, SUM_H, GAP = 36, 26, 4                          # top bar, portrait summary line, gap between cards


class Dashboard:
    def __init__(self, app, parent, on_clock=None, on_status=None):
        self.app = app
        self.parent = parent
        self.on_clock, self.on_status = on_clock, on_status
        self.self_pct = None
        self.active = False
        self.soc = self.cap = None
        self.blink_on = False
        self.blink = None
        self.cov_busy = False
        self._last_act = None
        self.build()

    # ---- sizing ---------------------------------------------------------------------------------
    def sizing(self):
        s = self.app.settings
        return float(s.get("sizing.inverter_kw", 25.0)), float(s.get("sizing.solar_kw", 25.0))

    def rebuild(self):
        for name in ("blink", "tick_timer"):
            t = getattr(self, name, None)
            if t:
                t.delete()
                setattr(self, name, None)
        self.parent.clean()
        self._ticked = False
        self.build()
        self.refresh()

    # ---- build ------------------------------------------------------------------------------------
    def build(self):
        import board
        self.portrait = board.portrait
        self.inv_kw, self.sol_kw = self.sizing()
        self.dec = prefs.kw_decimals()
        self.pk = {}
        # Header: a top bar (clock, date, status icons) plus, in portrait, a summary line. The four quadrants below it keep
        # their fonts and are only tightened vertically: Y() maps a y coordinate drawn for the original 238 px (landscape) /
        # 197 px (portrait) card height onto the shorter card.
        if self.portrait:
            self.top = BAR_H + SUM_H
            self.card_h = (800 - self.top - 3 * GAP) // 4
            self.K = self.card_h / 197.0
        else:
            self.top = BAR_H + 2
            self.card_h = (480 - self.top - GAP) // 2
            self.K = self.card_h / 238.0
        Y = self.Y
        # bar geometry shared by build_*() and the refresh code (landscape defaults; portrait overrides)
        self.b_center, self.b_half, self.b_bar_y = 146, 132, Y(176)
        self.b_icon = (304, 73, Y(50), Y(128))              # fill x, width, top, max height inside the battery icon
        self.s_x0, self.s_w, self.s_bar_y = 15, 364, Y(176)
        self.l_x0, self.l_w, self.l_bar_y = 15, 364, Y(176)
        self.g_center, self.g_half, self.g_bar_y = 196, 180, Y(176)
        self.sc_w = 383 - 65 - 4
        self.split_x, self.split_y, self.split_w, self.split_h = 15, Y(150), 364, 12
        self.build_bar(self.parent)
        if self.portrait:
            self.build_portrait(self.parent)
        else:
            self.build_battery(self.parent)
            self.build_solar(self.parent)
            self.build_load(self.parent)
            self.build_grid(self.parent)
        self.cards = (self.b_card, self.s_card, self.l_card, self.g_card)
        self.blink = lv.timer_create(self._blink, BLINK_MS, None)
        self.tick_timer = lv.timer_create(lambda t: self.tick(), 5000, None)
        self.tick()

    def Y(self, v):
        """Scale a vertical coordinate designed for the full-height card onto the real one."""
        return int(v * getattr(self, "K", 1.0) + 0.5)

    def build_bar(self, p):
        """Top bar: clock and date (tap: brightness) on the left, then the summary sentence, then the freshness text,
        the update dot and the three status icons (tap: status details)."""
        W = 480 if self.portrait else 800
        bar = self.bar = lv.obj(p)
        bar.remove_style_all()
        bar.set_pos(0, 0)
        bar.set_size(W, BAR_H)
        bar.remove_flag(lv.obj.FLAG.SCROLLABLE)
        rect(bar, 12, BAR_H - 1, W - 24, 1, DIV)
        left = self.bar_left = lv.obj(bar)
        left.remove_style_all()
        left.set_pos(12, 0)
        left.set_size(lv.SIZE_CONTENT, BAR_H - 2)
        left.set_flex_flow(lv.FLEX_FLOW.ROW)
        left.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        left.set_style_pad_column(10, 0)
        left.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.t_clock = lv.label(left)
        self.t_clock.set_style_text_font(font(24), 0)
        self.t_clock.set_style_text_color(kit.rgb(TITLE), 0)
        self.t_clock.set_text("--:--")
        self.t_date = lv.label(left)
        self.t_date.set_style_text_font(font(16), 0)
        self.t_date.set_style_text_color(kit.rgb(LABEL), 0)
        self.t_date.set_text("")
        right = self.bar_right = lv.obj(bar)
        right.remove_style_all()
        right.set_size(200 if not self.portrait else 190, BAR_H - 2)        # fixed width, content right-aligned: it can grow leftwards
        right.set_flex_flow(lv.FLEX_FLOW.ROW)
        right.set_flex_align(lv.FLEX_ALIGN.END, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        right.set_style_pad_column(10, 0)
        right.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.t_age = lv.label(right)
        self.t_age.set_style_text_font(font(14), 0)
        self.t_age.set_style_text_color(kit.rgb(LABEL), 0)
        self.t_age.set_text("")
        if self.portrait:
            self.t_age.add_flag(lv.obj.FLAG.HIDDEN)           # no room next to the clock; the summary line says it
        self.t_upd = lv.obj(right)                             # "update available" dot
        self.t_upd.remove_style_all()
        self.t_upd.set_size(12, 12)
        self.t_upd.set_style_radius(6, 0)
        self.t_upd.set_style_bg_color(kit.rgb(kit.DOT_ACTIVE), 0)
        self.t_upd.set_style_bg_opa(kit.OPA.COVER, 0)
        self.t_upd.add_flag(lv.obj.FLAG.HIDDEN)
        self.i_modbus = lv.label(right)
        self.i_ntp = lv.label(right)
        self.i_wifi = lv.label(right)
        for icon, glyph in ((self.i_modbus, MDI_HOME_BATT), (self.i_ntp, MDI_CLOCK), (self.i_wifi, MDI_WIFI)):
            icon.set_style_text_font(lv.font_mdi_24, 0)
            icon.set_style_text_color(kit.rgb(NO_DATA), 0)
            icon.set_text(glyph)
        right.align(lv.ALIGN.TOP_RIGHT, -12, 0)
        # summary sentence
        if self.portrait:
            self.t_sum = label(p, 15, BAR_H + 2, LEFT, font(16), LABEL, "", 450)
        else:
            self.t_sum = label(bar, 236, 10, LEFT, font(16), LABEL, "", 356)
        self.t_sum.set_long_mode(lv.label.LONG_MODE.DOTS)
        for obj, cb in ((left, self.on_clock), (right, self.on_status)):
            if cb:
                obj.add_flag(lv.obj.FLAG.CLICKABLE)
                obj.add_event_cb(lambda e, f=cb: f(), lv.EVENT.CLICKED, None)
        self.paint_icons()

    def build_battery(self, p):
        Y, by = self.Y, self.b_bar_y
        c = self.b_card = kit.card(p, 0, self.top, 398, self.card_h, kit.BATT_BG, BATT_BORDER)
        kit.title(c, font(34), TITLE, "BATTERY")
        self.b_temp = label(c, 373, Y(12), RIGHT, font(20), NO_DATA, "-- C")
        self.b_outline = kit.outline(c, 298, Y(44), 85, Y(140), NO_DATA, 8, 3)
        self.b_nub = rect(c, 324, Y(36), 34, 11, NO_DATA, 4)
        self.b_pct = label(c, 15, Y(42), LEFT, font(48), NO_DATA, "--%")
        self.b_time = label(c, 15, Y(94), LEFT, font(16), NO_DATA, "")
        self.b_fill = rect(c, 304, Y(178), 73, 0, NO_DATA, 4)
        self.b_kwh = label(c, 340, Y(192), CENTER, font(16), NO_DATA, "-- kWh")
        self.b_power = label(c, 149, Y(110), CENTER, font(30), NO_DATA, "-- kW")
        self.b_badge = kit.Badge(c, font(16), "NO DATA", 149, by - 29, CENTER, 2)
        rect(c, 13, by, 268, 24, TRACK_BG, 6)
        kit.outline(c, 13, by, 268, 24, BAR_BORDER, 6)
        rect(c, 146, by + 2, 2, 20, LABEL)
        self.b_bar = rect(c, 148, by + 2, 0, 20, NO_DATA, 4)
        kit.glow(self.b_bar, NO_DATA)
        self.b_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        self.pk["bchg"] = kit.PeakMarker(c, by)
        self.pk["bdis"] = kit.PeakMarker(c, by)
        inv = "%.0f kW" % self.inv_kw
        ty = by + 29
        label(c, 13, ty, LEFT, font(20), LABEL, inv)
        label(c, 147, ty, CENTER, font(20), LABEL, "0")
        label(c, 281, ty, RIGHT, font(20), LABEL, inv)

    def _ticks(self, c, kw, big_fnt=16):
        ty = self.s_bar_y + 29
        label(c, 13, ty, LEFT, font(16), LABEL, "0 kW")
        for x, f in ((105, .25), (197, .5), (289, .75)):
            label(c, x, ty, CENTER, font(14), LABEL, "%.1f" % (kw * f))
        label(c, 381, ty, RIGHT, font(16), LABEL, "%.0f kW" % kw)

    def _bar_frame(self, c):
        by = self.s_bar_y
        rect(c, 13, by, 368, 24, TRACK_BG, 6)
        for x in (104, 196, 288):
            m = rect(c, x, by + 2, 2, 20, LABEL)
            m.set_style_bg_opa(kit.OPA._40, 0)

    def build_solar(self, p):
        Y, by = self.Y, self.s_bar_y
        c = self.s_card = kit.card(p, 402, self.top, 398, self.card_h, kit.SOL_BG, SOL_BORDER)
        kit.title(c, font(34), TITLE, "SOLAR")
        self.s_value = label(c, 15, Y(42), LEFT, font(48), NO_DATA, "-- kW")
        self.s_daily = label(c, 15, Y(94), LEFT, font(16), NO_DATA, "Today: -- kWh")
        self.s_mtd = label(c, 15, Y(118), LEFT, font(16), NO_DATA, "MTD: -- kWh")
        self.s_self = label(c, 15, Y(144), LEFT, font(16), NO_DATA, "--%", 45)
        self.s_self.set_long_mode(lv.label.LONG_MODE.CLIP)
        self.s_self_fill = kit.mini_bar(c, 65, Y(145), 383 - 65, 14, SOL_BORDER)
        self._bar_frame(c)
        self.s_target = rect(c, 15, by + 2, 0, 20, LOAD_FILL, 4)
        self.s_target.set_style_bg_opa(kit.OPA._0, 0)
        self.s_bar = rect(c, 15, by + 2, 0, 20, SOL_FILL, 4)
        kit.glow(self.s_bar, SOL_FILL)
        self.s_bar.set_style_bg_grad_color(kit.rgb(SOL_BORDER), 0)
        self.s_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        kit.outline(c, 13, by, 368, 24, BAR_BORDER, 6)
        self.pk["sol"] = kit.PeakMarker(c, by)
        self._ticks(c, self.sol_kw)

    def build_load(self, p):
        Y, by = self.Y, self.l_bar_y
        c = self.l_card = kit.card(p, 0, self.top + self.card_h + GAP, 398, self.card_h, kit.LOAD_BG, LOAD_BORDER)
        kit.title(c, font(34), TITLE, "LOAD")
        self.l_value = label(c, 15, Y(42), LEFT, font(48), NO_DATA, "-- kW")
        self.l_daily = label(c, 15, Y(94), LEFT, font(16), NO_DATA, "Today: -- kWh")
        self.l_daily_split = label(c, 383, Y(94), RIGHT, lv.font_load_split_16, NO_DATA, "")
        self.l_daily_split.set_recolor(True)
        self.l_mtd = label(c, 15, Y(118), LEFT, font(16), NO_DATA, "MTD: -- kWh")
        self.l_mtd_split = label(c, 383, Y(118), RIGHT, lv.font_load_split_16, NO_DATA, "")
        self.l_mtd_split.set_recolor(True)
        # source-split bar (solar / battery / grid share of today's load)
        rect(c, 13, self.split_y - 2, 368, 16, TRACK_BG, 6)
        self.l_split = []
        for col in (SOL_BORDER, BATT_BORDER, IMP_BORDER):
            self.l_split.append(rect(c, self.split_x, self.split_y, 0, self.split_h, col))
        self.l_split[0].set_style_radius(4, 0)
        self.l_split[2].set_style_radius(4, 0)
        kit.outline(c, 13, self.split_y - 2, 368, 16, BAR_BORDER, 6)
        self._bar_frame(c)
        self.l_seg = []
        for col in (LOAD_FILL, BATT_BORDER, IMP_BORDER):
            self.l_seg.append(rect(c, 15, by + 2, 0, 20, col))
        self.l_seg[0].set_style_radius(4, 0)
        self.l_seg[2].set_style_radius(4, 0)
        kit.outline(c, 13, by, 368, 24, BAR_BORDER, 6)
        self.pk["load"] = kit.PeakMarker(c, by)
        self._ticks(c, self.inv_kw)

    def build_grid(self, p):
        Y, by = self.Y, self.g_bar_y
        c = self.g_card = kit.card(p, 402, self.top + self.card_h + GAP, 398, self.card_h, kit.GRID_BG_IDLE, IMP_BORDER)
        kit.title(c, font(34), TITLE, "GRID")
        self.g_ongrid = kit.Badge(c, font(16), "", 383, Y(14), RIGHT, 2)
        self.g_daily = label(c, 15, Y(94), LEFT, font(16), NO_DATA, "Today: In -- / Out -- kWh")
        self.g_mtd = label(c, 15, Y(118), LEFT, font(16), NO_DATA, "MTD: In -- / Out -- kWh")
        self.g_value = label(c, 15, Y(42), LEFT, font(48), NO_DATA, "-- kW")
        self.g_badge = kit.Badge(c, font(16), "GRID", 199, by - 29, CENTER, 2)
        rect(c, 13, by, 368, 24, TRACK_BG, 6)
        kit.outline(c, 13, by, 368, 24, BAR_BORDER, 6)
        rect(c, 196, by + 2, 2, 20, NO_DATA)
        self.g_bar = rect(c, 196, by + 2, 0, 20, NO_DATA, 4)
        kit.glow(self.g_bar, NO_DATA)
        self.g_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        self.pk["gimp"] = kit.PeakMarker(c, by)
        self.pk["gexp"] = kit.PeakMarker(c, by)
        inv = "%.0f kW" % self.inv_kw
        ty = by + 29
        label(c, 13, ty, LEFT, font(20), LABEL, inv)
        label(c, 197, ty, CENTER, font(20), LABEL, "0")
        label(c, 381, ty, RIGHT, font(20), LABEL, inv)

    def build_portrait(self, p):
        """480x800: four stacked bands under the bar and summary line (Solar, Battery, Load, Grid), smaller fonts, wider bars."""
        F, Y, top, h, step = font, self.Y, self.top, self.card_h, self.card_h + GAP
        self.b_center = self.b_half = 0
        by = Y(142)
        self.s_x0, self.s_w, self.s_bar_y = 15, 446, by
        self.l_x0, self.l_w, self.l_bar_y = 15, 446, by
        self.b_bar_y = self.g_bar_y = by
        ty = by + 28
        # solar
        c = self.s_card = kit.card(p, 0, top, 480, h, kit.SOL_BG, SOL_BORDER)
        kit.title(c, F(24), LABEL, "SOLAR")
        self.s_value = label(c, 15, Y(34), LEFT, F(34), NO_DATA, "-- kW")
        self.s_daily = label(c, 15, Y(76), LEFT, F(16), NO_DATA, "Today: -- kWh")
        self.s_mtd = label(c, 15, Y(96), LEFT, F(16), NO_DATA, "MTD: -- kWh")
        self.s_self = label(c, 15, Y(116), LEFT, F(16), NO_DATA, "--%", 45)
        self.s_self.set_long_mode(lv.label.LONG_MODE.CLIP)
        self.sc_w = 465 - 65 - 4
        self.s_self_fill = kit.mini_bar(c, 65, Y(117), 465 - 65, 14, SOL_BORDER)
        rect(c, 13, by, 450, 24, TRACK_BG, 6)
        for x in (125, 237, 349):
            m = rect(c, x, by + 2, 2, 20, LABEL)
            m.set_style_bg_opa(kit.OPA._40, 0)
        self.s_target = rect(c, 15, by + 2, 0, 20, LOAD_FILL, 4)
        self.s_target.set_style_bg_opa(kit.OPA._0, 0)
        self.s_bar = rect(c, 15, by + 2, 0, 20, SOL_FILL, 4)
        kit.glow(self.s_bar, SOL_FILL)
        self.s_bar.set_style_bg_grad_color(kit.rgb(SOL_BORDER), 0)
        self.s_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        kit.outline(c, 13, by, 450, 24, BAR_BORDER, 6)
        self.pk["sol"] = kit.PeakMarker(c, by)
        label(c, 13, ty, LEFT, F(14), LABEL, "0 kW")
        for x, f in ((126, .25), (238, .5), (350, .75)):
            label(c, x, ty, CENTER, F(14), LABEL, "%.1f" % (self.sol_kw * f))
        label(c, 463, ty, RIGHT, F(14), LABEL, "%.0f kW" % self.sol_kw)
        # battery
        c = self.b_card = kit.card(p, 0, top + step, 480, h, kit.BATT_BG, BATT_BORDER)
        kit.title(c, F(24), LABEL, "BATTERY")
        self.b_temp = label(c, 465, Y(8), RIGHT, F(16), NO_DATA, "-- C")
        self.b_pct = label(c, 15, Y(34), LEFT, F(34), NO_DATA, "--%")
        self.b_time = label(c, 140, Y(48), LEFT, F(16), NO_DATA, "")
        iw, ih, ix, iy = 68, Y(120), 465 - 68, Y(38)
        self.b_outline = kit.outline(c, ix, iy, iw, ih, NO_DATA, 8, 3)
        self.b_nub = rect(c, ix + (iw - 28) // 2, iy - 7, 28, 9, NO_DATA, 4)
        self.b_fill = rect(c, ix + 5, iy + 5, iw - 10, 0, NO_DATA, 4)
        self.b_icon = (ix + 5, iw - 10, iy + 5, ih - 10)
        self.b_kwh = label(c, ix + iw // 2, iy + ih + 3, CENTER, F(16), NO_DATA, "-- kWh")
        x2 = ix - 12
        self.b_center = (13 + x2) // 2
        self.b_half = self.b_center - 13 - 2
        rect(c, 13, by, x2 - 13, 24, TRACK_BG, 6)
        kit.outline(c, 13, by, x2 - 13, 24, BAR_BORDER, 6)
        rect(c, self.b_center, by + 2, 2, 20, LABEL)
        self.b_bar = rect(c, self.b_center, by + 2, 0, 20, NO_DATA, 4)
        kit.glow(self.b_bar, NO_DATA)
        self.b_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        self.pk["bchg"] = kit.PeakMarker(c, by)
        self.pk["bdis"] = kit.PeakMarker(c, by)
        self.b_power = label(c, self.b_center, Y(82), CENTER, F(30), NO_DATA, "-- kW")
        self.b_badge = kit.Badge(c, F(16), "NO DATA", self.b_center, by - 28, CENTER, 2)
        inv = "%.0f kW" % self.inv_kw
        label(c, 13, ty, LEFT, F(16), LABEL, inv)
        label(c, self.b_center, ty, CENTER, F(16), LABEL, "0")
        label(c, x2, ty, RIGHT, F(16), LABEL, inv)
        # load
        c = self.l_card = kit.card(p, 0, top + 2 * step, 480, h, kit.LOAD_BG, LOAD_BORDER)
        kit.title(c, F(24), LABEL, "LOAD")
        self.l_value = label(c, 15, Y(34), LEFT, F(34), NO_DATA, "-- kW")
        self.l_daily = label(c, 15, Y(76), LEFT, F(16), NO_DATA, "Today: -- kWh")
        self.l_daily_split = label(c, 465, Y(76), RIGHT, lv.font_load_split_16, NO_DATA, "")
        self.l_daily_split.set_recolor(True)
        self.l_mtd = label(c, 15, Y(96), LEFT, F(16), NO_DATA, "MTD: -- kWh")
        self.l_mtd_split = label(c, 465, Y(96), RIGHT, lv.font_load_split_16, NO_DATA, "")
        self.l_mtd_split.set_recolor(True)
        self.split_x, self.split_y, self.split_w, self.split_h = 15, Y(122), 446, 10
        rect(c, 13, self.split_y - 2, 450, 14, TRACK_BG, 6)
        self.l_split = []
        for col in (SOL_BORDER, BATT_BORDER, IMP_BORDER):
            self.l_split.append(rect(c, self.split_x, self.split_y, 0, self.split_h, col))
        self.l_split[0].set_style_radius(4, 0)
        self.l_split[2].set_style_radius(4, 0)
        kit.outline(c, 13, self.split_y - 2, 450, 14, BAR_BORDER, 6)
        rect(c, 13, by, 450, 24, TRACK_BG, 6)
        for x in (125, 237, 349):
            m = rect(c, x, by + 2, 2, 20, LABEL)
            m.set_style_bg_opa(kit.OPA._40, 0)
        self.l_seg = []
        for col in (LOAD_FILL, BATT_BORDER, IMP_BORDER):
            self.l_seg.append(rect(c, 15, by + 2, 0, 20, col))
        self.l_seg[0].set_style_radius(4, 0)
        self.l_seg[2].set_style_radius(4, 0)
        kit.outline(c, 13, by, 450, 24, BAR_BORDER, 6)
        self.pk["load"] = kit.PeakMarker(c, by)
        label(c, 13, ty, LEFT, F(14), LABEL, "0 kW")
        for x, f in ((126, .25), (238, .5), (350, .75)):
            label(c, x, ty, CENTER, F(14), LABEL, "%.1f" % (self.inv_kw * f))
        label(c, 463, ty, RIGHT, F(14), LABEL, "%.0f kW" % self.inv_kw)
        # grid
        c = self.g_card = kit.card(p, 0, top + 3 * step, 480, h, kit.GRID_BG_IDLE, IMP_BORDER)
        kit.title(c, F(24), LABEL, "GRID")
        self.g_ongrid = kit.Badge(c, F(16), "", 465, Y(8), RIGHT, 2)
        self.g_value = label(c, 15, Y(34), LEFT, F(34), NO_DATA, "-- kW")
        self.g_daily = label(c, 15, Y(76), LEFT, F(16), NO_DATA, "Today: In -- / Out -- kWh")
        self.g_mtd = label(c, 15, Y(96), LEFT, F(16), NO_DATA, "MTD: In -- / Out -- kWh")
        self.g_badge = kit.Badge(c, F(16), "GRID", 240, by - 28, CENTER, 2)
        self.g_center, self.g_half = 238, 223
        rect(c, 13, by, 450, 24, TRACK_BG, 6)
        kit.outline(c, 13, by, 450, 24, BAR_BORDER, 6)
        rect(c, 238, by + 2, 2, 20, NO_DATA)
        self.g_bar = rect(c, 238, by + 2, 0, 20, NO_DATA, 4)
        kit.glow(self.g_bar, NO_DATA)
        self.g_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        self.pk["gimp"] = kit.PeakMarker(c, by)
        self.pk["gexp"] = kit.PeakMarker(c, by)
        inv = "%.0f kW" % self.inv_kw
        label(c, 13, ty, LEFT, F(16), LABEL, inv)
        label(c, 238, ty, CENTER, F(16), LABEL, "0")
        label(c, 463, ty, RIGHT, F(16), LABEL, inv)

    # ---- status icons --------------------------------------------------------------------------
    def paint_icons(self):
        svc = self.app.services
        wifi, ntp = svc.get("wifi"), svc.get("ntp")
        self.i_wifi.set_style_text_color(kit.rgb(kit.STATUS_OK if wifi and wifi.connected else NO_DATA), 0)
        self.i_ntp.set_style_text_color(kit.rgb(kit.STATUS_OK if ntp and ntp.synced else NO_DATA), 0)
        self.i_modbus.set_style_text_color(kit.rgb(kit.STATUS_OK if svc["state"].alive else NO_DATA), 0)

    def _blink(self, t):
        """Activity light for the Modbus icon: one short flash per request on the wire, then back to the steady colour.
        (Toggling continuously while a poll cycle runs repainted ~8 frames/s and kept the UI loop ~50 % busy, which is what
        made touch feel laggy: every repaint blocks the loop for the panel's two-frame present.)"""
        state = self.app.services["state"]
        act = state._activity
        if act != self._last_act:
            self._last_act = act
            if not self.blink_on:
                self.blink_on = True
                self.i_modbus.set_style_text_color(kit.rgb(kit.MODBUS_BUSY), 0)
        elif self.blink_on:
            self.blink_on = False
            self.i_modbus.set_style_text_color(kit.rgb(kit.STATUS_OK if state.alive else NO_DATA), 0)

    # ---- top bar -------------------------------------------------------------------------------
    def data_age(self):
        """Seconds since the last complete poll cycle, None before the first one."""
        t = self.app.services["state"].last_commit_ms
        return None if t is None else time.ticks_diff(time.ticks_ms(), t) // 1000

    def tick(self):
        """Clock, date, data age, update dot, stale dimming and the summary sentence (every 5 s). A label is only touched
        when its text changed, so an idle dashboard stays idle."""
        if not self.active and self.t_clock is not None and getattr(self, "_ticked", False):
            return
        self._ticked = True
        t = tz.local()
        if t:
            clock = prefs.fmt_clock(t[3], t[4], prefs.clock24())
            date = prefs.fmt_date(t[6], t[2], t[1], t[0], prefs.date_fmt())
        else:
            clock, date = "--:--", ""
        self._set(self.t_clock, clock)
        self._set(self.t_date, date)
        age = self.data_age()
        stale = age is not None and age > prefs.STALE_S
        self._set(self.t_age, "" if age is None else ("Data %s" % ago(age) if stale else ago(age)))
        self.t_age.set_style_text_color(kit.rgb(0xFBBF24 if stale else LABEL), 0)
        if stale != getattr(self, "_stale", None):
            self._stale = stale
            for c in self.cards:
                c.set_style_opa(kit.OPA._50 if stale else kit.OPA.COVER, 0)
        from core import updater
        u = updater.state
        show = bool(u["available"]) and self.app.settings.get("update.dismissed") != u["latest"]
        if show == self.t_upd.has_flag(lv.obj.FLAG.HIDDEN):
            self.t_upd.remove_flag(lv.obj.FLAG.HIDDEN) if show else self.t_upd.add_flag(lv.obj.FLAG.HIDDEN)
        self.update_summary(age)

    @staticmethod
    def _set(lbl, text):
        if lbl.get_text() != text:
            lbl.set_text(text)

    def update_summary(self, age=None):
        s = self.app.services["state"]
        g = s.get
        if age is None:
            age = self.data_age()
        grid_on = (int(g("grid_status")) == st.GRID_ON) if s.valid("grid_status") else None
        text, tone = prefs.summary(s.alive, age, g("soc", 0.0), g("batt_power", 0.0), g("pv_power", 0.0), g("load_power", 0.0),
                                   g("grid_power", 0.0), grid_on, self.self_pct, prefs.kw_decimals())
        if age is None and not s.alive and time.ticks_ms() < 120000:
            text = "Swipe left for graphs, history and settings"
        col = {"ok": TITLE, "warn": 0xFBBF24, "bad": DISCHARGE_RED, "idle": LABEL}[tone]
        self._set(self.t_sum, text)
        self.t_sum.set_style_text_color(kit.rgb(col), 0)

    # ---- refresh ---------------------------------------------------------------------------------
    def refresh(self):
        """Re-read the cached readings and apply them to the widgets (all from one poll cycle)."""
        if not self.active:
            return
        s = self.app.services["state"]
        g = s.get
        if s.valid("soc"):
            self.r_soc(g("soc"))
        if s.valid("batt_cap"):
            self.cap = g("batt_cap")
            self.r_kwh()
        if s.valid("batt_power"):
            self.r_batt_power(g("batt_power"))
        if s.valid("batt_temp"):
            set_text(self.b_temp, "%.0f° C" % g("batt_temp"), LABEL)
        if s.valid("pv_power"):
            self.r_solar(g("pv_power"))
        if s.valid("load_power"):
            self.r_load(g("load_power"), g("pv_power", 0.0), g("batt_power", 0.0),
                        s.valid("pv_power") and s.valid("batt_power"))
        if s.valid("grid_power"):
            self.r_grid(g("grid_power"))
        if s.valid("pv_power") and s.valid("load_power"):
            self.r_selfcons(g("pv_power"), g("load_power"))
        mtd = self.mtd()
        if s.valid("pv_daily"):
            set_text(self.s_daily, "Today: %.1f kWh" % g("pv_daily"), LABEL)
        if mtd:
            set_text(self.s_mtd, "MTD: %.0f kWh" % mtd["solar"], LABEL)
        if s.valid("load_daily"):
            set_text(self.l_daily, "Today: %.1f kWh" % g("load_daily"), LABEL)
        if mtd:
            set_text(self.l_mtd, "MTD: %.0f kWh" % mtd["load"], LABEL)
        if s.valid("grid_daily_import") and s.valid("grid_daily_export"):
            set_text(self.g_daily, "Today: In %.1f / Out %.1f kWh" % (g("grid_daily_import"), g("grid_daily_export")), LABEL)
        if mtd:
            set_text(self.g_mtd, "MTD: In %.0f / Out %.0f kWh" % (mtd["grid_import"], mtd["grid_export"]), LABEL)
        if s.valid("grid_status"):
            if int(g("grid_status")) == st.GRID_ON:
                self.g_ongrid.set("ON-GRID", kit.STATUS_OK)
            else:
                self.g_ongrid.set("OFF-GRID", DISCHARGE_RED)
        self.paint_icons()
        self.update_summary()

    def mtd(self):
        m = self.app.services.get("monthly")
        return m.billing_current() if m else None

    # ---- battery --------------------------------------------------------------------------------
    def r_soc(self, soc):
        self.soc = soc
        col = kit.soc_color(soc)
        kit.set_card_accent(self.b_card, col)
        self.b_outline.set_style_border_color(kit.rgb(col), 0)
        kit.set_bg(self.b_nub, col)
        set_text(self.b_pct, ("%.0f%%" if soc in (0.0, 100.0) else "%.1f%%") % soc, col)
        ix, iw, itop, imax = self.b_icon
        h = int(imax * (soc / 100.0))
        self.b_fill.set_pos(ix, itop + (imax - h))
        self.b_fill.set_size(iw, max(h, 0))
        kit.set_bg(self.b_fill, col)
        self.b_fill.set_style_bg_grad_color(kit.rgb(kit.darken(col, 102)), 0)
        self.b_fill.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
        self.r_kwh()

    def r_kwh(self):
        if self.soc is None or self.cap is None:
            return
        set_text(self.b_kwh, "%.1f kWh" % (self.soc / 100.0 * self.cap), kit.soc_color(self.soc))

    def r_time(self, p):
        if self.soc is None or self.cap is None:
            return
        if p > 0.05:
            hours = self.cap * (100.0 - self.soc) / 100.0 / p
        elif p < -0.05:
            hours = self.cap * self.soc / 100.0 / -p
        else:
            self.b_time.set_text("")
            return
        if hours > 99.0:
            self.b_time.set_text("")
            return
        h = int(hours)
        set_text(self.b_time, "%dh %02dm to %s" % (h, int((hours - h) * 60), "full" if p > 0 else "empty"), LABEL)

    def r_batt_power(self, p):
        soc_col = kit.soc_color(self.soc) if self.soc is not None else NO_DATA
        if p > 0.05:
            self.b_badge.set("CHARGING", soc_col)
            set_text(self.b_power, "+%.*f kW" % (self.dec, p), soc_col)
        elif p < -0.05:
            self.b_badge.set("DISCHARGING", DISCHARGE_RED)
            set_text(self.b_power, "%.*f kW" % (self.dec, -p), DISCHARGE_RED)
        else:
            self.b_badge.set("STANDBY", LABEL)
            set_text(self.b_power, "%.*f kW" % (self.dec, 0), LABEL)
        self.r_time(p)
        bar = self.b_bar
        half, cx, by = self.b_half, self.b_center, self.b_bar_y + 2
        if p > 0.05:
            w = int(half * min(p / self.inv_kw, 1.0))
            bar.set_pos(cx + 2, by)
            bar.set_size(w, 20)
            kit.set_bg(bar, soc_col)
            bar.set_style_bg_grad_color(kit.rgb(kit.lighten(soc_col, 76)), 0)
            bar.set_style_shadow_color(kit.rgb(soc_col), 0)
        elif p < -0.05:
            w = int(half * min(-p / self.inv_kw, 1.0))
            bar.set_pos(cx - w, by)
            bar.set_size(w, 20)
            kit.set_bg(bar, kit.darken(DISCHARGE_RED, 76))
            bar.set_style_bg_grad_color(kit.rgb(DISCHARGE_RED), 0)
            bar.set_style_shadow_color(kit.rgb(DISCHARGE_RED), 0)
        else:
            bar.set_size(0, 20)

    # ---- solar ----------------------------------------------------------------------------------
    def r_solar(self, pv):
        gen = pv > 0.05
        border = SOL_BORDER if gen else LABEL
        kit.set_card_accent(self.s_card, border)
        set_text(self.s_value, "%.*f kW" % (self.dec, pv), SOL_BORDER if gen else NO_DATA)
        pct = min(pv / self.sol_kw, 1.0)
        self.s_bar.set_size(int(self.s_w * pct) if pct > 0.01 else 0, 20)
        kit.set_bg(self.s_bar, SOL_FILL if gen else LABEL)
        self.s_bar.set_style_bg_grad_color(kit.rgb(border), 0)
        self.s_bar.set_style_shadow_color(kit.rgb(border), 0)

    def r_selfcons(self, pv, load):
        if load <= 0.05:
            set_text(self.s_self, "--%", NO_DATA)
            self.s_self_fill.set_size(0, 10)
            self.s_target.set_style_bg_opa(kit.OPA._0, 0)
            return
        pct = pv / load * 100.0
        excess = pct > 100.0
        set_text(self.s_self, "%.0f%%" % pct, BATT_BORDER if excess else LABEL)
        self.s_self_fill.set_size(int(self.sc_w * (1.0 if excess else pct / 100.0)), 10)
        kit.set_bg(self.s_self_fill, BATT_BORDER if excess else SOL_FILL)
        tw = int(self.s_w * min(load / self.sol_kw, 1.0))
        self.s_target.set_size(max(tw, 0), 20)
        self.s_target.set_style_bg_opa(kit.OPA._50, 0)

    # ---- load -----------------------------------------------------------------------------------
    def r_load(self, load, pv, batt, have_split):
        set_text(self.l_value, "%.*f kW" % (self.dec, load), LOAD_BORDER)
        pct = max(0.0, min(load / self.inv_kw, 1.0))
        total = int(self.l_w * pct + 0.5) if pct > 0.005 else 0
        sw = bw = 0
        if have_split and load > 0.05 and total > 0:
            solar = min(pv, load) if pv > 0 else 0.0
            rem = load - solar
            dis = -batt if batt < 0 else 0.0
            sw = int(total * solar / load + 0.5)
            bw = int(total * min(dis, rem) / load + 0.5)
            sw = min(sw, total)
            bw = min(bw, total - sw)
            kit.set_bg(self.l_seg[0], SOL_BORDER)
        else:
            kit.set_bg(self.l_seg[0], LOAD_FILL)
            sw = total
        gw = max(total - sw - bw, 0)
        x = self.l_x0
        for seg, w in zip(self.l_seg, (sw, bw, gw)):
            seg.set_pos(x, self.l_bar_y + 2)
            seg.set_size(w, 20)
            x += w

    # ---- grid -----------------------------------------------------------------------------------
    def r_grid(self, gp):
        imp = gp if gp > 0 else 0.0
        exp = -gp if gp < 0 else 0.0
        exporting, importing = exp > 0.05, imp > 0.05
        bg, accent, fill = kit.GRID_BG_IDLE, LABEL, LABEL
        if exporting:
            bg, accent, fill = kit.EXP_BG, EXP_BORDER, EXP_FILL
        elif importing:
            bg, accent, fill = kit.IMP_BG, IMP_BORDER, IMP_FILL
        kit.set_card_accent(self.g_card, accent, bg)
        if exporting:
            self.g_badge.set("EXPORTING", EXP_BORDER)
            set_text(self.g_value, "%.*f kW" % (self.dec, exp), EXP_BORDER)
        elif importing:
            self.g_badge.set("IMPORTING", IMP_BORDER)
            set_text(self.g_value, "%.*f kW" % (self.dec, imp), IMP_BORDER)
        else:
            self.g_badge.set("STANDBY", LABEL)
            set_text(self.g_value, "%.*f kW" % (self.dec, 0), LABEL)
        bar = self.g_bar
        gc, gh, gy = self.g_center, self.g_half, self.g_bar_y + 2
        if exporting:
            w = int(gh * min(exp / self.inv_kw, 1.0))
            bar.set_pos(gc - w, gy)
            bar.set_size(w, 20)
            kit.set_bg(bar, kit.darken(fill, 76))
            bar.set_style_bg_grad_color(kit.rgb(fill), 0)
        elif importing:
            w = int(gh * min(imp / self.inv_kw, 1.0))
            bar.set_pos(gc + 2, gy)
            bar.set_size(w, 20)
            kit.set_bg(bar, fill)
            bar.set_style_bg_grad_color(kit.rgb(kit.lighten(fill, 76)), 0)
        else:
            bar.set_size(0, 20)
        bar.set_style_shadow_color(kit.rgb(fill), 0)

    # ---- history-derived: today/MTD source split + peak markers (60 s cadence) --------------
    def update_covered(self):
        if self.active and not self.cov_busy:
            asyncio.create_task(self._covered_task())

    async def _covered_task(self):
        """Today / billing-cycle source split and peak markers from the history ring (heavy: runs as a coroutine)."""
        h = self.app.services.get("history")
        if not h or not h.n:
            return
        self.cov_busy = True
        try:
            m = self.app.services.get("monthly")
            now = T.unix_now()
            today_start = tz.day_start(now)
            mtd_start = (m.billing_start_epoch() if m else None) or today_start
            d = await h.day_stats(mtd_start, today_start, now)
            if not self.active:
                return
            for lbl, (solar, batt, load) in ((self.l_daily_split, d["today"]), (self.l_mtd_split, d["mtd"])):
                self._covered(lbl, solar, batt, load)
            self._split_bar(*d["today"])
            sol, bat, load = d["today"]
            self.self_pct = None if load <= 0.05 else int(max(0.0, min((sol + bat) / load * 100.0, 100.0)) + 0.5)
            pk = d["peaks"]
            self.pk["sol"].set(self.s_x0, self.s_w, self.s_bar_y, pk["pv"], self.sol_kw, 0)
            self.pk["load"].set(self.l_x0, self.l_w, self.l_bar_y, pk["load"], self.inv_kw, 0)
            self.pk["bchg"].set(self.b_center, self.b_half, self.b_bar_y, pk["batt_chg"], self.inv_kw, +1)
            self.pk["bdis"].set(self.b_center, -self.b_half, self.b_bar_y, pk["batt_dis"], self.inv_kw, -1)
            self.pk["gimp"].set(self.g_center, self.g_half, self.g_bar_y, pk["grid_imp"], self.inv_kw, +1)
            self.pk["gexp"].set(self.g_center, -self.g_half, self.g_bar_y, pk["grid_exp"], self.inv_kw, -1)
        finally:
            self.cov_busy = False

    def _covered(self, lbl, solar, batt, load):
        if load <= 0.05:
            lbl.set_text("")
            return
        sp = max(0.0, min(solar / load * 100.0, 100.0))
        bp = max(0.0, min(batt / load * 100.0, 100.0))
        gp = max(0.0, min(100.0 - sp - bp, 100.0))
        lbl.set_text("#FBBF24 %s%.0f%%#  #22C55E %s%.0f%%#  #818CF8 %s%.0f%%#" % (SPLIT_SOLAR, sp, SPLIT_BATT, bp, SPLIT_GRID, gp))
        lbl.set_style_text_color(kit.rgb(LABEL), 0)

    def _split_bar(self, solar, batt, load):
        w, h = self.split_w, self.split_h
        if load < 0.05:
            for s in self.l_split:
                s.set_width(0)
            return
        sf = max(0.0, min(solar / load, 1.0))
        bf = max(0.0, min(batt / load, 1.0 - sf))
        sw = int(w * sf + 0.5)
        bw = int(w * bf + 0.5)
        gw = w - sw - bw
        if gw < 0:
            gw, bw = 0, max(w - sw, 0)
        x = self.split_x
        for seg, sz in zip(self.l_split, (sw, bw, gw)):
            seg.set_pos(x, self.split_y)
            seg.set_size(sz, h)
            x += sz


# ---- page lifecycle (called by ui.shell) ---------------------------------------------------------------------
def _on_show(self):
    if getattr(self, "sizing_changed", False):
        self.sizing_changed = False
        self.rebuild()
    self.active = True
    self.tick()
    self.refresh()
    self.update_covered()
    if not getattr(self, "cov_timer", None):
        self.cov_timer = lv.timer_create(lambda t: self.update_covered(), 60000, None)


def _on_hide(self):
    self.active = False


Dashboard.on_show = _on_show
Dashboard.on_hide = _on_hide
