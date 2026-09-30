"""WiFi manager: status + MAC, scan list, tap a network to enter its password, Forget. Used as the System > WiFi tab
and (with ap_ssid set) as the full-screen provisioning screen while the setup access point is up."""
import asyncio

import lvgl as lv

from . import common as C

CONNECTING_TIMEOUT_MS = 30000


def quality(rssi):
    return "Excellent" if rssi >= -50 else "Good" if rssi >= -60 else "Fair" if rssi >= -70 else "Weak"


class WifiPage:
    def __init__(self, parent, app, on_connected=None):
        self.app, self.wifi = app, app.services["wifi"]
        self.on_connected = on_connected
        self.results = []
        self.scan_msg = "Scanning..."
        self.connecting = ""
        self.connecting_ms = 0
        self.scanning = False
        self.ov = None
        self.built_key = None
        parent.set_style_bg_color(C.c(C.BG), 0)
        parent.set_style_bg_opa(lv.OPA.COVER, 0)
        parent.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        parent.set_style_pad_all(12, 0)
        parent.set_style_pad_row(8, 0)
        top = lv.obj(parent)
        top.remove_style_all()
        top.set_size(lv.pct(100), lv.SIZE_CONTENT)
        top.set_flex_flow(lv.FLEX_FLOW.ROW)
        top.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        col = lv.obj(top)
        col.remove_style_all()
        col.set_width(lv.pct(58))
        col.set_height(lv.SIZE_CONTENT)
        col.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.status = C.label(col, "", 24, C.TEXT, wrap_w=440)
        C.label(col, "MAC: %s" % self.wifi.mac, 16, C.MUTED)
        act = lv.obj(top)
        act.remove_style_all()
        act.set_width(lv.pct(40))
        act.set_height(lv.SIZE_CONTENT)
        act.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
        act.set_flex_align(lv.FLEX_ALIGN.END, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        act.set_style_pad_column(8, 0)
        C.button(act, "Scan", C.ACCENT, C.ACCENT_TEXT, self.rescan)
        self.forget_btn = C.button(act, "Forget network", C.DANGER, C.ACCENT_TEXT, self.forget)
        self.list = lv.obj(parent)
        self.list.set_width(lv.pct(100))
        self.list.set_height(0)
        self.list.set_flex_grow(1)
        self.list.add_flag(lv.obj.FLAG.SCROLLABLE)
        self.list.add_flag(lv.obj.FLAG.USER_1)          # keep scrollable (vertical only)
        self.list.set_scroll_dir(lv.DIR.VER)
        self.list.set_style_bg_opa(lv.OPA.TRANSP, 0)
        self.list.set_style_border_width(0, 0)
        self.list.set_style_pad_all(0, 0)
        self.list.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.list.set_style_pad_row(6, 0)
        self.timer = lv.timer_create(self.tick, 1000, None)
        self.tick(None)

    # ---- data -----------------------------------------------------------------------------------------
    def on_show(self):
        self.rescan()

    def rescan(self):
        if self.scanning:
            return
        self.scanning = True
        self.scan_msg = "Scanning..."
        self.populate()
        asyncio.create_task(self._scan())

    async def _scan(self):
        try:
            self.results = await self.wifi.scan()
            self.scan_msg = None if self.results else "No networks found"
        except Exception as e:
            self.results, self.scan_msg = [], "Scan failed - see the log"
            self.app.log.warn("wifi ui: scan failed: %r" % (e,))
        self.scanning = False
        self.populate()

    def populate(self):
        self.list.clean()
        cur = self.wifi.ssid if self.wifi.connected else ""
        if not self.results:
            row = self._row()
            l = C.label(row, self.scan_msg or "", 16, C.MUTED)
            l.center()
            return
        for ssid, rssi, secure in self.results:
            conn = ssid == cur
            row = self._row()
            if conn:
                row.set_style_bg_color(C.c(0x0F2942), 0)
                row.set_style_border_color(C.c(C.ACCENT), 0)
                row.set_style_border_width(2, 0)
            row.add_flag(lv.obj.FLAG.CLICKABLE)
            row.set_style_bg_color(C.c(0x334155), lv.STATE.PRESSED)
            C.label(row, ssid + ("  (connected)" if conn else "  (secured)" if secure else "  (open)"),
                    20 if conn else 16, C.ACCENT if conn else C.TEXT)
            C.label(row, "%d dBm  (%s)" % (rssi, quality(rssi)), 16, C.TEXT if conn else C.MUTED)
            C.on_click(row, lambda s=ssid, sec=secure: self.pick(s, sec))

    def _row(self):
        row = lv.obj(self.list)
        row.set_size(lv.pct(100), 58)
        row.set_style_bg_color(C.c(C.CARD), 0)
        row.set_style_bg_opa(lv.OPA.COVER, 0)
        row.set_style_border_width(0, 0)
        row.set_style_radius(8, 0)
        row.set_style_pad_hor(14, 0)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        row.remove_flag(lv.obj.FLAG.SCROLLABLE)
        return row

    # ---- status ---------------------------------------------------------------------------------------
    def close(self):
        if self.timer:
            self.timer.delete()
            self.timer = None

    def tick(self, t):
        w = self.wifi
        if w.connected:
            self.connecting = ""
            text = "IP: %s" % w.ip
            self.forget_btn.remove_flag(lv.obj.FLAG.HIDDEN)
            if self.on_connected:
                cb, self.on_connected = self.on_connected, None
                cb()
        elif self.connecting:
            text = "Connecting to %s..." % self.connecting
            self.forget_btn.add_flag(lv.obj.FLAG.HIDDEN)
            import time
            if time.ticks_diff(time.ticks_ms(), self.connecting_ms) > CONNECTING_TIMEOUT_MS:
                self.connecting = ""
        elif w.mode == "ap":
            text = "Not connected. Join \"%s\" from your phone, or pick a network below." % w.ap_ssid
            self.forget_btn.add_flag(lv.obj.FLAG.HIDDEN)
        else:
            text = "Not connected. Pick a network below."
            self.forget_btn.add_flag(lv.obj.FLAG.HIDDEN)
        if self.status.get_text() != text:
            self.status.set_text(text)
        key = (w.ssid if w.connected else "")
        if key != self.built_key and self.results:
            self.built_key = key
            self.populate()

    def forget(self):
        C.confirm("Forget network", "Forget the saved WiFi credentials? The device will restart into setup mode.",
                  self.wifi.forget, "Forget", danger=True)

    # ---- password entry ---------------------------------------------------------------------------
    def pick(self, ssid, secure):
        if not secure:
            self.join(ssid, "")
            return
        self.password_overlay(ssid)

    def join(self, ssid, pw):
        import time
        self.connecting, self.connecting_ms = ssid, time.ticks_ms()
        self.wifi.connect(ssid, pw)
        self.app.log.info("wifi ui: connecting to %s" % ssid)

    def password_overlay(self, ssid):
        ov = self.ov = C.overlay()
        ov.set_style_bg_opa(lv.OPA.COVER, 0)
        ov.set_style_bg_color(C.c(C.BG), 0)
        ov.set_style_pad_all(12, 0)
        ov.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        ov.set_style_pad_row(8, 0)
        head = lv.obj(ov)
        head.remove_style_all()
        head.set_size(lv.pct(100), lv.SIZE_CONTENT)
        head.set_flex_flow(lv.FLEX_FLOW.ROW)
        head.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        C.label(head, ssid, 24, C.TEXT)
        btns = lv.obj(head)
        btns.remove_style_all()
        btns.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
        btns.set_flex_flow(lv.FLEX_FLOW.ROW)
        btns.set_style_pad_column(8, 0)
        C.button(btns, "Cancel", C.CARD, C.TEXT, ov.delete)
        ta = lv.textarea(ov)
        ta.set_one_line(True)
        ta.set_password_mode(True)
        ta.set_placeholder_text("Password (leave blank for open networks)")
        ta.set_width(lv.pct(100))
        ta.set_style_text_font(lv.font_montserrat_20, 0)
        C.style_textarea(ta)
        cb = lv.checkbox(ov)
        cb.set_text("Show key")
        cb.set_style_text_color(C.c(C.TEXT), 0)
        cb.add_event_cb(lambda e: ta.set_password_mode(not cb.get_state() & lv.STATE.CHECKED), lv.EVENT.VALUE_CHANGED, None)
        kb = lv.keyboard(ov)
        kb.set_width(lv.pct(100))
        kb.set_flex_grow(1)
        kb.set_textarea(ta)
        C.style_keyboard(kb)

        def go(e=None):
            pw = ta.get_text()
            ov.delete()
            self.ov = None
            self.join(ssid, pw)
        C.on_click(kb, go, lv.EVENT.READY)
        return ov
