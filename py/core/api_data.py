"""History and monthly-totals endpoints: JSON / CSV export, CSV import (streamed, token required)."""
import asyncio
import json

from . import http, tz
from . import timeutil as T

IMPORT_MAX_HISTORY = 2 * 1024 * 1024
IMPORT_MAX_MONTHLY = 8192


def _hist_json(h):
    yield '{"interval_s":300,"records":['
    first = True
    for t, soc, b, p, g, l in h.rows():
        yield '%s{"t":%d,"soc_pct":%.2f,"battery_kw":%.3f,"pv_kw":%.3f,"grid_kw":%.3f,"load_kw":%.3f}' % (
            "" if first else ",", t, soc, b, p, g, l)
        first = False
    yield "]}"


def _hist_csv(h):
    yield "timestamp,soc_pct,battery_kw,pv_kw,grid_kw,load_kw\n"
    for t, soc, b, p, g, l in h.rows():
        yield "%d,%.2f,%.3f,%.3f,%.3f,%.3f\n" % (t, soc, b, p, g, l)


def parse_time(s):
    """Unix seconds from either a number or 'YYYY-MM-DD HH:MM[:SS]' / 'YYYY/MM/DD ...' (local time)."""
    s = s.strip().strip('"')
    if not s:
        return 0
    if "-" in s or "/" in s:
        d, _, t = s.replace("T", " ").partition(" ")
        parts = d.replace("/", "-").split("-")
        hms = [int(x) for x in (t.split(":") if t else [])] + [0, 0, 0]
        if len(parts) >= 3:
            return tz.local_to_unix(T.to_unix(int(parts[0]), int(parts[1]), int(parts[2]), hms[0], hms[1], hms[2]))
    return int(float(s))


_COLS = {"timestamp": 0, "time": 0, "ts": 0, "soc": 1, "soc_pct": 1, "battery": 2, "battery_kw": 2, "pv": 3,
         "pv_kw": 3, "solar": 3, "solar_kw": 3, "grid": 4, "grid_kw": 4, "load": 5, "load_kw": 5}


def _header_order(line):
    return [_COLS.get(c.strip().strip('"').lower(), -1) for c in line.split(",")]


def _slow_row(line, order):
    """Anything the fast path could not parse: 'header' for a header row, a row tuple, or None to skip."""
    line = line.strip("\r ")
    if not line:
        return None
    cells = [c.strip().strip('"') for c in line.split(",")]
    if any(c.lower() in _COLS for c in cells):
        return "header"
    order = order or [0, 1, 2, 3, 4, 5]
    vals = [None] * 6
    for pos, c in enumerate(cells):
        dest = order[pos] if pos < len(order) else -1
        if dest >= 0:
            vals[dest] = c
    try:
        ts = parse_time(vals[0] or "")
        if not ts:
            return None
        return (ts,) + tuple(float(v) if v not in (None, "") else 0.0 for v in vals[1:])
    except ValueError:
        return None


class Lines:
    """Reads a request body line by line without holding it all (MicroPython has no async generators)."""

    def __init__(self, req, limit):
        self.req, self.limit = req, limit
        self.total = 0
        self.buf = b""
        self.eof = False

    async def next(self):
        """Next line (str), or None at the end of the body."""
        while True:
            i = self.buf.find(b"\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 1:]
                return line.decode().strip("\r ")
            if self.eof:
                if self.buf.strip():
                    line, self.buf = self.buf, b""
                    return line.decode().strip("\r ")
                return None
            chunk = await self.req.read(2048)
            if not chunk:
                self.eof = True
                continue
            self.total += len(chunk)
            if self.total > self.limit:
                raise ValueError("body too large")
            self.buf += chunk


def register(app, server):
    svc = app.services
    hist, monthly = svc["history"], svc["monthly"]

    def history_json(req):
        return 200, "application/json", _hist_json(hist)

    def history_csv(req):
        return 200, "text/csv", _hist_csv(hist), {"Content-Disposition": 'attachment; filename="history.csv"'}

    async def history_import(req):
        import time
        if req.length <= 0 or req.length > IMPORT_MAX_HISTORY:
            return http.err(413, "CSV too large or empty")
        t_start = time.ticks_ms()
        order = None                      # column order from a header row; None = the standard timestamp,soc,batt,pv,grid,load
        imp = hist.import_begin()
        left = ""
        got = 0
        while True:
            chunk = await req.read(2048)
            if not chunk:
                break
            got += len(chunk)
            if got > IMPORT_MAX_HISTORY:
                return http.err(413, "body too large")
            lines = (left + chunk.decode()).split("\n")
            left = lines.pop()
            for line in lines:
                try:
                    c = line.split(",")
                    imp.add(int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5]))
                    continue
                except (ValueError, IndexError):
                    pass
                row = _slow_row(line, order)              # header, blank, reordered columns, date-string timestamps
                if row == "header":
                    order = _header_order(line)
                elif row:
                    imp.add(*row)
            await asyncio.sleep_ms(0)
        if left.strip():
            row = _slow_row(left, order)
            if row and row != "header":
                imp.add(*row)
        if not imp.ts:
            return http.err(400, "no valid records found")
        t_parsed = time.ticks_ms()
        count = hist.import_commit(imp)
        app.log.info("history import: parsed %d rows in %d ms, stored in %d ms" % (
            count, time.ticks_diff(t_parsed, t_start), time.ticks_diff(time.ticks_ms(), t_parsed)))
        imp = None
        await monthly.backfill_from_history(True)
        return {"status": "ok", "imported": count}

    def monthly_json(req):
        def item(y, m, s, i, e, l):
            return {"year": y, "month": m, "solar_kwh": s, "grid_import_kwh": i, "grid_export_kwh": e, "load_kwh": l}

        def cur(d):
            return None if d is None else item(d["year"], d["month"], d["solar"], d["grid_import"], d["grid_export"], d["load"])
        return {"history": [item(*r) for r in monthly.months()], "current": cur(monthly.current()),
                "current_billing": cur(monthly.billing_current())}

    def monthly_csv(req):
        out = "year,month,solar_kwh,grid_import_kwh,grid_export_kwh,load_kwh\n"
        for y, m, s, i, e, l in monthly.months():
            out += "%d,%d,%.2f,%.2f,%.2f,%.2f\n" % (y, m, s, i, e, l)
        return 200, "text/csv", out, {"Content-Disposition": 'attachment; filename="monthly.csv"'}

    async def _small_csv(req, parse):
        if req.length <= 0 or req.length > IMPORT_MAX_MONTHLY:
            return None, http.err(413, "CSV too large or empty")
        rows = []
        first = True
        lines = Lines(req, IMPORT_MAX_MONTHLY)
        while True:
            line = await lines.next()
            if line is None:
                break
            if not line:
                continue
            if first:
                first = False
                if "year" in line or "month" in line or "date" in line:
                    continue
            try:
                r = parse(line.split(","))
                if r:
                    rows.append(r)
            except (ValueError, IndexError):
                continue
        if not rows:
            return None, http.err(400, "no valid records found")
        return rows, None

    def _month_row(c):
        y, m = int(c[0]), int(c[1])
        if y < 2000 or not 1 <= m <= 12:
            return None
        v = [float(x) for x in c[2:6]] + [0.0] * 4
        return [y, m, v[0], v[1], v[2], v[3]]

    def _day_row(c):
        y, m, d = (int(x) for x in c[0].strip().split("-"))
        if y < 2000 or not (1 <= m <= 12 and 1 <= d <= 31):
            return None
        v = [float(x) for x in c[1:5]] + [0.0] * 4
        return (y, m, d, v[0], v[1], v[2], v[3])

    async def monthly_import(req):
        rows, err = await _small_csv(req, _month_row)
        if err:
            return err
        return {"status": "ok", "imported": monthly.import_months(rows)}

    async def days_import(req):
        rows, err = await _small_csv(req, _day_row)
        if err:
            return err
        return {"status": "ok", "imported": monthly.import_days(rows)}

    server.route("GET", "/api/history", history_json)
    server.route("GET", "/api/history.csv", history_csv)
    server.route("POST", "/api/history/import", history_import, auth=True, stream=True)
    server.route("GET", "/api/monthly", monthly_json)
    server.route("GET", "/api/monthly.csv", monthly_csv)
    server.route("POST", "/api/monthly/import", monthly_import, auth=True, stream=True)
    server.route("POST", "/api/monthly/days/import", days_import, auth=True, stream=True)
