"""Waveshare ESP32-S3-Touch-LCD-7 bring-up: 800x480 RGB display + CH422G expander + GT911 touch + LVGL loop."""
import asyncio
import time

DEBUG = False   # print touch/frame timing to the serial console

import rgb_lcd
import lvgl as lv
from machine import I2C, Pin

PHYS_W, PHYS_H = rgb_lcd.WIDTH, rgb_lcd.HEIGHT      # the panel itself is 800x480 landscape
W, H = PHYS_W, PHYS_H                                # logical size: swapped by init(portrait=True)
portrait = False
single = False                                       # partial rendering straight into the live frame buffer (no swap, no wait)
partial = False                                      # partial rendering into an SRAM buffer (always in portrait)
CCW = False                                          # portrait rotation direction (False = 90 degrees clockwise)

_I2C_SDA, _I2C_SCL = 8, 9

# CH422G I/O expander (write-only): 0x24 = mode register, 0x38 = output register.
# Output bits: 0 = touch INT/TP_IRQ helper, 1 = touch RESET, 2 = backlight enable, 3 = LCD reset, 5 = SD chip select.
_CH_MODE, _CH_OUT = 0x24, 0x38
_BIT_TP_RST, _BIT_BL, _BIT_LCD_RST = 0x02, 0x04, 0x08

_i2c = None
_ch_shadow = 0x2E


def _ch_write(v):
    global _ch_shadow
    _ch_shadow = v & 0xFF
    _i2c.writeto(_CH_OUT, bytes([_ch_shadow]))


def _i2c_bus():
    global _i2c
    if _i2c is None:
        _i2c = I2C(0, sda=Pin(_I2C_SDA), scl=Pin(_I2C_SCL), freq=400000)
    return _i2c


def _ch422g_reset():
    """Same sequence as Waveshare's demo: outputs on, hold touch/LCD in reset, release, backlight on."""
    _i2c_bus()
    _i2c.writeto(_CH_MODE, b"\x01")
    _ch_write(0x2C)
    time.sleep_ms(100)
    _ch_write(0x2E)
    time.sleep_ms(200)


def backlight(on):
    """The backlight is on/off only (CH422G output, no PWM on this board)."""
    if _i2c is None:
        return
    _ch_write((_ch_shadow | _BIT_BL) if on else (_ch_shadow & ~_BIT_BL))


class GT911:
    def __init__(self):
        i2c = _i2c_bus()
        found = i2c.scan()
        self.addr = 0x5D if 0x5D in found else 0x14
        if self.addr not in found:
            raise OSError("GT911 not found, i2c scan: %s" % found)
        self.i2c = i2c
        self.x = self.y = 0
        self.events = 0
        self.errors = 0

    def read(self):
        """Return pressed; the point is left in self.x / self.y."""
        i2c, a = self.i2c, self.addr
        st = i2c.readfrom_mem(a, 0x814E, 1, addrsize=16)[0]
        if not st & 0x80:
            return self.touching
        n = st & 0x0F
        if n:
            d = i2c.readfrom_mem(a, 0x8150, 4, addrsize=16)  # x lo/hi, y lo/hi of point 0
            self.x = d[0] | (d[1] << 8)
            self.y = d[2] | (d[3] << 8)
        i2c.writeto_mem(a, 0x814E, b"\x00", addrsize=16)
        was = self.touching
        self.touching = bool(n)
        if self.touching and not was:
            self.events += 1
        return self.touching

    touching = False


_disp = None
_pbuf = None      # rotated mode: LVGL's single partial draw buffer (internal SRAM)
_shown = 0      # rotated mode: index of the frame buffer on screen
_pu = None      # rotated mode: physical dirty rectangle of the frame being rendered
_indev = None
_touch = None
_fbs = None


# Double buffering: LVGL (DIRECT mode, two full-size buffers) renders frame N into buffer N%2;
# when a frame is complete it is handed to the panel, which switches at a frame boundary
# (no tearing, no half-drawn frames). present() blocks until the switch has happened.
_frame = 0
_y1 = _y2 = None       # dirty rows of the frame being rendered
_prev = None           # dirty rows of the previous frame (LVGL copies them into the next back buffer)


_pres = [0, 0]      # per stats window: total / worst ms spent waiting in present() (vsync)


def _flush_cb(disp, area, color_p):
    global _frame, _y1, _y2, _prev
    _y1 = area.y1 if _y1 is None else min(_y1, area.y1)
    _y2 = area.y2 if _y2 is None else max(_y2, area.y2)
    if disp.flush_is_last():
        y1, y2 = _y1, _y2
        if _prev:  # rows LVGL synced from the last frame must reach RAM too
            y1, y2 = min(y1, _prev[0]), max(y2, _prev[1])
        t0 = time.ticks_ms()
        rgb_lcd.present(_frame & 1, y1, y2)
        _pres[0] += time.ticks_diff(time.ticks_ms(), t0)
        _pres[1] = max(_pres[1], time.ticks_diff(time.ticks_ms(), t0))
        _prev = (_y1, _y2)
        _y1 = _y2 = None
        _frame += 1
    disp.flush_ready()


def _flush_rot(disp, area, color_p):
    """Partial rendering (portrait: rotated). LVGL draws into one small internal-SRAM buffer (fast: blending never reads
    the slow PSRAM frame buffer); each piece is copied into the back frame buffer, and when the frame is complete it is
    presented and the touched rectangle copied into the other buffer so both stay identical for the next frame."""
    global _frame, _shown, _pu
    if single:
        # Single buffer: copy each rendered piece into the buffer being scanned out and carry on at once. No swap, no
        # vsync wait, no second copy; the cost is that a big redraw is briefly visible as it sweeps down the panel.
        if portrait:
            rgb_lcd.blit_rot(_pbuf, area.x1, area.y1, area.x2, area.y2, 0, CCW)
        else:
            rgb_lcd.blit(_pbuf, area.x1, area.y1, area.x2, area.y2, 0)
        if disp.flush_is_last():
            _frame += 1
        disp.flush_ready()
        return
    back = 1 - _shown
    t0 = time.ticks_ms()
    if portrait:
        x1, y1, x2, y2 = rgb_lcd.blit_rot(_pbuf, area.x1, area.y1, area.x2, area.y2, back, CCW)
    else:
        x1, y1, x2, y2 = rgb_lcd.blit(_pbuf, area.x1, area.y1, area.x2, area.y2, back)
    if _pu is None:
        _pu = [x1, y1, x2, y2]
    else:
        _pu[0], _pu[1] = min(_pu[0], x1), min(_pu[1], y1)
        _pu[2], _pu[3] = max(_pu[2], x2), max(_pu[3], y2)
    if disp.flush_is_last():
        t0 = time.ticks_ms()
        rgb_lcd.present(back, _pu[1], _pu[3])
        _pres[0] += time.ticks_diff(time.ticks_ms(), t0)
        _pres[1] = max(_pres[1], time.ticks_diff(time.ticks_ms(), t0))
        rgb_lcd.copy_rect(back, _shown, _pu[0], _pu[1], _pu[2], _pu[3])
        _shown = back
        _pu = None
        _frame += 1
    disp.flush_ready()


def front():
    """Framebuffer currently on screen (for screenshots)."""
    if partial:
        return _fbs[_shown]
    return _fbs[(_frame - 1) & 1] if _frame else _fbs[0]


_inject = []       # queued synthetic touch samples [(x, y, pressed)], used by /api/touch for hands-free tests


def inject_drag(x1, y1, x2, y2, steps=8):
    """Queue a finger drag (a tap when the points are equal); one sample per LVGL input poll."""
    n = max(2, steps)
    for i in range(n + 1):
        _inject.append((x1 + (x2 - x1) * i // n, y1 + (y2 - y1) * i // n, True))
    _inject.append((x2, y2, False))
    _inject.append((x2, y2, False))


def _read_cb(indev, data):
    if _inject:
        x, y, pressed = _inject.pop(0)
        _touch.x, _touch.y = x, y
        data.point.x = x
        data.point.y = y
        data.state = lv.INDEV_STATE.PRESSED if pressed else lv.INDEV_STATE.RELEASED
        return
    try:
        pressed = _touch.read()
    except OSError:
        _touch.errors += 1
        pressed = False
    global _last_pressed
    if DEBUG and pressed != _last_pressed:
        print("[touch]", "down" if pressed else "up", _touch.x, _touch.y, time.ticks_ms())
    _last_pressed = pressed
    if portrait:                       # panel coordinates -> rotated logical coordinates
        if CCW:
            data.point.x, data.point.y = PHYS_H - 1 - _touch.y, _touch.x
        else:
            data.point.x, data.point.y = _touch.y, PHYS_W - 1 - _touch.x
    else:
        data.point.x = _touch.x
        data.point.y = _touch.y
    data.state = lv.INDEV_STATE.PRESSED if pressed else lv.INDEV_STATE.RELEASED


_last_pressed = False

stats = {"fps": 0.0, "load": 0, "max_ms": 0, "errors": 0, "stall_ms": 0}
_wdt = None
_up_ms = 0


def uptime_ms():
    return _up_ms


def frames():
    return _frame


def init(portrait_mode=False, partial_render=True, rows=None, single_buffer=False):
    """Bring up the panel. portrait_mode=True renders a 480x800 logical screen rotated into the 800x480 panel.
    partial_render (landscape): draw into a small internal-SRAM buffer instead of straight into the PSRAM frame buffers."""
    global _disp, _indev, _touch, _fbs, W, H, portrait, partial, single, _pbuf
    if _disp:
        return _disp
    _ch422g_reset()
    lv.init()
    _fbs = rgb_lcd.init()
    rgb_lcd.vsync_waits(2)   # 1 doubles the frame rate but showed glitching while dragging a slider
    portrait = bool(portrait_mode)
    if portrait:
        W, H = PHYS_H, PHYS_W
    _disp = lv.display_create(W, H)
    _disp.set_color_format(lv.COLOR_FORMAT.RGB565)
    partial = portrait or bool(partial_render)
    single = partial and bool(single_buffer)
    if partial:
        # partial rendering: one internal-SRAM draw buffer (~60 KB), copied (and rotated in portrait) by _flush_rot
        _pbuf = rgb_lcd.buffer(W * (rows or (64 if portrait else 40)) * 2)
        _disp.set_buffers(_pbuf, None, len(_pbuf), lv.DISPLAY_RENDER_MODE.PARTIAL)
        _disp.set_flush_cb(_flush_rot)
    else:
        _disp.set_buffers(_fbs[0], _fbs[1], len(_fbs[0]), lv.DISPLAY_RENDER_MODE.DIRECT)
        _disp.set_flush_cb(_flush_cb)
    # Input latency: touch is polled every 10 ms and a redraw is started as soon as something changed (10 ms refresh
    # timer). The panel itself (~37 Hz) plus two vsync waits in present() set the floor for what you actually see.
    _disp.get_refr_timer().set_period(10)
    # dark default theme so keyboards, text areas, dropdowns etc. match the app
    th = lv.theme_default_init(_disp, lv.color_hex(0x6366F1), lv.color_hex(0x38BDF8), True, lv.font_montserrat_16)
    _disp.set_theme(th)
    try:
        _touch = GT911()
        _indev = lv.indev_create()
        _indev.set_type(lv.INDEV_TYPE.POINTER)
        _indev.set_read_cb(_read_cb)
        _indev.get_read_timer().set_period(10)
    except OSError as e:
        print("touch disabled:", e)
    return _disp


def _start_watchdog():
    """Reset the panel if the UI loop stops feeding it for `system.watchdog_s` seconds (default 300, 0 = off).
    Not started while a /dev_mode file exists (long development sessions with mpremote)."""
    global _wdt
    try:
        import os
        try:
            from core import settings
        except ImportError:                    # bare bring-up build without the app framework
            class settings:
                get = staticmethod(lambda k, d=None: d)
        try:
            os.stat("/dev_mode")
            print("[I] watchdog off (dev_mode)")
            return
        except OSError:
            pass
        secs = settings.get("system.watchdog_s", 300)
        if secs:
            from machine import WDT
            _wdt = WDT(timeout=int(secs) * 1000)
    except Exception as e:
        print("[W] watchdog not started:", e)


def _loop_error(e):
    stats["errors"] += 1
    try:
        from core import errors, log
        log.error("ui loop: %s" % errors.describe(e))
    except Exception:
        print("ui loop error:", e)


def _loop_error_log(msg):
    try:
        from core import log
        log.warn(msg)
    except Exception:
        print(msg)


async def _loop():
    global _up_ms
    _start_watchdog()
    last = time.ticks_ms()
    win_start = last
    win_frames0 = _frame
    busy = 0
    worst = 0
    worst_gap = 0
    last_handler = 0
    while True:
        now = time.ticks_ms()
        dt = time.ticks_diff(now, last)
        if dt > worst_gap:
            worst_gap = dt
        if dt > 300:                       # something held the whole event loop (touch included) for a while
            _loop_error_log("ui: event loop stalled %d ms (previous handler %d ms)" % (dt, last_handler))
        _up_ms += dt
        lv.tick_inc(dt)
        last = now
        if _wdt:
            _wdt.feed()
        t0 = time.ticks_ms()
        try:
            lv.task_handler()
        except Exception as e:           # callbacks are protected in C; this is the last line of defence
            _loop_error(e)
        d = time.ticks_diff(time.ticks_ms(), t0)
        last_handler = d
        busy += d
        if d > worst:
            worst = d
        if DEBUG and d > 100:
            print("[slow frame]", d, "ms at", t0)
        wall = time.ticks_diff(time.ticks_ms(), win_start)
        if wall >= 2000:
            stats["fps"] = (_frame - win_frames0) * 1000 / wall
            stats["load"] = min(100, busy * 100 // wall)
            stats["max_ms"] = worst
            stats["stall_ms"] = worst_gap                 # longest time between two loop iterations
            stats["present_ms"], stats["present_max"] = _pres[0], _pres[1]
            _pres[0] = _pres[1] = 0
            win_start = time.ticks_ms()
            win_frames0 = _frame
            busy = worst = worst_gap = 0
        await asyncio.sleep_ms(2)


def start():
    """Start the LVGL loop as an asyncio task; returns the task."""
    return asyncio.create_task(_loop())


def run(coro=None):
    """Run LVGL forever (plus an optional extra coroutine)."""
    async def main():
        start()
        if coro:
            asyncio.create_task(coro)
        while True:
            await asyncio.sleep(3600)
    asyncio.run(main())
