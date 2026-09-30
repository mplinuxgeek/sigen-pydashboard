"""Shared UI bits: palette for forms/settings, buttons, text areas, keyboards, gesture-vs-click guard."""
import time

import lvgl as lv

BG = 0x08090E
CARD = 0x1E293B
TEXT = 0xE2E8F0
MUTED = 0x94A3B8
ACCENT = 0x38BDF8
ACCENT_TEXT = 0x0B1220
DANGER = 0xF87171
FIELD_BG = 0x0F172A
FIELD_BORDER = 0x334155

_cols = {}


def c(v):
    x = _cols.get(v)
    if x is None:
        x = _cols[v] = lv.color_hex(v)
    return x


# ---- swipe vs. click ----------------------------------------------------------------------------------------
# Every tile clears SCROLLABLE (the pager flips pages on a gesture), which also disables LVGL's built-in "a drag
# cancels the click". So a swipe that starts on a button would still fire its CLICKED on release: record when the
# last gesture was recognised and drop clicks that follow within the window.
GESTURE_CLICK_ABORT_MS = 1500
_last_gesture = None


def note_gesture():
    global _last_gesture
    _last_gesture = time.ticks_ms()


def gesture_recent():
    return _last_gesture is not None and time.ticks_diff(time.ticks_ms(), _last_gesture) < GESTURE_CLICK_ABORT_MS


def on_click(obj, cb, event=None):
    """Attach cb() to CLICKED unless a swipe just happened."""
    def wrapper(e):
        if not gesture_recent():
            cb()
    obj.add_event_cb(wrapper, event or lv.EVENT.CLICKED, None)


# ---- widgets ----------------------------------------------------------------------------------------------
def button(parent, text, color=CARD, text_color=TEXT, cb=None, w=None, h=44, font=16):
    """Touch-friendly button: >=44 px high, pressed-state feedback."""
    b = lv.button(parent)
    b.set_style_bg_color(c(color), 0)
    b.set_style_bg_opa(lv.OPA.COVER, 0)
    b.set_style_radius(8, 0)
    b.set_style_shadow_width(0, 0)
    b.set_style_pad_hor(16, 0)
    b.set_style_pad_ver(8, 0)
    b.set_height(h)
    if w:
        b.set_width(w)
    b.set_style_bg_opa(lv.OPA._70, lv.STATE.PRESSED)
    l = lv.label(b)
    l.set_text(text)
    l.set_style_text_color(c(text_color), 0)
    l.set_style_text_font(getattr(lv, "font_montserrat_%d" % font), 0)
    l.center()
    if cb:
        on_click(b, cb)
    return b


def label(parent, text, size=16, color=TEXT, wrap_w=None):
    l = lv.label(parent)
    l.set_text(text)
    l.set_style_text_font(getattr(lv, "font_montserrat_%d" % size), 0)
    l.set_style_text_color(c(color), 0)
    if wrap_w:
        l.set_width(wrap_w)
        l.set_long_mode(lv.label.LONG_MODE.WRAP)
    return l


def style_textarea(ta):
    ta.set_style_bg_color(c(FIELD_BG), 0)
    ta.set_style_bg_opa(lv.OPA.COVER, 0)
    ta.set_style_text_color(c(TEXT), 0)
    ta.set_style_border_color(c(FIELD_BORDER), 0)
    ta.set_style_border_width(1, 0)
    ta.set_style_border_color(c(ACCENT), lv.STATE.FOCUSED)
    ta.set_style_border_width(2, lv.STATE.FOCUSED)


def style_keyboard(kb):
    kb.set_style_bg_color(c(BG), lv.PART.MAIN)
    kb.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
    kb.set_style_border_width(0, lv.PART.MAIN)
    kb.set_style_bg_color(c(CARD), lv.PART.ITEMS)
    kb.set_style_bg_opa(lv.OPA.COVER, lv.PART.ITEMS)
    kb.set_style_text_color(c(TEXT), lv.PART.ITEMS)
    kb.set_style_border_color(c(FIELD_BORDER), lv.PART.ITEMS)
    kb.set_style_border_width(1, lv.PART.ITEMS)
    kb.set_style_bg_color(c(FIELD_BORDER), lv.PART.ITEMS | lv.STATE.PRESSED)
    kb.set_style_bg_color(c(FIELD_BG), lv.PART.ITEMS | lv.STATE.CHECKED)
    kb.set_style_text_color(c(ACCENT), lv.PART.ITEMS | lv.STATE.CHECKED)


# 3-column numeric pad (no mode switch, no +/-): digits, '.', backspace, and left/right/ok
NUM_MAP = ["1", "2", "3", "\n", "4", "5", "6", "\n", "7", "8", "9", "\n", ".", "0", lv.SYMBOL.BACKSPACE, "\n",
           lv.SYMBOL.LEFT, lv.SYMBOL.RIGHT, lv.SYMBOL.OK, ""]


def num_keyboard(parent, ta):
    kb = lv.keyboard(parent)
    kb.set_mode(lv.keyboard.MODE.NUMBER)
    B = lv.buttonmatrix.CTRL
    kb.set_map(lv.keyboard.MODE.NUMBER, NUM_MAP, [B.CLICK_TRIG | 1] * 13
               + [B.CLICK_TRIG | B.CUSTOM_1 | B.CHECKED | 1])
    kb.set_textarea(ta)
    style_keyboard(kb)
    return kb


def overlay():
    """Full-screen dimmed overlay on the top layer (modal)."""
    ov = lv.obj(lv.layer_top())
    ov.remove_style_all()
    ov.set_size(lv.pct(100), lv.pct(100))
    ov.set_style_bg_color(c(0x000000), 0)
    ov.set_style_bg_opa(lv.OPA._70, 0)
    ov.add_flag(lv.obj.FLAG.CLICKABLE)
    ov.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return ov


def confirm(title, text, on_yes, yes_label="Yes", danger=False):
    ov = overlay()
    p = lv.obj(ov)
    p.set_size(520, lv.SIZE_CONTENT)
    p.center()
    p.set_style_bg_color(c(CARD), 0)
    p.set_style_bg_opa(lv.OPA.COVER, 0)
    p.set_style_radius(14, 0)
    p.set_style_pad_all(20, 0)
    p.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    p.set_style_pad_row(14, 0)
    p.remove_flag(lv.obj.FLAG.SCROLLABLE)
    label(p, title, 24)
    label(p, text, 16, MUTED, wrap_w=470)
    row = lv.obj(p)
    row.remove_style_all()
    row.set_size(lv.pct(100), lv.SIZE_CONTENT)
    row.set_flex_flow(lv.FLEX_FLOW.ROW)
    row.set_flex_align(lv.FLEX_ALIGN.END, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    row.set_style_pad_column(12, 0)
    button(row, "Cancel", CARD, TEXT, lambda: ov.delete()).set_style_bg_color(c(FIELD_BORDER), 0)
    button(row, yes_label, DANGER if danger else ACCENT, ACCENT_TEXT, lambda: (ov.delete(), on_yes()))
    return ov
