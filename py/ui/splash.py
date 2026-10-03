"""Boot splash: logo, title, progress bar and a status line on LVGL's top layer, shown as soon as the display is up.

While main.py is still importing modules and building screens the asyncio UI loop is not running yet, so step() pumps LVGL by
hand. The splash lives on the top layer, so building the real screens underneath does not disturb it; finish() fades it out
once the loop is running."""
import asyncio
import time

import lvgl as lv

BG, ACCENT, TEXT, MUTED, TRACK, ON_ACCENT = 0x080A0E, 0x38BDF8, 0xF1F5F9, 0x94A3B8, 0x1E293B, 0x0F172A

_root = _bar = _msg = None
_manual = True
_last = 0


def _col(v):
    return lv.color_hex(v)


def _label(parent, text, size, color):
    l = lv.label(parent)
    l.set_text(text)
    l.set_style_text_color(_col(color), 0)
    l.set_style_text_font(getattr(lv, "font_montserrat_%d" % size), 0)
    return l


def show(version, manual=True):
    """Build the splash. manual=True: the caller pumps LVGL through step() (boot); False: the UI loop is already running."""
    global _root, _bar, _msg, _manual, _last
    hide()
    _manual, _last = manual, time.ticks_ms()
    r = _root = lv.obj(lv.layer_top())
    r.remove_style_all()
    r.set_size(lv.pct(100), lv.pct(100))
    r.set_style_bg_color(_col(BG), 0)
    r.set_style_bg_opa(lv.OPA.COVER, 0)
    r.remove_flag(lv.obj.FLAG.SCROLLABLE)
    r.add_flag(lv.obj.FLAG.CLICKABLE)                  # swallow touches until the real UI is ready
    r.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    r.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    r.set_style_pad_row(10, 0)
    logo = lv.obj(r)
    logo.remove_style_all()
    logo.set_size(88, 88)
    logo.set_style_radius(22, 0)
    logo.set_style_bg_color(_col(ACCENT), 0)
    logo.set_style_bg_opa(lv.OPA.COVER, 0)
    logo.remove_flag(lv.obj.FLAG.SCROLLABLE)
    _label(logo, "SG", 30, ON_ACCENT).center()
    gap = lv.obj(r)                                    # spacing below the logo
    gap.remove_style_all()
    gap.set_size(1, 6)
    _label(r, "Sigen Dashboard", 30, TEXT)
    _label(r, "Battery & solar monitor", 16, MUTED)
    gap = lv.obj(r)
    gap.remove_style_all()
    gap.set_size(1, 20)
    b = _bar = lv.bar(r)
    b.set_size(320, 6)
    b.set_range(0, 100)
    b.set_style_bg_color(_col(TRACK), lv.PART.MAIN)
    b.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
    b.set_style_radius(3, lv.PART.MAIN)
    b.set_style_bg_color(_col(ACCENT), lv.PART.INDICATOR)
    b.set_style_bg_opa(lv.OPA.COVER, lv.PART.INDICATOR)
    b.set_style_radius(3, lv.PART.INDICATOR)
    b.set_value(0, 0)
    _msg = _label(r, "Starting...", 14, MUTED)
    v = _label(r, "Version " + version, 14, 0x475569)
    v.add_flag(lv.obj.FLAG.IGNORE_LAYOUT)
    v.align(lv.ALIGN.BOTTOM_MID, 0, -14)
    _pump()


def _pump():
    """Draw now (only needed while the UI loop is not running)."""
    global _last
    if not _manual:
        return
    now = time.ticks_ms()
    lv.tick_inc(time.ticks_diff(now, _last))
    _last = now
    lv.task_handler()
    lv.task_handler()


def step(text, pct):
    if _root is None:
        return
    _msg.set_text(text)
    _bar.set_value(pct, 0)
    _pump()


def hide():
    global _root, _bar, _msg
    if _root is not None:
        _root.delete()
        _root = _bar = _msg = None


async def finish():
    """Fade out and remove (the UI loop must be running)."""
    if _root is None:
        return
    step("Ready", 100)
    await asyncio.sleep_ms(150)
    for opa in (200, 140, 80, 30):
        if _root is None:
            return
        _root.set_style_opa(opa, 0)
        await asyncio.sleep_ms(45)
    hide()
