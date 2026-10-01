"""Page navigator: six full-screen pages (Dashboard, Graph, Monthly, System Info / Settings / WiFi) flipped instantly
by a horizontal swipe (no drag-follow), a dot strip that fades after 3 s, and an idle timer that returns to the
Dashboard after 30 s without a touch. Pages are built once; only the active one is visible."""
import time

import lvgl as lv

from . import common, kit

DOT_SIZE, DOT_GAP, DOT_HIDE_MS = 10, 16, 3000
IDLE_RETURN_MS = 30000


class Shell:
    def __init__(self, app, board, page_defs):
        """page_defs: [(name, builder(parent, shell) -> page object or None)]"""
        self.app, self.board = app, board
        self.W, self.H = board.W, board.H
        self.names = [n for n, _b in page_defs]
        self.active = 0
        self.pages, self.objs = [], []
        self.suppress = False
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

    # ---- navigation -----------------------------------------------------------------------------------
    def go(self, idx):
        idx = max(0, min(idx, len(self.objs) - 1))
        self.idle_timer.reset()
        if idx == self.active:
            self._paint_dots(lv.OPA.COVER)
            self.dot_timer.reset()
            return
        prev = self.active
        self.objs[prev].add_flag(lv.obj.FLAG.HIDDEN)
        self.active = idx
        self.objs[idx].remove_flag(lv.obj.FLAG.HIDDEN)
        self._show(idx, prev)

    def _show(self, idx, prev=None):
        t0 = time.ticks_ms()
        for i, p in enumerate(self.pages):
            if p is None:
                continue
            if i == prev and hasattr(p, "on_hide"):
                p.on_hide()
        t1 = time.ticks_ms()
        p = self.pages[idx]
        if p is not None and hasattr(p, "on_show"):
            try:
                p.on_show()
            except Exception as e:
                self.app.log.error("ui: page %s on_show: %r" % (self.names[idx], e))
        t2 = time.ticks_ms()
        if time.ticks_diff(t2, t0) > 60:               # slow page switch: say where the time went (python side only)
            self.app.log.info("ui: %s: hide %s %d ms, show %s %d ms" % (
                "switch", self.names[prev] if prev is not None else "-", time.ticks_diff(t1, t0), self.names[idx],
                time.ticks_diff(t2, t1)))
        self._paint_dots(lv.OPA.COVER)
        self.dot_timer.reset()

    def go_name(self, name):
        self.go(self.names.index(name))

    def _gesture(self, e):
        ind = self.board._indev
        if self.suppress or ind is None:
            return
        common.note_gesture()
        d = ind.get_gesture_dir()
        if d == lv.DIR.LEFT:
            self.go(self.active + 1)
        elif d == lv.DIR.RIGHT:
            self.go(self.active - 1)

    def _touch(self, e):
        self.idle_timer.reset()
        notify = self.app.services.get("blank")
        if notify:
            notify.touched()

    def _idle(self, t):
        if self.active == 0:
            return
        self.go(0)
