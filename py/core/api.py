"""HTTP API routes (the JSON interface documented in docs/http-api.md). Grows as features land."""
import gc
import time

import machine

from . import http, log, tz

VERSION = "0.1.0"


def register(app, server):
    svc = app.services
    state = svc["state"]

    def uptime_s():
        return time.ticks_ms() // 1000

    def health(req):
        import esp32
        cap = {"internal": 1 << 11, "psram": 1 << 10}
        mem = {}
        for name, c in cap.items():
            t = f = big = 0
            for h in esp32.idf_heap_info(c):
                t += h[0]
                f += h[1]
                big = max(big, h[2])
            mem[name] = {"total": t, "free": f, "largest": big}
        return {"ok": True, "uptime_s": uptime_s(), "version": VERSION, "reset_cause": machine.reset_cause(),
                "heap": mem, "py_free": gc.mem_free(), "requests": server.requests}

    def metrics(req):
        d = state.snapshot()
        d["alive"] = state.alive
        d["cycles"] = state.cycles
        return d

    shot_busy = []

    async def screenshot(req):
        import board
        from . import png
        if shot_busy:
            return http.err(503, "screenshot already in progress")
        shot_busy.append(1)
        try:
            frame = bytearray(board.front())        # snapshot: the live buffer is recycled by LVGL
            data = await png.encode_rgb565(frame, board.W, board.H)
            return 200, "image/png", data
        finally:
            shot_busy.clear()

    server.route("GET", "/api/screenshot", screenshot)
    server.route("GET", "/api/health", health)
    server.route("GET", "/api/metrics", metrics)
