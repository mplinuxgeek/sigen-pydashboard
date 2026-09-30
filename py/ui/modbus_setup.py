"""First-run screen: enter the SigenStor's IP (and port) before the dashboard has anything to show."""
import lvgl as lv

from . import common as C
from core import modbus


def board_w():
    import board
    return board.W


class ModbusSetup:
    def __init__(self, app, on_done):
        self.app, self.on_done = app, on_done
        ov = self.ov = C.overlay()
        ov.set_style_bg_color(C.c(C.BG), 0)
        ov.set_style_bg_opa(lv.OPA.COVER, 0)
        ov.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        ov.set_style_pad_all(12, 0)
        ov.set_style_pad_row(10, 0)
        C.label(ov, "Set up your SigenStor", 24, C.TEXT)
        C.label(ov, "Enter the IP address of your Sigenergy device on this network. You can change this later from Settings.",
                16, C.MUTED, wrap_w=board_w() - 30)
        row = lv.obj(ov)
        row.remove_style_all()
        row.set_size(lv.pct(100), lv.SIZE_CONTENT)
        row.set_flex_grow(1)
        import board
        row.set_flex_flow(lv.FLEX_FLOW.COLUMN if board.portrait else lv.FLEX_FLOW.ROW)
        row.set_style_pad_column(16, 0)
        left = lv.obj(row)
        left.remove_style_all()
        left.set_size(lv.pct(100) if board.portrait else lv.pct(50), lv.SIZE_CONTENT if board.portrait else lv.pct(100))
        left.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        left.set_style_pad_row(10, 0)
        self.ip = self._field(left, "IP address", "0123456789.", modbus.DEFAULT_IP)
        self.port = self._field(left, "Port", "0123456789", str(modbus.DEFAULT_PORT))
        self.status = C.label(left, "", 16, 0xF87171)
        btns = lv.obj(left)
        btns.remove_style_all()
        btns.set_size(lv.pct(100), lv.SIZE_CONTENT)
        btns.set_style_pad_top(8, 0)
        btns.set_flex_flow(lv.FLEX_FLOW.ROW)
        btns.set_style_pad_column(8, 0)
        C.button(btns, "Skip for now", C.CARD, C.TEXT, self.skip).set_flex_grow(1)
        C.button(btns, "Continue", C.ACCENT, C.ACCENT_TEXT, self.cont).set_flex_grow(1)
        right = lv.obj(row)
        right.remove_style_all()
        right.set_size(lv.pct(100) if board.portrait else lv.pct(50), lv.pct(100))
        right.set_flex_grow(1)
        right.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.kb = C.num_keyboard(right, self.ip)
        self.kb.set_width(lv.pct(100))
        self.kb.set_flex_grow(1)
        C.on_click(self.kb, self.cont, lv.EVENT.READY)

    def _field(self, parent, name, accepted, initial):
        r = lv.obj(parent)
        r.remove_style_all()
        r.set_size(lv.pct(100), 44)
        r.set_flex_flow(lv.FLEX_FLOW.ROW)
        r.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        r.set_style_pad_column(8, 0)
        l = C.label(r, name, 16, C.MUTED)
        l.set_width(110)
        ta = lv.textarea(r)
        ta.set_size(lv.pct(100), 44)
        ta.set_flex_grow(1)
        ta.set_one_line(True)
        ta.set_accepted_chars(accepted)
        ta.set_text(initial)
        C.style_textarea(ta)
        ta.add_event_cb(lambda e: getattr(self, "kb", None) and self.kb.set_textarea(ta), lv.EVENT.FOCUSED, None)
        return ta

    def skip(self):
        self.finish()

    def cont(self):
        ip = self.ip.get_text().strip()
        parts = ip.split(".")
        if ip == modbus.DEFAULT_IP or len(parts) != 4 or not all(p.isdigit() and int(p) < 256 for p in parts):
            self.status.set_text("Enter the device's full IP, or tap Skip")
            return
        ptxt = self.port.get_text()
        port = int(ptxt) if ptxt else modbus.DEFAULT_PORT
        if not 0 < port < 65536:
            self.status.set_text("Port must be 1-65535")
            return
        s = self.app.settings
        s.set("modbus.ip", ip)
        s.set("modbus.port", port)
        self.app.services["poller"].apply_config()
        self.app.log.info("setup: modbus target %s:%d" % (ip, port))
        self.finish()

    def finish(self):
        self.ov.delete()
        self.on_done()
