"""Backlight control (port of backlight*.c).

The stock board only has on/off (CH422G). With a wire jumped from the backlight pad to a spare GPIO, PWM dimming and a
time-of-day curve become possible; that sits behind a master gate that defaults to off, in which case blanking uses the
hard on/off exactly as before.

Resolution order (bl_resolve): gate off -> 100 (0 while idle); idle -> 0; manual override; no clock / no curve -> curve
peak; touch boost (125 % of the current curve value, at least 15, at most the peak); else the curve. Awake never goes
below BL_ACTIVE_FLOOR. A manual override expires when the curve next moves; any touch clears it.
"""
import asyncio
import time

from . import tz

BL_ACTIVE_FLOOR = 3
BOOST_PERCENT = 125
BOOST_MIN = 15
BOOST_HOLD_MS = 60000
FADE_MS = 2000
MANUAL_FADE_MS = 200
PWM_FREQ = 5000
MAX_POINTS = 8
GPIO_DEFAULT = 6

PRESETS = {
    "off": [],
    "gentle": [(7 * 60, 50), (9 * 60, 80), (21 * 60, 25), (22 * 60, 2)],
    "aggressive": [(7 * 60, 50), (9 * 60, 90), (20 * 60, 30), (22 * 60, 2)],
}
# pins the board already owns: RGB bus, I2C/CH422G/touch, USB, UART0, in-package flash/PSRAM
_RESERVED = {0, 1, 2, 3, 5, 7, 8, 9, 10, 14, 17, 18, 19, 20, 21, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48} | set(range(26, 38))


def gpio_allowed(gpio):
    return 0 <= gpio <= 48 and gpio not in _RESERVED


# ---- pure curve maths ---------------------------------------------------------------------------------------
def _lerp(f, t, elapsed, span):
    if span == 0:
        return t
    delta = t - f
    bias = span // 2 if delta >= 0 else -(span // 2)
    return f + (delta * elapsed + bias) // span if delta >= 0 else f - ((-delta * elapsed + span // 2) // span)


def curve_eval(pts, minute):
    if not pts:
        return 100
    if len(pts) == 1:
        return pts[0][1]
    for i in range(len(pts) - 1):
        if pts[i][0] <= minute < pts[i + 1][0]:
            return _lerp(pts[i][1], pts[i + 1][1], minute - pts[i][0], pts[i + 1][0] - pts[i][0])
    last, first = pts[-1], pts[0]
    span = 1440 - last[0] + first[0]
    elapsed = minute - last[0] if minute >= last[0] else 1440 - last[0] + minute
    return _lerp(last[1], first[1], elapsed, span)


def curve_peak(pts):
    return max(p for _m, p in pts) if pts else 100


def curve_next(pts, minute):
    if not pts:
        return 0
    for m, _p in pts:
        if m > minute:
            return m
    return pts[0][0]


def curve_valid(pts):
    if len(pts) > MAX_POINTS:
        return False
    for i, (m, p) in enumerate(pts):
        if not (0 <= m < 1440 and 0 <= p <= 100):
            return False
        if i and m <= pts[i - 1][0]:
            return False
    return True


def manual_expired(set_minute, next_minute, now_minute):
    window = (next_minute + 1440 - set_minute) % 1440 or 1440
    return (now_minute + 1440 - set_minute) % 1440 >= window


class Backlight:
    def __init__(self, app, board):
        self.app, self.board = app, board
        s = app.settings
        self.enabled = bool(s.get("backlight.enabled", False))
        self.gpio = int(s.get("backlight.gpio", GPIO_DEFAULT))
        self.preset = s.get("backlight.preset", "off")
        self.custom = [tuple(p) for p in s.get("backlight.points", [])]
        self.idle = False
        self.boost_until = 0
        self.manual = None                 # (percent, minute set)
        self.pwm = None
        self.bound_gpio = None
        self.applied = None                # percent on the pin (or 0/100 for the CH422G)
        self.target = 100
        self.fade_ms = FADE_MS
        self._last_source = "disabled"

    # ---- state -------------------------------------------------------------------------------------------
    def points(self):
        return self.custom if self.preset == "custom" else PRESETS.get(self.preset, [])

    def minute(self):
        t = tz.local()
        return None if t is None else t[3] * 60 + t[4]

    def resolve(self):
        pts = self.points()
        if not self.enabled:
            return (0 if self.idle else 100), "disabled"
        if self.idle:
            return 0, "idle"
        if self.manual:
            return self.manual[0], "manual"
        minute = self.minute()
        if minute is None or not pts:
            pct, src = curve_peak(pts), "curve"
        elif time.ticks_diff(self.boost_until, time.ticks_ms()) > 0:
            boosted = max((curve_eval(pts, minute) * BOOST_PERCENT + 50) // 100, BOOST_MIN)
            pct, src = min(boosted, curve_peak(pts)), "boost"
        else:
            pct, src = curve_eval(pts, minute), "curve"
        return max(pct, BL_ACTIVE_FLOOR), src

    def screen_is_dark(self):
        return self.resolve()[0] == 0

    # ---- inputs ------------------------------------------------------------------------------------------
    def set_idle(self, idle):
        if idle != self.idle:
            self.idle = idle
            self.apply()

    def notify_touch(self):
        if not getattr(self, "pinned", False):
            self.manual = None                   # whoever stands at the panel can always recover it
        self.boost_until = time.ticks_add(time.ticks_ms(), BOOST_HOLD_MS)
        self.apply()

    def set_manual(self, percent, pinned=False):
        """Hold a brightness until the schedule next changes. pinned=True (the dashboard's brightness dialog) also survives
        touches; the default (web slider, API) is a preview that the next touch on the panel cancels."""
        self.pinned = bool(pinned)
        percent = max(0, min(100, int(percent)))
        m = self.minute()
        self.manual = (max(percent, BL_ACTIVE_FLOOR) if percent else 0, m if m is not None else 0)
        self.fade_ms = MANUAL_FADE_MS
        self.apply()

    # ---- config ------------------------------------------------------------------------------------------
    def set_config(self, enabled=None, gpio=None, preset=None):
        s = self.app.settings
        if gpio is not None:
            if not gpio_allowed(gpio):
                raise ValueError("gpio %d is not available" % gpio)
            self.gpio = gpio
            s.set("backlight.gpio", gpio)
        if preset is not None:
            if preset not in ("off", "gentle", "aggressive", "custom"):
                raise ValueError("preset must be off, gentle, aggressive or custom")
            self.preset = preset
            s.set("backlight.preset", preset)
        if enabled is not None:
            self.enabled = bool(enabled)
            s.set("backlight.enabled", self.enabled)
        self.apply()

    def set_curve(self, points):
        pts = [(int(m), int(p)) for m, p in points]
        if not curve_valid(pts):
            raise ValueError("invalid curve: up to %d points, minutes ascending 0-1439, percent 0-100" % MAX_POINTS)
        self.custom = pts
        self.preset = "custom"
        self.app.settings.set("backlight.points", pts)
        self.app.settings.set("backlight.preset", "custom")
        self.apply()

    def status(self):
        pct, src = self.resolve()
        pts = self.points()
        m = self.minute()
        nxt = curve_next(pts, m) if (pts and m is not None) else None
        return {"ok": True, "enabled": self.enabled, "gpio": self.gpio,
                "gpio_pending": bool(self.enabled and self.bound_gpio is not None and self.bound_gpio != self.gpio),
                "percent": pct, "applied_percent": self.applied if self.applied is not None else pct,
                "source": src, "preset": self.preset, "clock_synced": m is not None, "min": 0, "max": 100,
                "next_change": None if nxt is None else "%02d:%02d" % (nxt // 60, nxt % 60),
                "points": [["%02d:%02d" % (a // 60, a % 60), b] for a, b in pts]}

    # ---- hardware ----------------------------------------------------------------------------------------
    def _bind(self):
        if self.pwm is None and self.enabled:
            from machine import PWM, Pin
            try:
                pct = self.resolve()[0]
                self.pwm = PWM(Pin(self.gpio), freq=PWM_FREQ, duty_u16=pct * 65535 // 100)   # start at the target: no dark flash
                self.bound_gpio = self.gpio
                self.applied = pct
            except Exception as e:
                self.app.log.warn("backlight: cannot bind PWM on gpio %d: %r" % (self.gpio, e))
                self.enabled = False

    def _unbind(self):
        if self.pwm is not None:
            try:
                self.pwm.deinit()
            except Exception:
                pass
            self.pwm = None
            self.bound_gpio = None

    def apply(self):
        pct, src = self.resolve()
        self.target = pct
        self._last_source = src
        if self.enabled:
            self._bind()
        else:
            self._unbind()
            self.board.backlight(pct > 0)                 # hard on/off through the expander
            self.applied = 100 if pct > 0 else 0
            return
        # PWM path: the fade task steps `applied` towards `target`
        self.board.backlight(True)                        # expander gate stays on; the PWM pin does the dimming

    async def run(self):
        """Ticker: fade steps, boost/manual expiry, curve transitions."""
        last_minute = None
        while True:
            now_min = self.minute()
            if self.manual and now_min is not None and manual_expired(self.manual[1], curve_next(self.points(), self.manual[1]), now_min):
                self.manual = None
            if now_min != last_minute:
                last_minute = now_min
                self.apply()
            elif self._last_source == "boost" and time.ticks_diff(self.boost_until, time.ticks_ms()) <= 0:
                self.apply()
            if self.enabled and self.pwm is not None:
                cur = self.applied if self.applied is not None else 0
                if cur != self.target:
                    step = max(1, abs(self.target - cur) * 50 // max(self.fade_ms, 50))
                    cur = min(self.target, cur + step) if self.target > cur else max(self.target, cur - step)
                    self.applied = cur
                    self.pwm.duty_u16(cur * 65535 // 100)
                    if cur == self.target:
                        self.fade_ms = FADE_MS
                    await asyncio.sleep_ms(50)
                    continue
            await asyncio.sleep_ms(500)
