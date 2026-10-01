"""HTTP API: the JSON interface documented in docs/http-api.md (same routes and shapes as the ESP-IDF firmware).

Open GETs are read-only telemetry; anything that writes, erases, reboots or reveals a credential needs the admin token
(X-OTA-Token). Errors are always {"error": "..."} with a real status code."""
import asyncio
import gc
import json
import time

import machine

from . import http, log, tz, version
from . import timeutil as T

VERSION = version.VERSION
PROJECT = "sigen-dashboard-py"

# (method, path, auth, description, example curl or None)
ROUTES = (
    ("GET", "/api", False, "this index (JSON, or this page in a browser)", None),
    ("GET", "/api/health", False, "liveness, heap, reset reason, uptime", None),
    ("GET", "/api/system", False, "full device snapshot", None),
    ("GET", "/api/version", False, "running and inactive slot versions", None),
    ("GET", "/api/ota", False, "running build info", None),
    ("POST", "/api/ota", True, "upload a firmware .bin, then reboot",
     'curl -X POST -H "X-OTA-Token: $T" --data-binary @micropython.bin http://HOST/api/ota'),
    ("POST", "/api/ota/py", True, "upload the Python application (a .tar of py/), apply with rollback, reboot",
     'curl -X POST -H "X-OTA-Token: $T" --data-binary @app.tar http://HOST/api/ota/py'),
    ("POST", "/api/ota-token", True, "rotate the admin token",
     """curl -X POST -H "X-OTA-Token: $T" -d '{"token":"new-token"}' http://HOST/api/ota-token"""),
    ("POST", "/api/reset", True, "reboot the device", 'curl -X POST -H "X-OTA-Token: $T" http://HOST/api/reset'),
    ("GET", "/api/logs", True, "log ring from ?since=<seq>; see X-Log-Next / X-Log-Total",
     'curl -H "X-OTA-Token: $T" "http://HOST/api/logs?since=0"'),
    ("POST", "/api/coredump/erase", True, "clear the stored panic record (no-op on MicroPython)",
     'curl -X POST -H "X-OTA-Token: $T" http://HOST/api/coredump/erase'),
    ("GET", "/api/history", False, "history as JSON", None),
    ("GET", "/api/history.csv", False, "history as CSV", None),
    ("POST", "/api/history/import", True, "<b>replaces</b> all stored history from CSV",
     'curl -X POST -H "X-OTA-Token: $T" --data-binary @history.csv http://HOST/api/history/import'),
    ("POST", "/api/history/clear", True, "clear the stored history", 'curl -X POST -H "X-OTA-Token: $T" http://HOST/api/history/clear'),
    ("GET", "/api/monthly", False, "monthly totals as JSON (history, current, current_billing)", None),
    ("GET", "/api/monthly.csv", False, "completed months' Solar/Grid Import/Grid Export/Load totals as CSV", None),
    ("POST", "/api/monthly/import", True,
     "<b>replaces</b> all completed monthly totals from CSV (the in-progress month is untouched)",
     'curl -X POST -H "X-OTA-Token: $T" --data-binary @monthly.csv http://HOST/api/monthly/import'),
    ("POST", "/api/monthly/days/import", True,
     "overwrites the Month-to-Date day-ring with exact per-day totals from CSV (date,solar_kwh,grid_import_kwh,"
     "grid_export_kwh,load_kwh)", 'curl -X POST -H "X-OTA-Token: $T" --data-binary @days.csv http://HOST/api/monthly/days/import'),
    ("GET", "/api/screenshot", False, "PNG of the live screen", None),
    ("POST", "/api/swipe", False, "navigate the UI as a swipe would (?dir=left|right, or none to hold the page)",
     'curl -X POST "http://HOST/api/swipe?dir=left"'),
    ("GET", "/api/view", False, "which page the UI is showing, without moving it", None),
    ("GET", "/api/backlight", False, "full backlight status: level, source, curve, next transition", None),
    ("POST", "/api/backlight/set", True, "set backlight brightness (?percent=0-100)",
     'curl -X POST -H "X-OTA-Token: $T" "http://HOST/api/backlight/set?percent=50"'),
    ("POST", "/api/backlight/config", True, "master gate, GPIO pin and curve preset",
     """curl -X POST -H "X-OTA-Token: $T" -d '{"enabled":true,"gpio":6,"preset":"gentle"}' http://HOST/api/backlight/config"""),
    ("POST", "/api/backlight/curve", True, "custom dimming curve, up to 8 points",
     """curl -X POST -H "X-OTA-Token: $T" -d '{"points":[["07:00",80],["21:00",25]]}' http://HOST/api/backlight/curve"""),
    ("GET", "/api/metrics", False, "live battery/PV/grid/load readings, same values the dashboard shows", None),
    ("POST", "/api/tuning", True, "rendering knobs ui.partial / ui.rows / ui.single (null = default), applied on restart",
     """curl -X POST -H "X-OTA-Token: $T" -d '{"ui.single":true}' http://HOST/api/tuning"""),
    ("GET", "/api/settings", False, "Modbus/sizing/blanking/night-off/timezone/orientation snapshot (no OTA key)", None),
    ("POST", "/api/settings", True,
     "update any subset of ip+port, inverter_kw, solar_kw, ota_pin, blank_enabled, blank_timeout_s, night_enabled, "
     "night_start_minute, night_end_minute, country_code+zone, billing_date, billing_mode, billing_anchor, billing_cycle_length_days",
     """curl -X POST -H "X-OTA-Token: $T" -d '{"inverter_kw":25}' http://HOST/api/settings"""),
    ("POST", "/api/orientation", True, "set display orientation and restart to apply",
     """curl -X POST -H "X-OTA-Token: $T" -d '{"portrait":true}' http://HOST/api/orientation"""),
    ("POST", "/api/reset-wifi-modbus", True, "<b>forgets</b> saved WiFi + Modbus config, then restarts",
     'curl -X POST -H "X-OTA-Token: $T" http://HOST/api/reset-wifi-modbus'),
    ("POST", "/api/factory-reset", True, "<b>erases</b> everything (WiFi, Modbus, history, totals, settings), then restarts",
     'curl -X POST -H "X-OTA-Token: $T" http://HOST/api/factory-reset'),
    ("GET", "/tzdata.json", False, "raw timezone table backing the Settings tab's Country/Region pickers", None),
    ("GET", "/", False, "device landing page: Metrics + History + Info + Settings + Firmware tabs (same as /index.html)", None),
    ("GET", "/index.html", False, "device landing page", None),
    ("GET", "/history-chart.html", False, "interactive Chart.js graph of stored history", None),
    ("GET", "/chart.min.js", False, "Chart.js bundle used by /history-chart.html", None),
)

_GRID_NAMES = ("on_grid", "off_grid_auto", "off_grid_manual")


def _plain(desc):
    return desc.replace("<b>", "").replace("</b>", "")


def _mem(cap):
    import esp32
    t = f = big = 0
    for h in esp32.idf_heap_info(cap):
        t += h[0]
        f += h[1]
        big = max(big, h[2])
    return t, f, big


def _hhmm(s):
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":" or not (s[:2] + s[3:]).isdigit():
        return -1
    h, m = int(s[:2]), int(s[3:])
    return h * 60 + m if h < 24 and m < 60 else -1


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def register(app, server):
    svc = app.services
    state, settings = svc["state"], app.settings
    if not settings.get("ota.token"):
        import binascii
        import os
        settings.set("ota.token", binascii.hexlify(os.urandom(8)).decode())
        log.info("api: generated a new admin token (Settings > OTA Key)")

    def reboot_soon(reason):
        async def later():
            await asyncio.sleep_ms(500)
            from . import system
            system.reboot(app, reason)
        asyncio.create_task(later())

    def body_json(req):
        try:
            d = json.loads(req.body) if req.body else None
        except ValueError:
            return None, http.err(400, "body is not valid JSON")
        if not isinstance(d, dict):
            return None, http.err(400, "expected a small JSON object")
        return d, None

    # ---- info ---------------------------------------------------------------------------------------------
    def health(req):
        _t, f, big = _mem(1 << 11)
        _pt, pf, _pb = _mem(1 << 10)
        from . import log as L
        return {"version": VERSION, "uptime_ms": time.ticks_ms(), "reset_reason": _reset_reason(),
                "last_reboot_trigger": settings.get("last_reboot"), "last_reboot_trigger_uptime_s": None,
                "lvgl_lock_held_ms": 0, "lvgl_lock_holder": None, "internal_free": f, "internal_largest_block": big,
                "internal_min_free": f, "psram_free": pf, "log_bytes": L.rev, "last_coredump": "none",
                "py_free": gc.mem_free(), "requests": server.requests, "ui": dict(__import__("board").stats, slide_ms=__import__("board").slide_ms),
                "time": {"unix": T.unix_now(), "synced": bool(svc["ntp"].synced), "status": svc["ntp"].status_text()}}

    def _reset_reason():
        names = {machine.PWRON_RESET: "power-on", machine.HARD_RESET: "hard reset", machine.WDT_RESET: "watchdog",
                 machine.DEEPSLEEP_RESET: "deep sleep", machine.SOFT_RESET: "software"}
        return names.get(machine.reset_cause(), "unknown")

    def system(req):
        from . import ota
        wifi, ntp = svc["wifi"], svc["ntp"]
        ip, port = svc["poller"].config()
        _t, f, big = _mem(1 << 11)
        _pt, pf, _pb = _mem(1 << 10)
        z = tz.selection()
        info = ota.info()
        return {
            "firmware": {"version": VERSION, "project": PROJECT, "idf": info["idf_version"], "built": info["built"],
                         "running_slot": info["running_partition"], "image_state": info["image_state"],
                         "inactive_slot": info["inactive_slot"], "inactive_version": info["inactive_version"]},
            "boot": {"uptime_s": time.ticks_ms() // 1000, "reset_reason": _reset_reason(), "last_coredump": "none",
                     "last_reboot_trigger": settings.get("last_reboot")},
            "network": {"connected": wifi.connected, "ssid": wifi.ssid if wifi.connected else "", "ip": wifi.ip,
                        "rssi_dbm": wifi.rssi() or 0, "mac": wifi.mac.lower()},
            "ntp": {"synced": ntp.synced, "status": ntp.status_text(), "server": ntp.server or "",
                    "sync_count": ntp.sync_count,
                    "seconds_since_sync": -1 if ntp.last_ok is None else time.ticks_diff(time.ticks_ms(), ntp.last_ok) // 1000,
                    "timezone": z[3], "posix_tz": z[2]},
            "inverter": {"host": ip, "port": port, "responding": state.alive, "model": state.model, "serial": state.serial},
            "memory": {"internal_free": f, "internal_largest_block": big, "internal_min_free": f, "psram_free": pf,
                       "flash_mb": 8, "psram_mb": 8, "python_free": gc.mem_free()},
            "display": {"orientation": settings.get("orientation", "landscape"),
                        "backlight_percent": svc["backlight"].resolve()[0]},
            "hardware": {"chip": "ESP32-S3, 2 cores"}}

    def metrics(req):
        g, v = state.get, state.valid
        inv = float(settings.get("sizing.inverter_kw", 25.0))
        sol = float(settings.get("sizing.solar_kw", 25.0))
        gs = int(g("grid_status", 0))
        return {"alive": state.alive,
                "battery": {"soc_pct": g("soc", 0.0), "soc_valid": v("soc"), "power_kw": g("batt_power", 0.0),
                            "power_valid": v("batt_power"), "capacity_kwh": g("batt_cap", 0.0), "capacity_valid": v("batt_cap"),
                            "temp_c": g("batt_temp", 0.0), "temp_valid": v("batt_temp")},
                "pv": {"power_kw": g("pv_power", 0.0), "power_valid": v("pv_power"), "daily_kwh": g("pv_daily", 0.0),
                       "daily_valid": v("pv_daily")},
                "grid": {"power_kw": g("grid_power", 0.0), "power_valid": v("grid_power"),
                         "status": _GRID_NAMES[gs] if 0 <= gs < 3 else "unknown", "status_valid": v("grid_status"),
                         "daily_import_kwh": g("grid_daily_import", 0.0), "daily_import_valid": v("grid_daily_import"),
                         "daily_export_kwh": g("grid_daily_export", 0.0), "daily_export_valid": v("grid_daily_export")},
                "load": {"power_kw": g("load_power", 0.0), "power_valid": v("load_power"),
                         "daily_kwh": g("load_daily", 0.0), "daily_valid": v("load_daily")},
                "sizing": {"inverter_kw": inv, "solar_kw": sol}}

    # ---- settings ----------------------------------------------------------------------------------------
    def settings_get(req):
        ip, port = svc["poller"].config()
        z = tz.selection()
        b, n = svc["blank"], svc["blank"]
        a = int(settings.get("billing.anchor", 20260101))
        return {"modbus": {"ip": ip, "port": port},
                "sizing": {"inverter_kw": float(settings.get("sizing.inverter_kw", 25.0)),
                           "solar_kw": float(settings.get("sizing.solar_kw", 25.0))},
                "blanking": {"enabled": b.enabled, "timeout_s": b.timeout_s},
                "night": {"enabled": n.night_enabled, "start_minute": n.night_start, "end_minute": n.night_end},
                "timezone": {"country_code": z[0], "zone": z[1], "label": z[3]},
                "orientation": {"portrait": settings.get("orientation", "landscape") == "portrait"},
                "billing": {"date": int(settings.get("billing.day", 1)), "mode": int(settings.get("billing.mode", 0)),
                            "anchor": "%04d-%02d-%02d" % (a // 10000, a // 100 % 100, a % 100),
                            "cycle_length_days": int(settings.get("billing.cycle_len", 28))}}

    def settings_post(req):
        d, err = body_json(req)
        if err:
            return err
        E = http.err
        ip, port = d.get("ip"), d.get("port")
        if ip is not None:
            if not isinstance(ip, str) or not ip or len(ip) >= 40:
                return E(400, "ip must be non-empty and under 40 chars")
        if port is not None and (not isinstance(port, int) or not 0 < port < 65536):
            return E(400, "port must be 1-65535")
        if (ip is not None) != (port is not None):
            return E(400, "ip and port must be set together")

        def num(key, lo, hi, msg):
            v = d.get(key)
            if v is None:
                return None
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                raise ValueError(msg)
            return v
        try:
            inv = num("inverter_kw", 1, 100, "inverter_kw must be 1-100")
            sol = num("solar_kw", 1, 100, "solar_kw must be 1-100")
            bdate = num("billing_date", 1, 31, "billing_date must be 1-31")
            bmode = num("billing_mode", 0, 1, "billing_mode must be 0 (calendar) or 1 (fixed cycle)")
            clen = num("billing_cycle_length_days", 1, 365, "billing_cycle_length_days must be 1-365")
            bto = num("blank_timeout_s", 1, 10 ** 6, "blank_timeout_s must be positive")
            ns = num("night_start_minute", 0, 1439, "night_start_minute must be 0-1439")
            ne = num("night_end_minute", 0, 1439, "night_end_minute must be 0-1439")
        except ValueError as e:
            return E(400, str(e))
        if ns is not None and ne is not None and ns == ne:
            return E(400, "night_start_minute and night_end_minute must differ")
        anchor = None
        if "billing_anchor" in d:
            try:
                y, m, dd = (int(x) for x in str(d["billing_anchor"]).split("-"))
                assert 2000 <= y <= 2099 and 1 <= m <= 12 and 1 <= dd <= 31
                anchor = y * 10000 + m * 100 + dd
            except (ValueError, AssertionError):
                return E(400, 'billing_anchor must be "YYYY-MM-DD"')
        sel = None
        if "country_code" in d or "zone" in d:
            cc, zn = d.get("country_code"), d.get("zone")
            if not (isinstance(cc, str) and isinstance(zn, str)):
                return E(400, "country_code and zone must be set together")
            try:
                match = [z for z in tz.zones(cc) if z[0] == zn]
            except KeyError:
                match = []
            if not match:
                return E(400, "unknown country_code/zone -- see GET /tzdata.json")
            sel = (cc,) + match[0]
        if isinstance(d.get("ota_pin"), str):
            settings.set("ota.token", d["ota_pin"])
        if inv is not None:
            settings.set("sizing.inverter_kw", float(inv))
        if sol is not None:
            settings.set("sizing.solar_kw", float(sol))
        if inv is not None or sol is not None:
            dash = svc.get("dashboard")
            if dash:
                dash.sizing_changed = True
        if bdate is not None:
            settings.set("billing.day", int(bdate))
        if bmode is not None:
            settings.set("billing.mode", int(bmode))
        if anchor is not None:
            settings.set("billing.anchor", anchor)
        if clen is not None:
            settings.set("billing.cycle_len", int(clen))
        svc["monthly"].apply_settings()
        blank = svc["blank"]
        if isinstance(d.get("blank_enabled"), bool) or bto is not None:
            blank.set_blank(d.get("blank_enabled"), bto)
        if isinstance(d.get("night_enabled"), bool) or ns is not None or ne is not None:
            blank.set_night(d.get("night_enabled"), ns, ne)
        if sel:
            tz.select(sel[0], sel[1], sel[2], sel[3])
        if ip is not None:
            settings.set("modbus.ip", ip)
            settings.set("modbus.port", port)
            settings.delete("modbus.skipped")
            svc["poller"].apply_config()
        return {"ok": True}

    def orientation(req):
        d, err = body_json(req)
        if err:
            return err
        if not isinstance(d.get("portrait"), bool):
            return http.err(400, "portrait must be a boolean")
        settings.set("orientation", "portrait" if d["portrait"] else "landscape")
        log.warn("api: orientation changed to %s over /api/orientation -- restarting" % ("portrait" if d["portrait"] else "landscape"))
        reboot_soon("POST /api/orientation")
        return {"ok": True, "rebooting": True}

    def reset(req):
        log.warn("api: reboot requested over /api/reset")
        reboot_soon("POST /api/reset")
        return {"ok": True, "rebooting": True}

    def reset_wifi_modbus(req):
        log.warn("api: WiFi + Modbus reset requested")
        for k in ("wifi.ssid", "wifi.pass", "modbus.ip", "modbus.port", "modbus.skipped", "grid.base"):
            settings.delete(k)
        reboot_soon("POST /api/reset-wifi-modbus")
        return {"ok": True, "rebooting": True}

    def factory_reset(req):
        log.warn("api: factory reset requested")

        async def later():
            await asyncio.sleep_ms(500)
            from . import system
            system.factory_reset(app)
        asyncio.create_task(later())
        return {"ok": True, "rebooting": True}

    def history_clear(req):
        log.warn("api: history clear requested")
        svc["history"].clear()
        return {"ok": True, "cleared": True}

    def ota_token(req):
        d, err = body_json(req)
        if err:
            return err
        t = d.get("token")
        if not isinstance(t, str) or len(t) < 4 or len(t) > 64:
            return http.err(400, "token must be a string of 4-64 characters")
        settings.set("ota.token", t)
        return {"ok": True}

    # ---- backlight ---------------------------------------------------------------------------------------
    bl = svc["backlight"]

    def bl_set(req):
        v = req.query.get("percent", "")
        if not v:
            return http.err(400, "percent required (e.g. /api/backlight/set?percent=50)")
        if not v.isdigit() or int(v) > 100:
            return http.err(400, "percent must be 0-100")
        if not bl.enabled:
            return http.err(409, "backlight control is disabled (needs the GPIO jumper and POST /api/backlight/config "
                                 '{"enabled":true})')
        bl.set_manual(int(v))
        return bl.status()

    def bl_config(req):
        d, err = body_json(req)
        if err:
            return err
        gpio = d.get("gpio")
        if gpio is not None and not (isinstance(gpio, int) and __import__("core.backlight", None, None, ["x"]).gpio_allowed(gpio)):
            return http.err(400, "that GPIO is already used by the RGB bus, I2C, USB or the console")
        try:
            bl.set_config(d.get("enabled") if isinstance(d.get("enabled"), bool) else None, gpio, d.get("preset"))
        except ValueError:
            return http.err(400, "preset must be off, gentle, aggressive or custom")
        return bl.status()

    def bl_curve(req):
        d, err = body_json(req)
        if err:
            return err
        pts = d.get("points")
        if not isinstance(pts, list):
            return http.err(400, 'expected {"points":[["HH:MM",percent], ...]}')
        if not pts:
            return http.err(400, "at least one point is required")
        if len(pts) > 8:
            return http.err(400, "at most 8 points")
        parsed = []
        for p in pts:
            if not (isinstance(p, list) and len(p) == 2 and isinstance(p[0], str) and isinstance(p[1], int)):
                return http.err(400, 'each point is ["HH:MM", percent]')
            m = _hhmm(p[0])
            if m < 0 or not 0 <= p[1] <= 100:
                return http.err(400, "time must be HH:MM and percent 0-100")
            parsed.append((m, p[1]))
        try:
            bl.set_curve(parsed)
        except ValueError:
            return http.err(400, "points must be in ascending time order, with no duplicates")
        return bl.status()

    # ---- UI ------------------------------------------------------------------------------------------------
    def view_info(changed=False):
        sh = svc["shell"]
        names = ("dashboard", "graph", "monthly", "system", "system", "system")
        tabs = (None, None, None, "info", "settings", "wifi")
        i = sh.active
        return {"ok": True, "changed": changed, "view": names[i] + ("/" + tabs[i] if tabs[i] else ""), "tile": names[i],
                "tab": tabs[i]}

    def swipe(req):
        sh = svc["shell"]
        d = req.query.get("dir", "")
        before = sh.active
        if d == "left":
            sh.go(sh.active + 1)
        elif d == "right":
            sh.go(sh.active - 1)
        elif d == "none":
            sh.idle_timer.reset()
        else:
            return http.err(400, "dir must be 'left', 'right' or 'none' (e.g. /api/swipe?dir=left)")
        return view_info(sh.active != before)

    def bench_render(req):
        """Diagnostics: force a full redraw of the current page and time it (ms), a few times."""
        import lvgl as lv
        out = []
        for _ in range(3):
            lv.screen_active().invalidate()
            t0 = time.ticks_ms()
            lv.refr_now(None)
            out.append(time.ticks_diff(time.ticks_ms(), t0))
        return {"page": svc["shell"].names[svc["shell"].active], "render_ms": out}

    server.route("POST", "/api/bench/render", bench_render, auth=True)

    shot_busy = []

    async def screenshot(req):
        import board
        from . import png
        if shot_busy:
            return http.err(503, "screenshot already in progress")
        shot_busy.append(1)
        try:
            gc.collect()
            data = await png.encode_rgb565(board.front(), board.W, board.H, (2 if board.CCW else 1) if board.portrait else 0)
            return 200, "image/png", data
        finally:
            shot_busy.clear()

    def logs(req):
        try:
            since = int(req.query.get("since", "0"))
        except ValueError:
            return http.err(400, "since must be an integer")
        nxt, entries = log.since(since)
        text = "".join(" %s (%d) %s\n" % ("IWE"[lv], ms, t) for _s, ms, lv, t in entries)
        return 200, "text/plain", text, {"X-Log-Next": nxt, "X-Log-Total": nxt, "X-Log-Lost": 0}

    # ---- static pages ------------------------------------------------------------------------------------
    def page(name, ctype="text/html", gz=False):
        def h(req):
            try:
                return (200, ctype, _read("www/" + name), {"Content-Encoding": "gzip"} if gz else {})
            except OSError:
                return http.err(404, "not found")
        return h

    def tzdata(req):
        return 200, "application/json", _read("www/tzdata.json"), {"Cache-Control": "public, max-age=31536000, immutable"}

    def index(req):
        q = req.query.get("format")
        if q == "json" or (q != "html" and "text/html" not in req.headers.get("accept", "")):
            return {"routes": [{"method": m, "path": p, "auth": a, "desc": _plain(dsc)} for m, p, a, dsc, _e in ROUTES]}
        rows = ""
        for m, p, a, dsc, ex in ROUTES:
            link = '<a href="%s">%s</a>' % (p, p) if (m == "GET" and not a and p not in ("/api/logs",)) else "<code>%s</code>" % p
            rows += ("<tr><td><span class=\"m %s\">%s</span></td><td>%s</td><td>%s</td><td>%s%s</td></tr>" % (
                m.lower(), m, link, '<span class="lock">token</span>' if a else '<span class="open">open</span>', dsc,
                "<pre>%s</pre>" % ex.replace("<", "&lt;") if ex else ""))
        html = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,"
                "initial-scale=1\"><title>Device API</title><style>body{margin:0;padding:24px;background:#101418;color:#e2e8f0;"
                "font-family:-apple-system,Segoe UI,Roboto,sans-serif}.wrap{max-width:900px;margin:0 auto}table{width:100%;"
                "border-collapse:collapse;font-size:.9rem}th{text-align:left;padding:8px;color:#94a3b8;border-bottom:1px solid "
                "#334155}td{padding:8px;border-bottom:1px solid #1e293b;vertical-align:top}.m{font-family:monospace;font-weight:700;"
                "padding:2px 7px;border-radius:4px}.get{background:#0e3a2f;color:#4ade80}.post{background:#3a2a0e;color:#fbbf24}"
                "a{color:#38bdf8;text-decoration:none}pre{margin:6px 0 0;padding:8px;background:#0f172a;border-radius:6px;"
                "overflow-x:auto;font-size:.78rem;color:#94a3b8}.lock{color:#f87171}.open{color:#475569}</style></head><body>"
                "<div class=\"wrap\"><h1>Device API</h1><p>This page is <code>GET /api</code> viewed in a browser; the same URL "
                "returns JSON to anything else. Gated routes need the <code>X-OTA-Token</code> header (5 bad attempts in 60 s "
                "locks an IP out for 5 minutes).</p><table><tr><th>Method</th><th>Path</th><th>Auth</th><th>Description</th></tr>"
                + rows + "</table></div></body></html>")
        return 200, "text/html", html

    R = server.route
    R("GET", "/api", index)
    R("GET", "/api/health", health)
    R("GET", "/api/system", system)
    R("GET", "/api/metrics", metrics)
    R("GET", "/api/settings", settings_get)
    R("POST", "/api/settings", settings_post, auth=True)

    def tuning_post(req):
        """Rendering tuning knobs (ui.partial, ui.rows, ui.single); null removes one. Takes effect after a restart."""
        d, err = body_json(req)
        if err:
            return err
        for k, v in d.items():
            if k not in ("ui.partial", "ui.rows", "ui.single", "ui.animate"):
                return http.err(400, "unknown key " + k)
            if v is None:
                settings.delete(k)
            else:
                settings.set(k, v)
        return {"ok": True}
    R("POST", "/api/tuning", tuning_post, auth=True)
    R("POST", "/api/orientation", orientation, auth=True)
    R("POST", "/api/reset", reset, auth=True)
    R("POST", "/api/reset-wifi-modbus", reset_wifi_modbus, auth=True)
    R("POST", "/api/factory-reset", factory_reset, auth=True)
    R("POST", "/api/history/clear", history_clear, auth=True)
    R("POST", "/api/ota-token", ota_token, auth=True)
    R("POST", "/api/coredump/erase", lambda req: {"ok": True, "erased": False}, auth=True)
    R("GET", "/api/backlight", lambda req: bl.status())
    R("POST", "/api/backlight/set", bl_set, auth=True)
    R("POST", "/api/backlight/config", bl_config, auth=True)
    R("POST", "/api/backlight/curve", bl_curve, auth=True)
    R("GET", "/api/view", lambda req: view_info())
    R("POST", "/api/swipe", swipe)
    R("GET", "/api/screenshot", screenshot)
    R("GET", "/api/logs", logs, auth=True)
    R("GET", "/tzdata.json", tzdata)
    R("GET", "/history-chart.html", page("history-chart.html"))
    R("GET", "/chart.min.js", page("chart.min.js.gz", "application/javascript", gz=True))
