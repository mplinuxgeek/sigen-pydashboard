"""Low-level widget helpers + palette for the dashboard (port of the make_*() helpers in dashboard_ui.c).

Colours are plain 0xRRGGBB ints; use rgb() to make an lv color and darken()/lighten() for the derived shades."""
import lvgl as lv

# ---- palette (same values as the ESP-IDF build) -----------------------------------------------------------
NO_DATA = 0x3C4452
SOL_FILL, SOL_BORDER = 0xF59E0B, 0xFBBF24
LOAD_FILL, LOAD_BORDER = 0x14B8A6, 0x2DD4BF
IMP_FILL, IMP_BORDER = 0x6366F1, 0x818CF8
EXP_FILL, EXP_BORDER = 0xA855F7, 0xC084FC
LABEL = 0x94A3B8
TITLE = 0xF1F5F9
BAR_BORDER = 0x334155
DOT_ACTIVE = 0x38BDF8
DIV = 0x1E293B
BATT_BG, BATT_BORDER = 0x0A160E, 0x22C55E
SOL_BG, LOAD_BG = 0x181208, 0x081618
IMP_BG, EXP_BG, GRID_BG_IDLE = 0x101028, 0x160E20, 0x121228
DISCHARGE_RED = 0xEF4444
SCREEN_BG = 0x080A0E
TRACK_BG = 0x141820
STATUS_OK = 0x22C55E
MODBUS_BUSY = 0x38BDF8

LEFT, RIGHT, CENTER = 0, 1, 2

_cache = {}


def rgb(v):
    c = _cache.get(v)
    if c is None:
        if len(_cache) > 200:
            _cache.clear()
        c = _cache[v] = lv.color_hex(v)
    return c


def _mix(v, target, opa):
    r, g, b = (v >> 16) & 255, (v >> 8) & 255, v & 255
    tr, tg, tb = (target >> 16) & 255, (target >> 8) & 255, target & 255
    return (((r * (255 - opa) + tr * opa) // 255) << 16) | (((g * (255 - opa) + tg * opa) // 255) << 8) | \
        ((b * (255 - opa) + tb * opa) // 255)


def darken(v, opa):
    return _mix(v, 0x000000, opa)


def lighten(v, opa):
    return _mix(v, 0xFFFFFF, opa)


def soc_color(soc):
    if soc < 10:
        return 0xEF4444
    if soc < 25:
        return 0xF97316
    if soc < 40:
        return 0xEAB308
    if soc < 60:
        return 0xA3E635
    if soc < 80:
        return 0x4ADE80
    return 0x22C55E


def font(size):
    return getattr(lv, "font_montserrat_%d" % size)


OPA = lv.OPA


def rect(parent, x, y, w, h, bg, radius=0):
    o = lv.obj(parent)
    o.remove_style_all()
    o.set_pos(x, y)
    o.set_size(w, h)
    o.set_style_bg_color(rgb(bg), 0)
    o.set_style_bg_opa(OPA.COVER, 0)
    o.set_style_radius(radius, 0)
    o.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return o


def set_bg(o, v):
    o.set_style_bg_color(rgb(v), 0)


def glow(fill, color):
    """Neon-tube glow for a bar fill (static width/spread/opa; only the colour changes with state)."""
    fill.set_style_shadow_color(rgb(color), 0)
    fill.set_style_shadow_width(14, 0)
    fill.set_style_shadow_spread(0, 0)
    fill.set_style_shadow_opa(OPA._70, 0)


def card(parent, x, y, w, h, bg, border):
    o = lv.obj(parent)
    o.remove_style_all()
    o.set_pos(x, y)
    o.set_size(w, h)
    o.set_style_bg_color(rgb(bg), 0)
    o.set_style_bg_opa(OPA.COVER, 0)
    o.set_style_border_color(rgb(border), 0)
    o.set_style_border_width(2, 0)
    o.set_style_border_opa(OPA.COVER, 0)
    o.set_style_radius(14, 0)
    o.set_style_shadow_color(rgb(border), 0)
    o.set_style_shadow_width(18, 0)
    o.set_style_shadow_spread(1, 0)
    o.set_style_shadow_opa(OPA._50, 0)
    o.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return o


def set_card_accent(o, border, bg=None):
    o.set_style_border_color(rgb(border), 0)
    o.set_style_shadow_color(rgb(border), 0)
    if bg is not None:
        o.set_style_bg_color(rgb(bg), 0)


def outline(parent, x, y, w, h, border, radius=4, width=1):
    o = lv.obj(parent)
    o.remove_style_all()
    o.set_pos(x, y)
    o.set_size(w, h)
    o.set_style_bg_opa(OPA.TRANSP, 0)
    o.set_style_border_color(rgb(border), 0)
    o.set_style_border_width(width, 0)
    o.set_style_border_opa(OPA.COVER, 0)
    o.set_style_radius(radius, 0)
    o.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return o


_ALIGN = None


def label(parent, x, y, align, fnt, color, text, box_w=300):
    """x is the left edge (LEFT), right edge (RIGHT) or centre (CENTER)."""
    global _ALIGN
    if _ALIGN is None:
        _ALIGN = (lv.TEXT_ALIGN.LEFT, lv.TEXT_ALIGN.RIGHT, lv.TEXT_ALIGN.CENTER)
    o = lv.label(parent)
    o.remove_style_all()
    o.set_text(text)
    o.set_style_text_font(fnt, 0)
    o.set_style_text_color(rgb(color), 0)
    bx = x - box_w if align == RIGHT else x - box_w // 2 if align == CENTER else x
    o.set_style_text_align(_ALIGN[align], 0)
    o.set_pos(bx, y)
    o.set_width(box_w)
    return o


def set_text(o, text, color=None):
    o.set_text(text)
    if color is not None:
        o.set_style_text_color(rgb(color), 0)


def title(parent, fnt, color, text):
    o = label(parent, 15, 6, LEFT, fnt, color, text)
    o.set_style_text_letter_space(2, 0)
    return o


class Badge:
    """Content-sized pill around a label; re-anchor after every text change (the width changes with the text)."""

    def __init__(self, parent, fnt, text, anchor_x, anchor_y, align):
        self.ax, self.ay, self.align = anchor_x, anchor_y, align
        b = self.box = lv.obj(parent)
        b.remove_style_all()
        b.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
        b.set_style_pad_hor(9, 0)
        b.set_style_pad_ver(3, 0)
        b.set_style_radius(8, 0)
        b.set_style_bg_color(rgb(LABEL), 0)
        b.set_style_bg_opa(OPA._30, 0)
        b.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.label = lv.label(b)
        self.label.remove_style_all()
        self.label.set_text(text)
        self.label.set_style_text_font(fnt, 0)
        self.label.set_style_text_color(rgb(LABEL), 0)
        self.label.center()
        self.place()

    def set(self, text, accent):
        self.label.set_text(text)
        self.box.set_style_bg_color(rgb(accent), 0)
        self.box.set_style_bg_opa(OPA._30, 0)
        self.label.set_style_text_color(rgb(accent), 0)
        self.place()

    def place(self):
        self.box.update_layout()
        w = self.box.get_width()
        x = self.ax - w if self.align == RIGHT else self.ax - w // 2 if self.align == CENTER else self.ax
        self.box.set_pos(x, self.ay)


def mini_bar(parent, x, y, w, h, fill_col):
    """Framed single-fill bar (track, fill inset 2px, outline). Returns the fill."""
    rect(parent, x, y, w, h, TRACK_BG, 6)
    fill = rect(parent, x + 2, y + 2, 0, h - 4, fill_col, 4)
    outline(parent, x, y, w, h, BAR_BORDER, 6)
    return fill


class PeakMarker:
    """Today's peak: thin line at the peak value plus its kW as plain text next to it. Hidden until a peak exists."""

    def __init__(self, parent, bar_y):
        self.line = rect(parent, 0, bar_y + 2, 3, 20, TITLE)
        self.line.add_flag(lv.obj.FLAG.HIDDEN)
        self.tag = lv.label(parent)
        self.tag.remove_style_all()
        self.tag.set_style_text_font(font(14), 0)
        self.tag.set_style_text_color(rgb(TITLE), 0)
        self.tag.add_flag(lv.obj.FLAG.HIDDEN)

    def set(self, origin_x, span, bar_y, peak_kw, scale_kw, align):
        if peak_kw < 0.05 or scale_kw < 0.1:
            self.line.add_flag(lv.obj.FLAG.HIDDEN)
            self.tag.add_flag(lv.obj.FLAG.HIDDEN)
            return
        frac = min(peak_kw / scale_kw, 0.97)
        x = origin_x + int(span * frac)
        self.line.set_pos(x, bar_y + 2)
        self.tag.set_text("%.1f" % peak_kw)
        self.tag.update_layout()
        tw = self.tag.get_width()
        if align > 0:
            tx = x + 6
        elif align < 0:
            tx = x - 6 - tw
        elif frac > 0.85:
            tx = x - 6 - tw
        else:
            tx = x + 6
        self.tag.set_pos(max(tx, 1), bar_y + 5)
        self.line.remove_flag(lv.obj.FLAG.HIDDEN)
        self.tag.remove_flag(lv.obj.FLAG.HIDDEN)
