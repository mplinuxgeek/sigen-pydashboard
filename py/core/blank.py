"""Screen blanking (idle timeout) and the scheduled Night Screen Off, both driving Backlight.set_idle().

A blanked screen gets a full-screen overlay that swallows the wake-up tap, so waking the panel never presses a button
underneath. Settings: blank.enabled / blank.timeout_s (default on, 120 s), night.enabled / night.start / night.end
(minutes after local midnight; default on, 22:00 - 07:00)."""
import asyncio
import time

import lvgl as lv

from . import tz

BLANK_DEFAULT_S = 120
NIGHT_START_DEFAULT, NIGHT_END_DEFAULT = 22 * 60, 7 * 60
NIGHT_CHECK_MS = 30000


def in_window(start, end, minute):
    if start == end:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


class Blank:
    def __init__(self, app, backlight):
        self.app, self.bl = app, backlight
        s = app.settings
        self.enabled = bool(s.get("blank.enabled", True))
        self.timeout_s = int(s.get("blank.timeout_s", BLANK_DEFAULT_S))
        self.night_enabled = bool(s.get("night.enabled", True))
        self.night_start = int(s.get("night.start", NIGHT_START_DEFAULT))
        self.night_end = int(s.get("night.end", NIGHT_END_DEFAULT))
        self.blanked = False
        self.night_active = False
        self.last_touch = time.ticks_ms()
        self.overlay = None

    # ---- settings ----------------------------------------------------------------------------------------
    def set_blank(self, enabled=None, timeout_s=None):
        if enabled is not None:
            self.enabled = bool(enabled)
            self.app.settings.set("blank.enabled", self.enabled)
            if not self.enabled and self.blanked:
                self.wake()
        if timeout_s is not None:
            self.timeout_s = max(5, int(timeout_s))
            self.app.settings.set("blank.timeout_s", self.timeout_s)
        self.last_touch = time.ticks_ms()

    def set_night(self, enabled=None, start=None, end=None):
        s = self.app.settings
        if enabled is not None:
            self.night_enabled = bool(enabled)
            s.set("night.enabled", self.night_enabled)
        if start is not None and 0 <= start < 1440:
            self.night_start = int(start)
            s.set("night.start", self.night_start)
        if end is not None and 0 <= end < 1440:
            self.night_end = int(end)
            s.set("night.end", self.night_end)
        self.check_night()

    # ---- blank / wake ------------------------------------------------------------------------------------
    def _make_overlay(self):
        if self.overlay is not None or not self.bl.screen_is_dark():
            return
        ov = self.overlay = lv.obj(lv.layer_top())
        ov.remove_style_all()
        ov.set_size(lv.pct(100), lv.pct(100))
        ov.add_flag(lv.obj.FLAG.CLICKABLE)
        ov.add_event_cb(lambda e: self.wake(), lv.EVENT.PRESSED, None)

    def _drop_overlay(self):
        if self.overlay is not None:
            self.overlay.delete()
            self.overlay = None

    def blank(self):
        self.blanked = True
        self.bl.set_idle(True)
        self._make_overlay()
        self.app.log.info("blank: screen off")

    def wake(self):
        was = self.blanked or self.bl.idle
        self.blanked = False
        self.bl.set_idle(False)
        self._drop_overlay()
        self.last_touch = time.ticks_ms()
        if was:
            self.app.log.info("blank: screen on")

    def touched(self):
        """Any touch (pointer PRESSED): boost the backlight, wake a blanked screen, restart the idle countdown."""
        self.bl.notify_touch()
        if self.blanked or self.bl.idle:
            self.wake()
        self.last_touch = time.ticks_ms()

    # ---- night schedule --------------------------------------------------------------------------------
    def check_night(self):
        t = tz.local()
        if not self.night_enabled or t is None:
            if self.night_active:
                self.night_active = False
                self.bl.set_idle(False)
                self._drop_overlay()
            return
        active = in_window(self.night_start, self.night_end, t[3] * 60 + t[4])
        if active != self.night_active:
            self.app.log.info("night screen: %s" % ("off (scheduled)" if active else "on (schedule ended)"))
        was, self.night_active = self.night_active, active
        if not active and was:
            self.bl.set_idle(False)
            self._drop_overlay()
        if active:
            self.bl.set_idle(True)
            self._make_overlay()

    async def run(self):
        last_night = 0
        while True:
            now = time.ticks_ms()
            if self.enabled and not self.blanked and time.ticks_diff(now, self.last_touch) >= self.timeout_s * 1000:
                self.blank()
            if time.ticks_diff(now, last_night) >= NIGHT_CHECK_MS:
                last_night = now
                self.check_night()
            await asyncio.sleep_ms(1000)
