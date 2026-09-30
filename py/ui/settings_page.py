"""System > Settings: Modbus target, plant sizing, billing cycle, time zone, screen blanking, night screen, backlight.
Fields save live (leaving the page autosaves; the keyboard's tick saves with a status line)."""
import lvgl as lv

from core import modbus, tz
from . import common as C

TIMEOUTS = (30, 60, 120, 300, 600)
TIMEOUT_LABELS = ("30s", "1m", "2m", "5m", "10m")
HOURS = ["%02d:00" % h for h in range(24)]
PRESETS = ("off", "gentle", "aggressive", "custom")
LBL_W = 130
ACCEPT_HOST = "0123456789."
ACCEPT_INT = "0123456789"
ACCEPT_TOKEN = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_."


class SettingsPage:
    def __init__(self, parent, app, shell):
        self.app, self.parent, self.shell = app, parent, shell
        self.tz_touched = False
        self.anchor = 20260101
        self.loading = False
        self.country_codes = []
        self.zone_list = []
        s = app.settings
        parent.set_style_bg_color(C.c(C.BG), 0)
        parent.set_style_bg_opa(lv.OPA.COVER, 0)
        parent.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        parent.set_style_pad_all(10, 0)
        parent.set_style_pad_row(6, 0)
        parent.remove_flag(lv.obj.FLAG.SCROLLABLE)
        C.label(parent, "Settings", 24, C.TEXT)
        main = lv.obj(parent)
        main.remove_style_all()
        main.set_size(lv.pct(100), lv.SIZE_CONTENT)
        main.set_flex_grow(1)
        main.set_flex_flow(lv.FLEX_FLOW.ROW)
        main.set_style_pad_column(16, 0)
        main.remove_flag(lv.obj.FLAG.SCROLLABLE)
        main.add_event_cb(lambda e: self.hide_kb(), lv.EVENT.CLICKED, None)
        self.left = self._col(main)
        self.right = self._col(main)
        L, R = self.left, self.right
        self.ip = self._field(L, "IP address", ACCEPT_HOST)
        self.port, self.port_row = self._field(L, "Port", ACCEPT_INT, True)
        self.inv = self._field(L, "Inverter (kW)", ACCEPT_HOST)
        self.sol = self._field(L, "Solar (kW)", ACCEPT_HOST)
        self.bday = self._field(L, "Billing Date", ACCEPT_INT)
        self.token = self._field(L, "OTA Key", ACCEPT_TOKEN)
        self.bmode = self._dd_row(L, "Billing Cycle", ["Calendar Month", "Fixed N-Day Cycle"], self.on_bmode)
        r = C.row(L)
        C.label(r, "Cycle Days", 16, C.MUTED).set_width(LBL_W)
        self.clen = lv.textarea(r)
        self._style_ta(self.clen, "0123456789")
        self.clen.set_size(60, 38)
        self.clen.set_max_length(3)
        self.anchor_btn = lv.button(r)
        self.anchor_btn.set_height(38)
        self.anchor_btn.set_flex_grow(1)
        self.anchor_btn.set_style_bg_color(C.c(C.FIELD_BG), 0)
        self.anchor_btn.set_style_bg_opa(lv.OPA.COVER, 0)
        self.anchor_btn.set_style_border_color(C.c(C.FIELD_BORDER), 0)
        self.anchor_btn.set_style_border_width(1, 0)
        self.anchor_btn.set_style_radius(6, 0)
        C.on_click(self.anchor_btn, self.pick_anchor)
        self.anchor_lbl = C.label(self.anchor_btn, "", 16, C.TEXT)
        self.anchor_lbl.center()
        self.country = self._dd_row(L, "Country", ["…"], self.on_country)
        self.region = self._dd_row(R, "Region", ["…"], self.on_region)
        r = C.row(R)
        self.blank_cb = C.checkbox(r, "Enable Screen Blank")
        self.blank_dd = C.dropdown(r, TIMEOUT_LABELS)
        self.night_cb = C.checkbox(C.row(R), "Enable Night Screen Off")
        self.night_start = self._dd_row(R, "Turn Off At", HOURS)
        self.night_end = self._dd_row(R, "Turn On At", HOURS)
        self.bl_cb = C.checkbox(C.row(R), "Backlight control", self.on_bl_enable)
        r = C.row(R)
        r.set_style_pad_right(16, 0)
        C.label(r, "Brightness", 16, C.MUTED).set_width(LBL_W)
        from core import backlight as bl
        self.slider = lv.slider(r)
        self.slider.set_flex_grow(1)
        self.slider.set_height(20)
        self.slider.set_range(bl.BL_ACTIVE_FLOOR, 100)
        self.slider.set_style_bg_color(C.c(C.FIELD_BG), lv.PART.MAIN)
        self.slider.set_style_bg_color(C.c(C.ACCENT), lv.PART.INDICATOR)
        self.slider.set_style_bg_color(C.c(C.ACCENT), lv.PART.KNOB)
        self.slider.add_event_cb(lambda e: self.on_slider(), lv.EVENT.RELEASED, None)
        for ev in (lv.EVENT.PRESSED,):
            self.slider.add_event_cb(lambda e: setattr(shell, "suppress", True), ev, None)
        for ev in (lv.EVENT.RELEASED, lv.EVENT.PRESS_LOST):
            self.slider.add_event_cb(lambda e: setattr(shell, "suppress", False), ev, None)
        self.preset = self._dd_row(R, "Night curve", ["Off", "Gentle", "Aggressive", "Custom (API)"], self.on_preset)
        self.orient = self._dd_row(R, "Orientation", ["Landscape", "Portrait"], self.on_orient)
        self.status = C.label(L, "", 16, 0xF87171)
        self.build_kb(parent)

    # ---- widgets ---------------------------------------------------------------------------------------
    def _col(self, parent):
        c = lv.obj(parent)
        c.remove_style_all()
        c.set_size(lv.pct(50), lv.pct(100))
        c.set_flex_grow(1)
        c.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        c.set_style_pad_row(6, 0)
        c.add_flag(lv.obj.FLAG.SCROLLABLE)
        c.add_flag(lv.obj.FLAG.USER_1)          # keep scrollable (vertical only)
        c.set_scroll_dir(lv.DIR.VER)
        c.set_scrollbar_mode(lv.SCROLLBAR_MODE.AUTO)
        c.add_event_cb(lambda e: self.hide_kb(), lv.EVENT.CLICKED, None)
        return c

    def _style_ta(self, ta, accepted):
        ta.set_one_line(True)
        ta.set_accepted_chars(accepted)
        C.style_textarea(ta)
        ta.add_event_cb(lambda e: self.show_kb(ta), lv.EVENT.FOCUSED, None)

    def _field(self, parent, name, accepted, with_reset=False):
        r = C.row(parent)
        C.label(r, name, 16, C.MUTED).set_width(LBL_W)
        ta = lv.textarea(r)
        ta.set_size(lv.pct(100), 38)
        ta.set_flex_grow(1)
        self._style_ta(ta, accepted)
        if not with_reset:
            return ta
        btn = lv.button(r)
        btn.set_size(36, 38)
        btn.set_style_bg_color(C.c(C.FIELD_BG), 0)
        btn.set_style_bg_opa(lv.OPA.COVER, 0)
        btn.set_style_border_color(C.c(C.FIELD_BORDER), 0)
        btn.set_style_border_width(1, 0)
        btn.set_style_radius(6, 0)
        btn.add_flag(lv.obj.FLAG.HIDDEN)
        ic = lv.label(btn)
        ic.set_text(lv.SYMBOL.REFRESH)
        ic.set_style_text_color(C.c(C.TEXT), 0)
        ic.center()
        C.on_click(btn, lambda: ta.set_text(str(modbus.DEFAULT_PORT)))
        ta.add_event_cb(lambda e: btn.remove_flag(lv.obj.FLAG.HIDDEN) if ta.get_text() != str(modbus.DEFAULT_PORT)
                        else btn.add_flag(lv.obj.FLAG.HIDDEN), lv.EVENT.VALUE_CHANGED, None)
        return ta, btn

    def _dd_row(self, parent, name, options, cb=None):
        r = C.row(parent)
        C.label(r, name, 16, C.MUTED).set_width(LBL_W)
        return C.dropdown(r, options, cb)

    def build_kb(self, parent):
        p = self.kb_panel = lv.obj(parent)
        p.add_flag(lv.obj.FLAG.IGNORE_LAYOUT)
        p.set_size(lv.pct(50), lv.pct(88))
        p.align(lv.ALIGN.RIGHT_MID, 0, 0)
        p.set_style_bg_color(C.c(C.CARD), 0)
        p.set_style_bg_opa(lv.OPA.COVER, 0)
        p.set_style_border_color(C.c(C.FIELD_BORDER), 0)
        p.set_style_border_width(1, 0)
        p.set_style_radius(8, 0)
        p.set_style_pad_all(6, 0)
        p.set_style_pad_top(44, 0)
        p.remove_flag(lv.obj.FLAG.SCROLLABLE)
        p.add_flag(lv.obj.FLAG.HIDDEN)
        close = lv.button(p)
        close.align(lv.ALIGN.TOP_RIGHT, 0, -38)
        close.set_size(44, 36)
        close.set_style_bg_color(C.c(C.FIELD_BG), 0)
        close.set_style_bg_opa(lv.OPA.COVER, 0)
        close.set_style_border_color(C.c(C.FIELD_BORDER), 0)
        close.set_style_border_width(1, 0)
        close.set_style_radius(6, 0)
        C.on_click(close, self.hide_kb)
        x = lv.label(close)
        x.set_text(lv.SYMBOL.CLOSE)
        x.set_style_text_color(C.c(C.TEXT), 0)
        x.center()
        self.kb = C.num_keyboard(p, self.ip)
        self.kb.set_size(lv.pct(100), lv.pct(100))
        self.kb.align(lv.ALIGN.TOP_LEFT, 0, 0)
        self.kb.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
        self.kb.set_style_pad_all(0, lv.PART.MAIN)
        C.on_click(self.kb, lambda: self.save(True), lv.EVENT.READY)

    def show_kb(self, ta):
        if getattr(self, "loading", False):
            return
        if ta is self.token:
            self.kb.set_mode(lv.keyboard.MODE.TEXT_LOWER)
        else:
            self.kb.set_mode(lv.keyboard.MODE.NUMBER)
        self.kb.set_textarea(ta)
        self.kb_panel.remove_flag(lv.obj.FLAG.HIDDEN)

    def hide_kb(self):
        self.kb_panel.add_flag(lv.obj.FLAG.HIDDEN)
        self.kb.set_textarea(None) if False else None

    # ---- lifecycle ---------------------------------------------------------------------------------------
    def on_show(self):
        self.reload()

    def on_hide(self):
        self.hide_kb()
        for dd in (self.country, self.region, self.blank_dd, self.night_start, self.night_end, self.bmode,
                   self.preset, self.orient):
            if dd.is_open():
                dd.close()
        self.save(False)

    def reload(self):
        self.loading = True
        s = self.app.settings
        svc = self.app.services
        self.ip.set_text(s.get("modbus.ip", modbus.DEFAULT_IP))
        self.port.set_text(str(s.get("modbus.port", modbus.DEFAULT_PORT)))
        self.port_row.add_flag(lv.obj.FLAG.HIDDEN) if int(s.get("modbus.port", 502)) == 502 else self.port_row.remove_flag(lv.obj.FLAG.HIDDEN)
        self.inv.set_text("%g" % float(s.get("sizing.inverter_kw", 25.0)))
        self.sol.set_text("%g" % float(s.get("sizing.solar_kw", 25.0)))
        self.bday.set_text(str(int(s.get("billing.day", 1))))
        self.token.set_text(s.get("ota.token", "") or "")
        self.bmode.set_selected(int(s.get("billing.mode", 0)))
        self.clen.set_text(str(int(s.get("billing.cycle_len", 28))))
        self.anchor = int(s.get("billing.anchor", 20260101))
        self.paint_anchor()
        self.update_billing_states()
        # time zone
        code, zone, _px, _lb = tz.selection()
        codes = tz.countries()
        self.country_codes = [c for c, _n in codes]
        self.country.set_options("\n".join(n for _c, n in codes))
        if code in self.country_codes:
            self.country.set_selected(self.country_codes.index(code))
        self.fill_zones(code, zone)
        self.tz_touched = False
        blank, bl = svc["blank"], svc["backlight"]
        C.set_checked(self.blank_cb, blank.enabled)
        self.blank_dd.set_selected(TIMEOUTS.index(blank.timeout_s) if blank.timeout_s in TIMEOUTS else 2)
        C.set_checked(self.night_cb, blank.night_enabled)
        self.night_start.set_selected(blank.night_start // 60)
        self.night_end.set_selected(blank.night_end // 60)
        C.set_checked(self.bl_cb, bl.enabled)
        self.preset.set_selected(PRESETS.index(bl.preset) if bl.preset in PRESETS else 0)
        self.slider.set_value(max(bl.resolve()[0], 3), lv.ANIM.OFF)
        self.update_bl_states()
        self.orient.set_selected(1 if s.get("orientation", "landscape") == "portrait" else 0)
        self.status.set_text("")
        self.loading = False

    def fill_zones(self, code, zone=None):
        zs = tz.zones(code) if code in self.country_codes else []
        self.zone_list = zs
        self.region.set_options("\n".join(z[2] for z in zs) or "-")
        idx = 0
        for i, z in enumerate(zs):
            if z[0] == zone:
                idx = i
        self.region.set_selected(idx)

    # ---- handlers ---------------------------------------------------------------------------------------
    def on_country(self):
        if self.loading:
            return
        self.tz_touched = True
        self.fill_zones(self.country_codes[self.country.get_selected()])
        self.hide_kb()

    def on_region(self):
        if not self.loading:
            self.tz_touched = True
        self.hide_kb()

    def on_bmode(self):
        self.update_billing_states()
        self.hide_kb()

    def update_billing_states(self):
        fixed = self.bmode.get_selected() == 1
        for w, on in ((self.bday, not fixed), (self.clen, fixed), (self.anchor_btn, fixed)):
            if on:
                w.remove_state(lv.STATE.DISABLED)
            else:
                w.add_state(lv.STATE.DISABLED)

    def paint_anchor(self):
        a = self.anchor
        self.anchor_lbl.set_text("Start: %04d-%02d-%02d" % (a // 10000, a // 100 % 100, a % 100))

    def on_bl_enable(self):
        self.update_bl_states()
        self.hide_kb()

    def update_bl_states(self):
        on = C.checked(self.bl_cb)
        for w in (self.slider, self.preset):
            if on:
                w.remove_state(lv.STATE.DISABLED)
            else:
                w.add_state(lv.STATE.DISABLED)

    def on_slider(self):
        bl = self.app.services["backlight"]
        if bl.enabled:
            bl.set_manual(self.slider.get_value())

    def on_preset(self):
        if self.loading:
            return
        bl = self.app.services["backlight"]
        name = PRESETS[self.preset.get_selected()]
        if name == "custom" and not bl.custom:
            self.preset.set_selected(PRESETS.index(bl.preset))
            self.status.set_text("Custom curves are set through the API (POST /api/backlight/curve)")
            return
        bl.set_config(preset=name)
        self.hide_kb()

    def on_orient(self):
        if self.loading:
            return
        portrait = self.orient.get_selected() == 1
        cur = self.app.settings.get("orientation", "landscape") == "portrait"
        if portrait == cur:
            return
        C.confirm("Switch Screen Orientation?", "Switches the display to %s and restarts the device immediately. "
                  "No settings or logged data will be lost." % ("Portrait" if portrait else "Landscape"),
                  lambda: self.apply_orientation(portrait), "Switch & Restart")
        self.orient.set_selected(1 if cur else 0)

    def apply_orientation(self, portrait):
        from core import system
        self.app.settings.set("orientation", "portrait" if portrait else "landscape")
        system.reboot(self.app, "Orientation change")

    def pick_anchor(self):
        ov = C.overlay()
        p = lv.obj(ov)
        p.set_size(420, lv.SIZE_CONTENT)
        p.center()
        p.set_style_bg_color(C.c(C.CARD), 0)
        p.set_style_bg_opa(lv.OPA.COVER, 0)
        p.set_style_radius(14, 0)
        p.set_style_pad_all(16, 0)
        p.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        p.set_style_pad_row(12, 0)
        p.remove_flag(lv.obj.FLAG.SCROLLABLE)
        C.label(p, "Cycle Start Date", 24, C.TEXT)
        C.label(p, "Any date a real billing cycle started on.", 16, C.MUTED)
        rr = C.row(p, 130, 10)
        y0 = 2020
        a = self.anchor
        ry = self._roller(rr, "\n".join(str(y) for y in range(y0, y0 + 16)), a // 10000 - y0)
        rm = self._roller(rr, "\n".join("%02d" % m for m in range(1, 13)), a // 100 % 100 - 1)
        rd = self._roller(rr, "\n".join("%02d" % d for d in range(1, 32)), a % 100 - 1)
        b = C.row(p, 44, 12)
        b.set_flex_align(lv.FLEX_ALIGN.END, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)

        def ok():
            y, m, d = y0 + ry.get_selected(), rm.get_selected() + 1, rd.get_selected() + 1
            from core import timeutil as T
            self.anchor = y * 10000 + m * 100 + min(d, T.days_in_month(y, m))
            self.paint_anchor()
            ov.delete()
        C.button(b, "Cancel", C.CARD, C.TEXT, ov.delete).set_style_bg_color(C.c(C.FIELD_BORDER), 0)
        C.button(b, "OK", C.ACCENT, C.ACCENT_TEXT, ok)

    def _roller(self, parent, opts, sel):
        r = lv.roller(parent)
        r.set_options(opts, lv.roller.MODE.NORMAL)
        r.set_visible_row_count(3)
        r.set_selected(sel, lv.ANIM.OFF)
        r.set_flex_grow(1)
        r.set_style_bg_color(C.c(C.FIELD_BG), 0)
        r.set_style_text_color(C.c(C.TEXT), 0)
        r.set_style_border_color(C.c(C.FIELD_BORDER), 0)
        r.set_style_bg_color(C.c(C.ACCENT), lv.PART.SELECTED)
        r.set_style_text_color(C.c(C.BG), lv.PART.SELECTED)
        return r

    # ---- save --------------------------------------------------------------------------------------------
    def fail(self, msg, show):
        if show:
            self.status.set_style_text_color(C.c(0xF87171), 0)
            self.status.set_text(msg)
        return False

    def save(self, show_status):
        if self.loading:
            return True
        s = self.app.settings
        svc = self.app.services
        ip = self.ip.get_text().strip()
        parts = ip.split(".")
        if not ip or ip == modbus.DEFAULT_IP:
            if ip == modbus.DEFAULT_IP and not show_status:
                pass
            else:
                return self.fail("IP address can't be blank", show_status)
        elif len(parts) != 4 or not all(p.isdigit() and int(p) < 256 for p in parts):
            return self.fail("Enter a full IPv4 address", show_status)
        pt = self.port.get_text()
        port = int(pt) if pt else modbus.DEFAULT_PORT
        if not 0 < port < 65536:
            return self.fail("Port must be 1-65535", show_status)
        try:
            inv = float(self.inv.get_text() or 25)
            sol = float(self.sol.get_text() or 25)
        except ValueError:
            return self.fail("Sizes must be numbers", show_status)
        if not 0.1 <= inv <= 100:
            return self.fail("Inverter size must be 1-100kW", show_status)
        if not 0.1 <= sol <= 100:
            return self.fail("Solar size must be 1-100kW", show_status)
        bd = int(self.bday.get_text() or 1)
        if not 1 <= bd <= 31:
            return self.fail("Billing date must be 1-31", show_status)
        cl = int(self.clen.get_text() or 28)
        if not 1 <= cl <= 365:
            return self.fail("Cycle days must be 1-365", show_status)
        tok = self.token.get_text().strip()
        if tok:
            s.set("ota.token", tok)
        resized = (float(s.get("sizing.inverter_kw", 25.0)), float(s.get("sizing.solar_kw", 25.0))) != (inv, sol)
        s.set("sizing.inverter_kw", inv)
        s.set("sizing.solar_kw", sol)
        s.set("billing.day", bd)
        s.set("billing.mode", self.bmode.get_selected())
        s.set("billing.cycle_len", cl)
        s.set("billing.anchor", self.anchor)
        svc["monthly"].apply_settings()
        if resized and svc.get("dashboard"):
            svc["dashboard"].sizing_changed = True
        blank = svc["blank"]
        blank.set_blank(C.checked(self.blank_cb), TIMEOUTS[self.blank_dd.get_selected()])
        blank.set_night(C.checked(self.night_cb), self.night_start.get_selected() * 60, self.night_end.get_selected() * 60)
        svc["backlight"].set_config(enabled=C.checked(self.bl_cb))
        if show_status or self.tz_touched:
            zi = self.region.get_selected()
            if self.zone_list and zi < len(self.zone_list):
                code = self.country_codes[self.country.get_selected()]
                z = self.zone_list[zi]
                tz.select(code, z[0], z[1], z[2])
            self.tz_touched = False
        old = (s.get("modbus.ip", modbus.DEFAULT_IP), int(s.get("modbus.port", modbus.DEFAULT_PORT)))
        if ip and (ip, port) != old:
            s.set("modbus.ip", ip)
            s.set("modbus.port", port)
            s.delete("modbus.skipped")
            svc["poller"].apply_config()
        if show_status:
            self.status.set_style_text_color(C.c(0x4ADE80), 0)
            self.status.set_text("Saved " + lv.SYMBOL.OK)
        return True
