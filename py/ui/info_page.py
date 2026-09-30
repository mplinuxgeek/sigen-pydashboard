"""System > Info: firmware, chip and memory, inverter identity, NTP diagnostics, plus Clear History / Factory Reset / Reboot."""
import gc
import sys
import time

import lvgl as lv

from core import timeutil as T, tz
from . import common as C


def _card(parent, w):
    o = lv.obj(parent)
    o.set_size(w, lv.SIZE_CONTENT)
    o.set_style_bg_color(C.c(C.CARD), 0)
    o.set_style_bg_opa(lv.OPA.COVER, 0)
    o.set_style_border_color(C.c(0x334155), 0)
    o.set_style_border_width(2, 0)
    o.set_style_radius(12, 0)
    o.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    o.set_style_pad_all(6, 0)
    o.set_style_pad_row(4, 0)
    o.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return o


class InfoPage:
    def __init__(self, parent, app, shell):
        self.app, self.parent = app, parent
        parent.set_style_bg_color(C.c(C.BG), 0)
        parent.set_style_bg_opa(lv.OPA.COVER, 0)
        parent.remove_flag(lv.obj.FLAG.SCROLLABLE)
        C.label(parent, "Info", 24, C.TEXT).set_pos(10, 8)
        cols = lv.obj(parent)
        cols.remove_style_all()
        cols.set_size(lv.pct(100), lv.SIZE_CONTENT)
        cols.set_pos(0, 44)
        cols.set_style_pad_hor(10, 0)
        import board
        cols.set_flex_flow(lv.FLEX_FLOW.COLUMN if board.portrait else lv.FLEX_FLOW.ROW)
        cols.set_style_pad_column(10, 0)
        cols.set_style_pad_row(6, 0)
        cols.remove_flag(lv.obj.FLAG.SCROLLABLE)
        colw = lv.pct(100) if board.portrait else lv.pct(49)
        left = _card(cols, colw)
        right_stack = lv.obj(cols)
        right_stack.remove_style_all()
        right_stack.set_size(colw, lv.SIZE_CONTENT)
        right_stack.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        right_stack.set_style_pad_row(6, 0)
        inv = _card(right_stack, lv.pct(100))
        ntp = _card(right_stack, lv.pct(100))
        self.L = {}

        def group(card, title, keys, wrap=False):
            C.label(card, title, 20, C.ACCENT)
            for k in keys:
                l = C.label(card, "", 20, C.MUTED)
                if wrap:
                    l.set_width(lv.pct(100))
                    l.set_long_mode(lv.label.LONG_MODE.WRAP)
                self.L[k] = l
        group(left, "System", ("version", "python", "uptime", "chip", "storage", "sram", "psram", "pyheap"))
        group(inv, "Inverter", ("model", "serial"), wrap=True)
        group(ntp, "NTP", ("ntp_status", "ntp_server", "ntp_last", "ntp_count", "ntp_time"))
        btns = lv.obj(parent)
        btns.remove_style_all()
        btns.set_size(lv.pct(100), lv.SIZE_CONTENT)
        btns.set_flex_flow(lv.FLEX_FLOW.ROW)
        btns.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        btns.set_style_pad_column(16, 0)
        btns.align(lv.ALIGN.BOTTOM_MID, 0, -30)
        C.button(btns, "Clear History", C.DANGER, C.ACCENT_TEXT, self.clear_history)
        C.button(btns, "Factory Reset", C.DANGER, C.ACCENT_TEXT, self.factory_reset)
        C.button(btns, "Reboot", C.ACCENT, C.ACCENT_TEXT, self.reboot)
        self.timer = None

    def on_show(self):
        self.refresh()
        if self.timer is None:
            self.timer = lv.timer_create(lambda t: self.refresh(), 1000, None)
        self.timer.resume()

    def on_hide(self):
        if self.timer:
            self.timer.pause()

    def refresh(self):
        import esp32
        from core import api
        L = self.L
        svc = self.app.services
        up = time.ticks_ms() // 1000

        def heap(cap):
            f = t = 0
            for h in esp32.idf_heap_info(cap):
                t += h[0]
                f += h[1]
            return t, f
        st, sf = heap(1 << 11)
        pt, pf = heap(1 << 10)
        L["version"].set_text("Version: %s" % api.VERSION)
        L["python"].set_text("MicroPython %s" % ".".join(str(x) for x in sys.implementation.version[:3]))
        L["uptime"].set_text("Uptime: %dh %dm" % (up // 3600, up % 3600 // 60))
        L["chip"].set_text("ESP32-S3, 2 cores @ %d MHz" % (__import__("machine").freq() // 1000000))
        L["storage"].set_text("Flash: 8 MB | PSRAM: 8 MB")
        L["sram"].set_text("SRAM free: %d KB" % (sf // 1024))
        L["psram"].set_text("PSRAM free: %d KB" % (pf // 1024))
        L["pyheap"].set_text("Python heap free: %d KB" % (gc.mem_free() // 1024))
        s = svc["state"]
        L["model"].set_text("Model: %s" % (s.model or "--"))
        L["serial"].set_text("Serial: %s" % (s.serial or "--"))
        n = svc["ntp"]
        L["ntp_status"].set_text("Synced: %s (%s)" % ("Yes" if n.synced else "No", n.status_text()))
        L["ntp_server"].set_text("Server: %s" % (n.server or "--"))
        if n.last_ok is None:
            L["ntp_last"].set_text("Last sync: never")
        else:
            ago = time.ticks_diff(time.ticks_ms(), n.last_ok) // 1000
            L["ntp_last"].set_text("Last sync: %s ago" % ("%dh %dm" % (ago // 3600, ago % 3600 // 60) if ago >= 3600 else
                                                          "%dm %ds" % (ago // 60, ago % 60) if ago >= 60 else "%ds" % ago))
        L["ntp_count"].set_text("Sync count: %d" % n.sync_count)
        t = tz.local()
        L["ntp_time"].set_text("Time: %02d:%02d:%02d %s" % (t[3], t[4], t[5], tz.abbrev()) if (n.synced and t) else "Time: --")

    def clear_history(self):
        C.confirm("Clear History?", "Deletes every recorded data point for the graphs. WiFi and Modbus settings are kept. "
                  "This can't be undone.", self.app.services["history"].clear, "Clear History", danger=True)

    def factory_reset(self):
        from core import system
        C.confirm("Factory Reset?", "Erases WiFi credentials, Modbus settings, history, monthly totals and every other "
                  "setting, then restarts into first-run setup. This can't be undone.",
                  lambda: system.factory_reset(self.app), "Factory Reset", danger=True)

    def reboot(self):
        from core import system
        C.confirm("Reboot Device?", "Restarts the panel immediately. No settings or logged data will be lost.",
                  lambda: system.reboot(self.app, "System UI Reboot button"), "Reboot")
