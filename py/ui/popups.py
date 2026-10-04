"""Small modal dialogs opened from the dashboard's top bar: system status (tap the icons) and brightness (tap the clock)."""
import time

import lvgl as lv

from . import common as C


def status(app, shell):
    """What the three status icons mean, right now, with shortcuts to the screens that fix them."""
    svc = app.services
    s, wifi, ntp = svc["state"], svc["wifi"], svc["ntp"]
    from core import updater, version
    from core.fmt import ago
    ov, p = C.dialog("System status")
    if s.last_commit_ms is None:
        inv = "Waiting for the first reading" if s.alive else "Not connected (check the address in Settings)"
    else:
        inv = ("Connected, last reading %s" if s.alive else "Not responding, last reading %s") % ago(time.ticks_diff(time.ticks_ms(), s.last_commit_ms) // 1000)
    w = ("%s, %s dBm, %s" % (wifi.ssid, wifi.rssi(), wifi.ip)) if wifi.connected else ("Setup hotspot" if wifi.mode == "ap" else "Not connected")
    t = ("Synced (%s)" % (ntp.server or "NTP")) if ntp.synced else "Not synced yet"
    u = updater.state
    if u["available"]:
        sw = "Version %s, %s available" % (version.VERSION, u["latest"])
    else:
        sw = "Version %s%s" % (version.VERSION, ", up to date" if u["checked"] is not None and not u["error"] else "")
    for head, body, ok in (("Inverter", inv, s.alive), ("WiFi", w, wifi.connected), ("Clock", t, ntp.synced), ("Software", sw, True)):
        row = lv.obj(p)
        row.remove_style_all()
        row.set_size(lv.pct(100), lv.SIZE_CONTENT)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_style_pad_column(12, 0)
        h = C.label(row, head, 16, C.MUTED)
        h.set_width(90)
        C.label(row, body, 16, C.TEXT if ok else 0xFBBF24, wrap_w=360)
    btns = C.button_row(p)
    C.button(btns, "WiFi", C.CARD, C.TEXT, lambda: (ov.delete(), shell.go_name("WiFi"))).set_style_bg_color(C.c(C.FIELD_BORDER), 0)
    C.button(btns, "Inverter settings", C.CARD, C.TEXT, lambda: (ov.delete(), shell.go_name("Settings"))).set_style_bg_color(C.c(C.FIELD_BORDER), 0)
    C.button(btns, "Close", C.ACCENT, C.ACCENT_TEXT, lambda: ov.delete())


def brightness(app, shell):
    """A pinned brightness (until you pick Auto or the schedule next changes) without going through Settings."""
    bl = app.services["backlight"]
    from core import backlight as bmod
    ov, p = C.dialog("Brightness", 480)
    val = C.label(p, "", 20, C.ACCENT)
    sl = lv.slider(p)
    sl.set_width(lv.pct(100))
    sl.set_height(22)
    sl.set_range(bmod.BL_ACTIVE_FLOOR, 100)
    sl.set_style_bg_color(C.c(C.FIELD_BORDER), lv.PART.MAIN)
    sl.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
    sl.set_style_bg_color(C.c(C.ACCENT), lv.PART.INDICATOR)
    sl.set_style_bg_color(C.c(C.ACCENT), lv.PART.KNOB)
    cur = max(bl.resolve()[0], bmod.BL_ACTIVE_FLOOR)
    sl.set_value(cur, 0)
    note = C.label(p, "", 14, C.MUTED, wrap_w=420)

    def show():
        val.set_text("%d%%" % sl.get_value())
        note.set_text("Held until you choose Auto or the schedule changes." if bl.manual else "Following the schedule (%s)." % bl.preset)

    def changed():
        bl.set_manual(sl.get_value(), True)
        show()
    sl.add_event_cb(lambda e: changed(), lv.EVENT.VALUE_CHANGED, None)
    for ev in (lv.EVENT.PRESSED, lv.EVENT.PRESSING):
        sl.add_event_cb(lambda e: setattr(shell, "suppress", True), ev, None)
    for ev in (lv.EVENT.RELEASED, lv.EVENT.PRESS_LOST):
        sl.add_event_cb(lambda e: setattr(shell, "suppress", False), ev, None)

    def auto():
        bl.manual = None
        bl.apply()
        sl.set_value(max(bl.resolve()[0], bmod.BL_ACTIVE_FLOOR), 0)
        show()
    btns = C.button_row(p)
    C.button(btns, "Auto", C.CARD, C.TEXT, auto).set_style_bg_color(C.c(C.FIELD_BORDER), 0)
    C.button(btns, "Done", C.ACCENT, C.ACCENT_TEXT, lambda: (setattr(shell, "suppress", False), ov.delete()))
    show()
