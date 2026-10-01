"""Dashboard tile: four quadrants (Battery, Solar, Load, Grid), each with live power, a fill bar and daily totals.
Landscape 800x480 layout, ported from dashboard_ui.c."""
import asyncio

import lvgl as lv

from core import state as st, timeutil as T, tz
from . import kit
from .kit import (LEFT, RIGHT, CENTER, NO_DATA, LABEL, TITLE, SOL_FILL, SOL_BORDER, LOAD_FILL, LOAD_BORDER,
                  IMP_FILL, IMP_BORDER, EXP_FILL, EXP_BORDER, BATT_BORDER, DISCHARGE_RED, TRACK_BG, BAR_BORDER,
                  rect, label, set_text, font)

MDI_WIFI, MDI_CLOCK, MDI_HOME_BATT = "", "", ""
SPLIT_SOLAR, SPLIT_BATT, SPLIT_GRID = "", "", ""
BLINK_MS = 150


class Dashboard:
    def __init__(self, app, parent, on_wifi_icon=None, on_modbus_icon=None):
        self.app = app
        self.parent = parent
        self.on_wifi_icon, self.on_modbus_icon = on_wifi_icon, on_modbus_icon
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
        if self.blink:
            self.blink.delete()
            self.blink = None
        self.parent.clean()
        self.build()
        self.refresh()

    # ---- build ------------------------------------------------------------------------------------
    def build(self):
        import board
        self.portrait = board.portrait
        self.inv_kw, self.sol_kw = self.sizing()
        self.pk = {}
        # bar geometry shared by build_*() and the refresh code (landscape defaults; portrait overrides)
        self.b_center, self.b_half, self.b_bar_y = 146, 132, 176
        self.b_icon = (304, 73, 50, 128)                   # fill x, width, top, max height inside the battery icon
        self.s_x0, self.s_w, self.s_bar_y = 15, 364, 176
        self.l_x0, self.l_w, self.l_bar_y = 15, 364, 176
        self.g_center, self.g_half, self.g_bar_y = 196, 180, 176
        self.sc_w = 383 - 65 - 4
        self.split_x, self.split_y, self.split_w, self.split_h = 15, 150, 364, 12
        if self.portrait:
            self.build_portrait(self.parent)
        else:
            self.build_battery(self.parent)
            self.build_solar(self.parent)
            self.build_load(self.parent)
            self.build_grid(self.parent)
            self.build_icons(self.parent)
        self.blink = lv.timer_create(self._blink, BLINK_MS, None)

    def build_battery(self, p):
        c = self.b_card = kit.card(p, 0, 0, 398, 238, kit.BATT_BG, BATT_BORDER)
        kit.title(c, font(34), TITLE, "BATTERY")
        self.b_temp = label(c, 373, 12, RIGHT, font(20), NO_DATA, "-- C")
        self.b_outline = kit.outline(c, 298, 44, 85, 140, NO_DATA, 8, 3)
        self.b_nub = rect(c, 324, 36, 34, 11, NO_DATA, 4)
        self.b_pct = label(c, 15, 42, LEFT, font(48), NO_DATA, "--%")
        self.b_time = label(c, 15, 94, LEFT, font(16), NO_DATA, "")
        self.b_fill = rect(c, 304, 178, 73, 0, NO_DATA, 4)
        self.b_kwh = label(c, 340, 192, CENTER, font(16), NO_DATA, "-- kWh")
        self.b_power = label(c, 149, 112, CENTER, font(30), NO_DATA, "-- kW")
        self.b_badge = kit.Badge(c, font(20), "NO DATA", 149, 144, CENTER)
        rect(c, 13, 176, 268, 24, TRACK_BG, 6)
        kit.outline(c, 13, 176, 268, 24, BAR_BORDER, 6)
        rect(c, 146, 178, 2, 20, LABEL)
        self.b_bar = rect(c, 148, 178, 0, 20, NO_DATA, 4)
        kit.glow(self.b_bar, NO_DATA)
        self.b_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        self.pk["bchg"] = kit.PeakMarker(c, 176)
        self.pk["bdis"] = kit.PeakMarker(c, 176)
        inv = "%.0f kW" % self.inv_kw
        label(c, 13, 205, LEFT, font(20), LABEL, inv)
        label(c, 147, 205, CENTER, font(20), LABEL, "0")
        label(c, 281, 205, RIGHT, font(20), LABEL, inv)

    def _ticks(self, c, kw, big_fnt=16):
        label(c, 13, 205, LEFT, font(16), LABEL, "0 kW")
        for x, f in ((105, .25), (197, .5), (289, .75)):
            label(c, x, 205, CENTER, font(14), LABEL, "%.1f" % (kw * f))
        label(c, 381, 205, RIGHT, font(16), LABEL, "%.0f kW" % kw)

    def _bar_frame(self, c):
        rect(c, 13, 176, 368, 24, TRACK_BG, 6)
        for x in (104, 196, 288):
            m = rect(c, x, 178, 2, 20, LABEL)
            m.set_style_bg_opa(kit.OPA._40, 0)

    def build_solar(self, p):
        c = self.s_card = kit.card(p, 402, 0, 398, 238, kit.SOL_BG, SOL_BORDER)
        kit.title(c, font(34), TITLE, "SOLAR")
        self.s_value = label(c, 15, 42, LEFT, font(48), NO_DATA, "-- kW")
        self.s_daily = label(c, 15, 94, LEFT, font(16), NO_DATA, "Today: -- kWh")
        self.s_mtd = label(c, 15, 118, LEFT, font(16), NO_DATA, "MTD: -- kWh")
        self.s_self = label(c, 15, 144, LEFT, font(16), NO_DATA, "--%", 45)
        self.s_self.set_long_mode(lv.label.LONG_MODE.CLIP)
        self.s_self_fill = kit.mini_bar(c, 65, 145, 383 - 65, 14, SOL_BORDER)
        self._bar_frame(c)
        self.s_target = rect(c, 15, 178, 0, 20, LOAD_FILL, 4)
        self.s_target.set_style_bg_opa(kit.OPA._0, 0)
        self.s_bar = rect(c, 15, 178, 0, 20, SOL_FILL, 4)
        kit.glow(self.s_bar, SOL_FILL)
        self.s_bar.set_style_bg_grad_color(kit.rgb(SOL_BORDER), 0)
        self.s_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        kit.outline(c, 13, 176, 368, 24, BAR_BORDER, 6)
        self.pk["sol"] = kit.PeakMarker(c, 176)
        self._ticks(c, self.sol_kw)

    def build_load(self, p):
        c = self.l_card = kit.card(p, 0, 242, 398, 238, kit.LOAD_BG, LOAD_BORDER)
        kit.title(c, font(34), TITLE, "LOAD")
        self.l_value = label(c, 15, 42, LEFT, font(48), NO_DATA, "-- kW")
        self.l_daily = label(c, 15, 94, LEFT, font(16), NO_DATA, "Today: -- kWh")
        self.l_daily_split = label(c, 383, 94, RIGHT, lv.font_load_split_16, NO_DATA, "")
        self.l_daily_split.set_recolor(True)
        self.l_mtd = label(c, 15, 118, LEFT, font(16), NO_DATA, "MTD: -- kWh")
        self.l_mtd_split = label(c, 383, 118, RIGHT, lv.font_load_split_16, NO_DATA, "")
        self.l_mtd_split.set_recolor(True)
        # source-split bar (solar / battery / grid share of today's load)
        rect(c, 13, 148, 368, 16, TRACK_BG, 6)
        self.l_split = []
        for col in (SOL_BORDER, BATT_BORDER, IMP_BORDER):
            self.l_split.append(rect(c, self.split_x, self.split_y, 0, self.split_h, col))
        self.l_split[0].set_style_radius(4, 0)
        self.l_split[2].set_style_radius(4, 0)
        kit.outline(c, 13, 148, 368, 16, BAR_BORDER, 6)
        self._bar_frame(c)
        self.l_seg = []
        for col in (LOAD_FILL, BATT_BORDER, IMP_BORDER):
            self.l_seg.append(rect(c, 15, 178, 0, 20, col))
        self.l_seg[0].set_style_radius(4, 0)
        self.l_seg[2].set_style_radius(4, 0)
        kit.outline(c, 13, 176, 368, 24, BAR_BORDER, 6)
        self.pk["load"] = kit.PeakMarker(c, 176)
        self._ticks(c, self.inv_kw)

    def build_grid(self, p):
        c = self.g_card = kit.card(p, 402, 242, 398, 238, kit.GRID_BG_IDLE, IMP_BORDER)
        kit.title(c, font(34), TITLE, "GRID")
        self.g_ongrid = kit.Badge(c, font(20), "", 383, 12, RIGHT)
        self.g_daily = label(c, 15, 94, LEFT, font(16), NO_DATA, "Today: In -- / Out -- kWh")
        self.g_mtd = label(c, 15, 118, LEFT, font(16), NO_DATA, "MTD: In -- / Out -- kWh")
        self.g_value = label(c, 15, 42, LEFT, font(48), NO_DATA, "-- kW")
        self.g_badge = kit.Badge(c, font(20), "GRID", 199, 144, CENTER)
        rect(c, 13, 176, 368, 24, TRACK_BG, 6)
        kit.outline(c, 13, 176, 368, 24, BAR_BORDER, 6)
        rect(c, 196, 178, 2, 20, NO_DATA)
        self.g_bar = rect(c, 196, 178, 0, 20, NO_DATA, 4)
        kit.glow(self.g_bar, NO_DATA)
        self.g_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        self.pk["gimp"] = kit.PeakMarker(c, 176)
        self.pk["gexp"] = kit.PeakMarker(c, 176)
        inv = "%.0f kW" % self.inv_kw
        label(c, 13, 205, LEFT, font(20), LABEL, inv)
        label(c, 197, 205, CENTER, font(20), LABEL, "0")
        label(c, 381, 205, RIGHT, font(20), LABEL, inv)

    def build_portrait(self, p):
        """480x800: four stacked 197 px bands (Solar, Battery, Load, Grid), smaller fonts, wider bars."""
        F = font
        # solar
        c = self.s_card = kit.card(p, 0, 0, 480, 197, kit.SOL_BG, SOL_BORDER)
        kit.title(c, F(24), LABEL, "SOLAR")
        self.s_value = label(c, 15, 34, LEFT, F(34), NO_DATA, "-- kW")
        self.s_daily = label(c, 15, 76, LEFT, F(16), NO_DATA, "Today: -- kWh")
        self.s_mtd = label(c, 15, 96, LEFT, F(16), NO_DATA, "MTD: -- kWh")
        self.s_self = label(c, 15, 116, LEFT, F(16), NO_DATA, "--%", 45)
        self.s_self.set_long_mode(lv.label.LONG_MODE.CLIP)
        self.sc_w = 465 - 65 - 4
        self.s_self_fill = kit.mini_bar(c, 65, 117, 465 - 65, 14, SOL_BORDER)
        self.s_x0, self.s_w, self.s_bar_y = 15, 446, 142
        rect(c, 13, 142, 450, 24, TRACK_BG, 6)
        for x in (125, 237, 349):
            m = rect(c, x, 144, 2, 20, LABEL)
            m.set_style_bg_opa(kit.OPA._40, 0)
        self.s_target = rect(c, 15, 144, 0, 20, LOAD_FILL, 4)
        self.s_target.set_style_bg_opa(kit.OPA._0, 0)
        self.s_bar = rect(c, 15, 144, 0, 20, SOL_FILL, 4)
        kit.glow(self.s_bar, SOL_FILL)
        self.s_bar.set_style_bg_grad_color(kit.rgb(SOL_BORDER), 0)
        self.s_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        kit.outline(c, 13, 142, 450, 24, BAR_BORDER, 6)
        self.pk["sol"] = kit.PeakMarker(c, 142)
        label(c, 13, 170, LEFT, F(14), LABEL, "0 kW")
        for x, f in ((126, .25), (238, .5), (350, .75)):
            label(c, x, 170, CENTER, F(14), LABEL, "%.1f" % (self.sol_kw * f))
        label(c, 463, 170, RIGHT, F(14), LABEL, "%.0f kW" % self.sol_kw)
        # status icons in the solar band's corner
        self.i_modbus = label(c, 385, 6, RIGHT, lv.font_mdi_24, NO_DATA, MDI_HOME_BATT)
        self.i_ntp = label(c, 425, 6, RIGHT, lv.font_mdi_24, NO_DATA, MDI_CLOCK)
        self.i_wifi = label(c, 465, 6, RIGHT, lv.font_mdi_24, NO_DATA, MDI_WIFI)
        for icon, cb in ((self.i_wifi, self.on_wifi_icon), (self.i_modbus, self.on_modbus_icon)):
            if cb:
                icon.add_flag(lv.obj.FLAG.CLICKABLE)
                icon.set_style_text_color(kit.rgb(kit.DOT_ACTIVE), lv.STATE.PRESSED)
                icon.add_event_cb(lambda e, f=cb: f(), lv.EVENT.CLICKED, None)
        self.paint_icons()
        # battery
        c = self.b_card = kit.card(p, 0, 201, 480, 197, kit.BATT_BG, BATT_BORDER)
        kit.title(c, F(24), LABEL, "BATTERY")
        self.b_temp = label(c, 465, 8, RIGHT, F(16), NO_DATA, "-- C")
        self.b_pct = label(c, 15, 34, LEFT, F(34), NO_DATA, "--%")
        self.b_time = label(c, 140, 48, LEFT, F(16), NO_DATA, "")
        iw, ih, ix, iy = 68, 120, 465 - 68, 38
        self.b_outline = kit.outline(c, ix, iy, iw, ih, NO_DATA, 8, 3)
        self.b_nub = rect(c, ix + (iw - 28) // 2, iy - 7, 28, 9, NO_DATA, 4)
        self.b_fill = rect(c, ix + 5, iy + 5, iw - 10, 0, NO_DATA, 4)
        self.b_icon = (ix + 5, iw - 10, iy + 5, ih - 10)
        self.b_kwh = label(c, ix + iw // 2, iy + ih + 3, CENTER, F(16), NO_DATA, "-- kWh")
        x2 = ix - 12
        self.b_center = (13 + x2) // 2
        self.b_half = self.b_center - 13 - 2
        self.b_bar_y = 142
        rect(c, 13, 142, x2 - 13, 24, TRACK_BG, 6)
        kit.outline(c, 13, 142, x2 - 13, 24, BAR_BORDER, 6)
        rect(c, self.b_center, 144, 2, 20, LABEL)
        self.b_bar = rect(c, self.b_center, 144, 0, 20, NO_DATA, 4)
        kit.glow(self.b_bar, NO_DATA)
        self.b_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        self.pk["bchg"] = kit.PeakMarker(c, 142)
        self.pk["bdis"] = kit.PeakMarker(c, 142)
        self.b_power = label(c, self.b_center, 82, CENTER, F(30), NO_DATA, "-- kW")
        self.b_badge = kit.Badge(c, F(16), "NO DATA", self.b_center, 114, CENTER)
        inv = "%.0f kW" % self.inv_kw
        label(c, 13, 170, LEFT, F(16), LABEL, inv)
        label(c, self.b_center, 170, CENTER, F(16), LABEL, "0")
        label(c, x2, 170, RIGHT, F(16), LABEL, inv)
        # load
        c = self.l_card = kit.card(p, 0, 402, 480, 197, kit.LOAD_BG, LOAD_BORDER)
        kit.title(c, F(24), LABEL, "LOAD")
        self.l_value = label(c, 15, 34, LEFT, F(34), NO_DATA, "-- kW")
        self.l_daily = label(c, 15, 76, LEFT, F(16), NO_DATA, "Today: -- kWh")
        self.l_daily_split = label(c, 465, 76, RIGHT, lv.font_load_split_16, NO_DATA, "")
        self.l_daily_split.set_recolor(True)
        self.l_mtd = label(c, 15, 96, LEFT, F(16), NO_DATA, "MTD: -- kWh")
        self.l_mtd_split = label(c, 465, 96, RIGHT, lv.font_load_split_16, NO_DATA, "")
        self.l_mtd_split.set_recolor(True)
        self.split_x, self.split_y, self.split_w, self.split_h = 15, 122, 446, 10
        rect(c, 13, 120, 450, 14, TRACK_BG, 6)
        self.l_split = []
        for col in (SOL_BORDER, BATT_BORDER, IMP_BORDER):
            self.l_split.append(rect(c, self.split_x, self.split_y, 0, self.split_h, col))
        self.l_split[0].set_style_radius(4, 0)
        self.l_split[2].set_style_radius(4, 0)
        kit.outline(c, 13, 120, 450, 14, BAR_BORDER, 6)
        self.l_x0, self.l_w, self.l_bar_y = 15, 446, 142
        rect(c, 13, 142, 450, 24, TRACK_BG, 6)
        for x in (125, 237, 349):
            m = rect(c, x, 144, 2, 20, LABEL)
            m.set_style_bg_opa(kit.OPA._40, 0)
        self.l_seg = []
        for col in (LOAD_FILL, BATT_BORDER, IMP_BORDER):
            self.l_seg.append(rect(c, 15, 144, 0, 20, col))
        self.l_seg[0].set_style_radius(4, 0)
        self.l_seg[2].set_style_radius(4, 0)
        kit.outline(c, 13, 142, 450, 24, BAR_BORDER, 6)
        self.pk["load"] = kit.PeakMarker(c, 142)
        label(c, 13, 170, LEFT, F(14), LABEL, "0 kW")
        for x, f in ((126, .25), (238, .5), (350, .75)):
            label(c, x, 170, CENTER, F(14), LABEL, "%.1f" % (self.inv_kw * f))
        label(c, 463, 170, RIGHT, F(14), LABEL, "%.0f kW" % self.inv_kw)
        # grid
        c = self.g_card = kit.card(p, 0, 603, 480, 197, kit.GRID_BG_IDLE, IMP_BORDER)
        kit.title(c, F(24), LABEL, "GRID")
        self.g_ongrid = kit.Badge(c, F(16), "", 465, 8, RIGHT)
        self.g_value = label(c, 15, 34, LEFT, F(34), NO_DATA, "-- kW")
        self.g_daily = label(c, 15, 76, LEFT, F(16), NO_DATA, "Today: In -- / Out -- kWh")
        self.g_mtd = label(c, 15, 96, LEFT, F(16), NO_DATA, "MTD: In -- / Out -- kWh")
        self.g_badge = kit.Badge(c, F(16), "GRID", 240, 116, CENTER)
        self.g_center, self.g_half, self.g_bar_y = 238, 223, 142
        rect(c, 13, 142, 450, 24, TRACK_BG, 6)
        kit.outline(c, 13, 142, 450, 24, BAR_BORDER, 6)
        rect(c, 238, 144, 2, 20, NO_DATA)
        self.g_bar = rect(c, 238, 144, 0, 20, NO_DATA, 4)
        kit.glow(self.g_bar, NO_DATA)
        self.g_bar.set_style_bg_grad_dir(lv.GRAD_DIR.HOR, 0)
        self.pk["gimp"] = kit.PeakMarker(c, 142)
        self.pk["gexp"] = kit.PeakMarker(c, 142)
        inv = "%.0f kW" % self.inv_kw
        label(c, 13, 170, LEFT, F(16), LABEL, inv)
        label(c, 238, 170, CENTER, F(16), LABEL, "0")
        label(c, 463, 170, RIGHT, F(16), LABEL, inv)

    def build_icons(self, p):
        """Modbus / NTP / WiFi status icons, top-right of the Solar quadrant (no header bar)."""
        self.i_modbus = label(self.s_card, 290 - 402 + 402, 12, RIGHT, lv.font_mdi_24, NO_DATA, MDI_HOME_BATT)
        self.i_ntp = label(self.s_card, 328, 12, RIGHT, lv.font_mdi_24, NO_DATA, MDI_CLOCK)
        self.i_wifi = label(self.s_card, 366, 12, RIGHT, lv.font_mdi_24, NO_DATA, MDI_WIFI)
        for icon, cb in ((self.i_wifi, self.on_wifi_icon), (self.i_modbus, self.on_modbus_icon)):
            if cb:
                icon.add_flag(lv.obj.FLAG.CLICKABLE)
                icon.set_style_text_color(kit.rgb(kit.DOT_ACTIVE), lv.STATE.PRESSED)
                icon.add_event_cb(lambda e, f=cb: f(), lv.EVENT.CLICKED, None)
        self.paint_icons()

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
            set_text(self.b_power, "+%.2f kW" % p, soc_col)
        elif p < -0.05:
            self.b_badge.set("DISCHARGING", DISCHARGE_RED)
            set_text(self.b_power, "%.2f kW" % -p, DISCHARGE_RED)
        else:
            self.b_badge.set("STANDBY", LABEL)
            set_text(self.b_power, "0.00 kW", LABEL)
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
        set_text(self.s_value, "%.2f kW" % pv, SOL_BORDER if gen else NO_DATA)
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
        set_text(self.l_value, "%.2f kW" % load, LOAD_BORDER)
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
            set_text(self.g_value, "%.2f kW" % exp, EXP_BORDER)
        elif importing:
            self.g_badge.set("IMPORTING", IMP_BORDER)
            set_text(self.g_value, "%.2f kW" % imp, IMP_BORDER)
        else:
            self.g_badge.set("STANDBY", LABEL)
            set_text(self.g_value, "0.00 kW", LABEL)
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
    self.refresh()
    self.update_covered()
    if not getattr(self, "cov_timer", None):
        self.cov_timer = lv.timer_create(lambda t: self.update_covered(), 60000, None)


def _on_hide(self):
    self.active = False


Dashboard.on_show = _on_show
Dashboard.on_hide = _on_hide
