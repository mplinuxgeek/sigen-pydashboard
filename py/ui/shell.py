"""Page navigator: six full-screen pages (Dashboard, Graph, Monthly, System Info / Settings / WiFi). A horizontal swipe
slides to the neighbouring page: the pages follow the finger while it is down, then ease to the destination (or spring
back if the drag was short). Programmatic changes (API, status icons) animate the same way. A dot strip fades after 3 s
and an idle timer returns to the Dashboard after 30 s without a touch. Pages are built once."""
import time

import lvgl as lv

from . import common, kit

DOT_SIZE, DOT_GAP, DOT_HIDE_MS = 10, 16, 3000
IDLE_RETURN_MS = 30000
SLIDE_MS = 240          # full-width slide; shorter remaining distances take proportionally less
COMMIT_FRACTION = 0.3   # drag further than this fraction of the width to change page on release


class Shell:
    def __init__(self, app, board, page_defs):
        """page_defs: [(name, builder(parent, shell) -> page object or None)]"""
        self.app, self.board = app, board
        self.W, self.H = board.W, board.H
        self.names = [n for n, _b in page_defs]
        self.active = 0
        self.pages, self.objs = [], []
        self.suppress = False
        self._drag = None       # finger-follow state while a swipe is in progress
        self._slide = None      # ease-out animation state
        scr = self.scr = lv.screen_active()
        scr.clean()
        scr.set_style_bg_color(kit.rgb(kit.SCREEN_BG), 0)
        scr.set_style_bg_opa(lv.OPA.COVER, 0)
        scr.remove_flag(lv.obj.FLAG.SCROLLABLE)
        for name, build in page_defs:
            o = lv.obj(scr)
            o.remove_style_all()
            o.set_size(self.W, self.H)
            o.set_pos(0, 0)
            o.remove_flag(lv.obj.FLAG.SCROLLABLE)
            o.add_flag(lv.obj.FLAG.HIDDEN)
            self.objs.append(o)
            try:
                self.pages.append(build(o, self))
            except Exception as e:
                app.log.error("ui: page %s failed to build: %r" % (name, e))
                self.pages.append(None)
        self.objs[0].remove_flag(lv.obj.FLAG.HIDDEN)
        self._build_dots()
        self.dot_timer = lv.timer_create(self._hide_dots, DOT_HIDE_MS, None)
        self.idle_timer = lv.timer_create(self._idle, IDLE_RETURN_MS, None)
        ind = board._indev
        if ind:
            ind.add_event_cb(self._gesture, lv.EVENT.GESTURE, None)
            for ev in (lv.EVENT.PRESSED, lv.EVENT.PRESSING):
                ind.add_event_cb(self._touch, ev, None)
        self._show(0)

    # ---- dots -----------------------------------------------------------------------------------------
    def _build_dots(self):
        n = len(self.names)
        total = n * DOT_SIZE + (n - 1) * DOT_GAP
        x0, y = (self.W - total) // 2, self.H - 18
        self.dots = []
        for i in range(n):
            d = lv.obj(self.scr)
            d.remove_style_all()
            d.remove_flag(lv.obj.FLAG.SCROLLABLE)
            d.remove_flag(lv.obj.FLAG.CLICKABLE)
            d.set_size(DOT_SIZE, DOT_SIZE)
            d.set_style_radius(DOT_SIZE // 2, 0)
            d.set_style_bg_opa(lv.OPA.COVER, 0)
            d.set_pos(x0 + i * (DOT_SIZE + DOT_GAP), y)
            self.dots.append(d)

    def _paint_dots(self, opa):
        for i, d in enumerate(self.dots):
            d.set_style_bg_color(kit.rgb(kit.DOT_ACTIVE if i == self.active else kit.LABEL), 0)
            d.set_style_opa(opa, 0)

    def _hide_dots(self, t):
        for d in self.dots:
            d.set_style_opa(lv.OPA.TRANSP, 0)

    def animated(self):
        return bool(self.app.settings.get("ui.animate", False))

    # ---- navigation -----------------------------------------------------------------------------------
    def go(self, idx):
        """Switch page: an animated slide to a neighbour, an instant jump for anything further away."""
        idx = max(0, min(idx, len(self.objs) - 1))
        self.idle_timer.reset()
        if self._drag or self._slide:
            return
        if idx == self.active:
            self._paint_dots(lv.OPA.COVER)
            self.dot_timer.reset()
            return
        if abs(idx - self.active) == 1 and self.animated():
            self._slide_to(idx - self.active)
            return
        prev = self.active
        self.objs[prev].add_flag(lv.obj.FLAG.HIDDEN)
        self.active = idx
        self.objs[idx].remove_flag(lv.obj.FLAG.HIDDEN)
        self._show(idx, prev)

    def _show(self, idx, prev=None):
        if prev is not None and self.pages[prev] is not None and hasattr(self.pages[prev], "on_hide"):
            self.pages[prev].on_hide()
        self._enter(idx)
        self._paint_dots(lv.OPA.COVER)
        self.dot_timer.reset()

    def _enter(self, idx):
        p = self.pages[idx]
        if p is not None and hasattr(p, "on_show"):
            try:
                p.on_show()
            except Exception as e:
                self.app.log.error("ui: page %s on_show: %r" % (self.names[idx], e))

    def go_name(self, name):
        self.go(self.names.index(name))

    # ---- slide machinery ------------------------------------------------------------------------------
    def _prepare(self, d):
        """Bring the neighbouring page (d = +1 next, -1 previous) in just off-screen, ready to slide."""
        old, new = self.active, self.active + d
        a, b = self.objs[old], self.objs[new]
        b.set_x(d * self.W)
        b.remove_flag(lv.obj.FLAG.HIDDEN)
        b.move_foreground()
        self._enter(new)
        return {"d": d, "old": old, "new": new, "a": a, "b": b, "off": 0}

    def _slide_to(self, d):
        st = self._prepare(d)
        self._animate(st, -d * self.W, self._commit)

    def _animate(self, st, end_off, done):
        """Ease-out from the current offset to end_off (a lands at -d*W when committed, 0 when cancelled)."""
        a, b, d, w = st["a"], st["b"], st["d"], st["W"] if "W" in st else self.W
        start = st["off"]
        t0 = time.ticks_ms()
        dur = max(60, int(SLIDE_MS * abs(end_off - start) / max(1, w)))

        def step(t):
            k = min(1.0, time.ticks_diff(time.ticks_ms(), t0) / dur)
            e = 1 - (1 - k) * (1 - k) * (1 - k)
            off = start + (end_off - start) * e
            a.set_x(int(off))
            b.set_x(int(d * w + off))
            if k >= 1.0:
                tm.delete()
                self._slide = None
                done(st)
        tm = lv.timer_create(step, 16, None)
        self._slide = tm

    def _commit(self, st):
        st["a"].set_x(0)
        st["b"].set_x(0)
        st["a"].add_flag(lv.obj.FLAG.HIDDEN)
        prev = self.pages[st["old"]]
        if prev is not None and hasattr(prev, "on_hide"):
            prev.on_hide()
        self.active = st["new"]
        self._paint_dots(lv.OPA.COVER)
        self.dot_timer.reset()

    def _cancel(self, st):
        st["a"].set_x(0)
        st["b"].set_x(0)
        st["b"].add_flag(lv.obj.FLAG.HIDDEN)
        p = self.pages[st["new"]]
        if p is not None and hasattr(p, "on_hide"):
            p.on_hide()

    # ---- finger-follow swipe ----------------------------------------------------------------------------
    def _gesture(self, e):
        ind = self.board._indev
        if self.suppress or ind is None or self._drag or self._slide:
            return
        common.note_gesture()
        d = ind.get_gesture_dir()
        if d == lv.DIR.LEFT and self.active < len(self.objs) - 1:
            step = 1
        elif d == lv.DIR.RIGHT and self.active > 0:
            step = -1
        else:
            return
        self.idle_timer.reset()
        if not self.animated():                      # instant flip (default): no drag-follow, no animation
            self.go(self.active + step)
            return
        st = self._prepare(step)
        pt = lv.point_t()
        ind.get_point(pt)
        st["start_x"] = pt.x
        st["ind"] = ind
        st["timer"] = lv.timer_create(lambda t: self._drag_tick(), 16, None)
        self._drag = st

    def _drag_tick(self):
        st = self._drag
        ind = st["ind"]
        if ind.get_state() != lv.INDEV_STATE.PRESSED:
            self._end_drag()
            return
        pt = lv.point_t()
        ind.get_point(pt)
        d, w = st["d"], self.W
        # progress is positive only while the finger keeps moving the "right" way; a reversal clamps to 0
        progress = max(0, min(w, -d * (pt.x - st["start_x"])))
        off = -d * progress
        st["off"] = off
        st["a"].set_x(off)
        st["b"].set_x(d * w + off)

    def _end_drag(self):
        st = self._drag
        self._drag = None
        st["timer"].delete()
        d, w = st["d"], self.W
        commit = abs(st["off"]) > w * COMMIT_FRACTION
        self._animate(st, -d * w if commit else 0, self._commit if commit else self._cancel)

    def _touch(self, e):
        self.idle_timer.reset()
        notify = self.app.services.get("blank")
        if notify:
            notify.touched()

    def _idle(self, t):
        if self.active == 0:
            return
        self.go(0)
