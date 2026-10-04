"""System > Info: firmware, chip and memory, inverter identity, NTP diagnostics, plus Clear History / Factory Reset / Reboot."""
import gc
import sys
import time

import lvgl as lv

from core import tz
from core.fmt import ago, duration
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
        group(left, "System", ("version", "ip", "update", "python", "uptime", "reset", "signal", "sram", "psram", "pyheap"))
        group(inv, "Inverter", ("model", "serial", "lastread", "link"), wrap=True)
        group(ntp, "NTP", ("ntp_status", "ntp_server", "ntp_last", "ntp_count", "ntp_time"))
        btns = lv.obj(parent)
        btns.remove_style_all()
        btns.set_size(lv.pct(100), lv.SIZE_CONTENT)
        btns.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)                  # two rows in portrait
        btns.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        btns.set_style_pad_column(16, 0)
        btns.set_style_pad_row(8, 0)
        btns.align(lv.ALIGN.BOTTOM_MID, 0, -30)
        C.button(btns, "Clear History", C.DANGER, C.ACCENT_TEXT, self.clear_history)
        C.button(btns, "Factory Reset", C.DANGER, C.ACCENT_TEXT, self.factory_reset)
        C.button(btns, "Reboot", C.ACCENT, C.ACCENT_TEXT, self.reboot)
        self.upd_btn = C.button(btns, "Check Updates", C.CARD, C.TEXT, self.update_clicked)
        self.upd_lbl = self.upd_btn.get_child(0)
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
        w = svc["wifi"]
        L["ip"].set_text("IP: %s (%s)" % (w.ip or "--", "setup hotspot" if w.mode == "ap" else (w.ssid or "not connected")))
        self.refresh_update(L)
        L["python"].set_text("MicroPython %s" % ".".join(str(x) for x in sys.implementation.version[:3]))
        L["uptime"].set_text("Uptime: %s" % duration(up))
        import machine
        names = {machine.PWRON_RESET: "power-on", machine.HARD_RESET: "hard reset", machine.WDT_RESET: "restart or watchdog",
                 machine.SOFT_RESET: "software"}
        L["reset"].set_text("Last reset: %s" % names.get(machine.reset_cause(), "unknown"))
        w = svc["wifi"]
        L["signal"].set_text("WiFi signal: %s" % ("%d dBm" % w.rssi() if w.connected else "--"))
        L["sram"].set_text("SRAM free: %d KB" % (sf // 1024))
        L["psram"].set_text("PSRAM free: %d KB" % (pf // 1024))
        L["pyheap"].set_text("Python heap free: %d KB" % (gc.mem_free() // 1024))
        s = svc["state"]
        L["model"].set_text("Model: %s" % (s.model or "--"))
        L["serial"].set_text("Serial: %s" % (s.serial or "--"))
        if s.last_commit_ms is None:
            L["lastread"].set_text("Last reading: none yet")
        else:
            L["lastread"].set_text("Last reading: %s" % ago(time.ticks_diff(time.ticks_ms(), s.last_commit_ms) // 1000))
        fails = svc["poller"].fail_streak
        L["link"].set_text("Link: %s" % ("OK" if s.alive and not fails else "failing (%d)" % fails if fails else "connecting"))
        n = svc["ntp"]
        L["ntp_status"].set_text("Synced: %s (%s)" % ("Yes" if n.synced else "No", n.status_text()))
        L["ntp_server"].set_text("Server: %s" % (n.server or "--"))
        if n.last_ok is None:
            L["ntp_last"].set_text("Last sync: never")
        else:
            L["ntp_last"].set_text("Last sync: %s" % ago(time.ticks_diff(time.ticks_ms(), n.last_ok) // 1000))
        L["ntp_count"].set_text("Sync count: %d" % n.sync_count)
        t = tz.local()
        L["ntp_time"].set_text("Time: %02d:%02d:%02d %s" % (t[3], t[4], t[5], tz.abbrev()) if (n.synced and t) else "Time: --")

    def refresh_update(self, L):
        from core import updater
        u = updater.state
        if u["status"] == "installing":
            L["update"].set_text("Installing... %d%%" % u["progress"])
            self.upd_lbl.set_text("Installing")
        elif u["status"] == "checking":
            L["update"].set_text("Checking for updates...")
            self.upd_lbl.set_text("Checking")
        elif u["available"]:
            L["update"].set_text("Update %s available" % u["latest"])
            self.upd_lbl.set_text("Install %s" % u["latest"])
        elif u["error"]:
            L["update"].set_text("Update: %s" % u["error"])
            self.upd_lbl.set_text("Check Updates")
        elif u["checked"] is not None:
            L["update"].set_text("Up to date (checked %s)" % ago(time.ticks_diff(time.ticks_ms(), u["checked"]) // 1000))
            self.upd_lbl.set_text("Check Updates")
        else:
            L["update"].set_text("Updates: not checked")
            self.upd_lbl.set_text("Check Updates")

    def update_clicked(self):
        import asyncio
        from core import updater
        u = updater.state
        if u["status"] != "idle":
            return
        if u["available"]:
            C.confirm("Install %s?" % u["latest"], "Downloads the new version from GitHub, checks it, installs it and restarts "
                      "the panel. Settings and history are kept. If the new version fails to start, the old one returns "
                      "automatically." + ("\n\n" + u["notes"] if u["notes"] else ""),
                      lambda: asyncio.create_task(updater.install(self.app)), "Install",
                      on_no=lambda: self.app.settings.set("update.dismissed", u["latest"]), no_label="Later")
        else:
            asyncio.create_task(updater.check(self.app))

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
