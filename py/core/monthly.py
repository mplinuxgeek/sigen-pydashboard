"""Month totals + billing cycle (port of monthly_totals.c).

Completed months (36 kept) roll up from per-day totals taken from the inverter's own daily registers; a 31-day ring of
finalised days lets the billing-cycle total be re-derived whenever the cycle boundary setting changes. State lives in NVS
blobs ("m_prog", "m_months", "m_days"). Days are keyed by day_num = days since 1970-01-01 of the *local calendar date*
(offset-free, so it survives time zones that are not whole multiples of 24 h).

    billing_current()  -> {"year","month","solar","load","grid_import","grid_export"} incl. today's live totals, or None
    current()          -> calendar month so far (completed days only) or None
    months()           -> completed months oldest first: [[year, month, solar, grid_import, grid_export, load]]
"""
from . import store, tz
from . import timeutil as T

RETENTION_MONTHS = 36
RETENTION_DAYS = 31
MODE_CALENDAR, MODE_FIXED = 0, 1


class Monthly:
    def __init__(self, app):
        self.app = app
        self.progress = store.get("m_prog") or {"last_day": 0, "last": [0, 0, 0, 0], "cur": [0, 0], "acc": [0, 0, 0, 0]}
        self.month_list = store.get("m_months") or []
        self.days = store.get("m_days") or []         # [[day_num, solar, imp, exp, load]]
        self.cache = None                             # (cycle_start_day_num, [solar, imp, exp, load])
        self.rev = 0

    # ---- settings -------------------------------------------------------------------------------------
    def cfg(self):
        s = self.app.settings
        return (int(s.get("billing.mode", MODE_CALENDAR)), int(s.get("billing.day", 1)),
                int(s.get("billing.anchor", 20260101)), int(s.get("billing.cycle_len", 28)))

    def apply_settings(self):
        """Billing setting changed: re-sum the day ring against the new boundary (no-op until the clock is set)."""
        if T.clock_valid():
            self._recompute_cache()

    # ---- helpers --------------------------------------------------------------------------------------
    def _today(self):
        t = tz.local()
        return None if t is None else (t[0], t[1], t[2])

    def _cycle_start(self, y, m, d):
        mode, bday, anchor, clen = self.cfg()
        if mode == MODE_FIXED and clen >= 1:
            ay, am, ad = anchor // 10000, anchor // 100 % 100, anchor % 100
            a = T.days_from_civil(ay, am, ad)
            today = T.days_from_civil(y, m, d)
            if today <= a:
                return a
            return a + (today - a) // clen * clen
        if d < bday:
            m -= 1
            if m < 1:
                m, y = 12, y - 1
        return T.days_from_civil(y, m, min(bday, T.days_in_month(y, m)))

    def _recompute_cache(self):
        t = self._today()
        if t is None:
            return
        start = self._cycle_start(*t)
        tot = [0.0, 0.0, 0.0, 0.0]
        for day in self.days:
            if day[0] >= start:
                for i in range(4):
                    tot[i] += day[1 + i]
        self.cache = (start, tot)

    def _recompute_calendar(self):
        cy, cm = self.progress["cur"]
        if not cm:
            return
        acc = [0.0, 0.0, 0.0, 0.0]
        for day in self.days:
            y, m, _d = T.civil_from_days(day[0])
            if y == cy and m == cm:
                for i in range(4):
                    acc[i] += day[1 + i]
        self.progress["acc"] = acc

    def _save_days(self):
        store.put("m_days", self.days)

    def _save_progress(self):
        store.put("m_prog", self.progress)

    def _push_day(self, day_num, solar, imp, exp, load):
        self.days.append([day_num, solar, imp, exp, load])
        del self.days[:-RETENTION_DAYS]
        self._save_days()

    def _finalize_month(self):
        cy, cm = self.progress["cur"]
        if not cm:
            return
        a = self.progress["acc"]
        self.month_list.append([cy, cm, a[0], a[1], a[2], a[3]])
        del self.month_list[:-RETENTION_MONTHS]
        store.put("m_months", self.month_list)
        self.app.log.info("monthly: finalized %04d-%02d solar=%.1f import=%.1f export=%.1f load=%.1f kWh" % (
            cy, cm, a[0], a[1], a[2], a[3]))

    # ---- sampling (called after each history sample) ------------------------------------------------------
    def sample(self):
        s = self.app.services["state"]
        ntp = self.app.services.get("ntp")
        if not (ntp and ntp.synced):
            return
        for k in ("pv_daily", "grid_daily_import", "grid_daily_export", "load_daily"):
            if not s.valid(k):
                return
        t = self._today()
        if t is None:
            return
        y, m, d = t
        today = T.days_from_civil(y, m, d)
        p = self.progress
        if not p["cur"][1]:
            p["cur"] = [y, m]
            self._recompute_cache()
        elif p["last_day"] and today != p["last_day"]:
            gap = today - p["last_day"]
            if gap == 1:
                for i in range(4):
                    p["acc"][i] += p["last"][i]
                self._push_day(p["last_day"], *p["last"])
            else:
                self.app.log.warn("monthly: %d-day gap since last sample, resyncing without backfilling" % gap)
            if (y, m) != tuple(p["cur"]):
                self._finalize_month()
                p["cur"] = [y, m]
                p["acc"] = [0.0, 0.0, 0.0, 0.0]
            self._recompute_cache()
        p["last_day"] = today
        p["last"] = [s.get("pv_daily"), s.get("grid_daily_import"), s.get("grid_daily_export"), s.get("load_daily")]
        self._save_progress()
        self.rev += 1

    # ---- getters ----------------------------------------------------------------------------------------
    def months(self):
        return self.month_list

    def current(self):
        p = self.progress
        if not p["cur"][1]:
            return None
        a = p["acc"]
        return {"year": p["cur"][0], "month": p["cur"][1], "solar": a[0], "grid_import": a[1], "grid_export": a[2],
                "load": a[3]}

    def billing_current(self):
        if self.cache is None:
            if T.clock_valid():
                self._recompute_cache()
            if self.cache is None:
                return None
        start, tot = self.cache
        y, m, _d = T.civil_from_days(start)
        p = self.progress
        t = self._today()
        today_valid = t is not None and p["last_day"] == T.days_from_civil(*t)
        last = p["last"] if today_valid else (0, 0, 0, 0)
        return {"year": y, "month": m, "solar": tot[0] + last[0], "grid_import": tot[1] + last[1],
                "grid_export": tot[2] + last[2], "load": tot[3] + last[3]}

    def billing_start_epoch(self):
        """Unix time of local midnight at the start of the current billing cycle, or None."""
        if self.cache is None:
            self.billing_current()
        if self.cache is None:
            return None
        y, m, d = T.civil_from_days(self.cache[0])
        return tz.day_start(T.to_unix(y, m, d, 12))

    # ---- backfill / import ------------------------------------------------------------------------------
    def backfill_from_history(self, force=False):
        """Estimate missing completed days from the 5-minute power log (power x time). force=True overwrites."""
        hist = self.app.services.get("history")
        ntp = self.app.services.get("ntp")
        if not hist or not hist.n or not (ntp and ntp.synced):
            return 0
        t = self._today()
        if t is None:
            return 0
        today = T.days_from_civil(*t)
        dth = 300 / 3600.0
        have = {d[0] for d in self.days}
        buckets = {}
        for i in range(hist.n):
            ts = hist.ts[i]
            if not ts:
                continue
            y, m, d = T.civil(ts + tz.offset(ts))[:3]
            dn = T.days_from_civil(y, m, d)
            if dn == today or (dn in have and not force):
                continue
            b = buckets.setdefault(dn, [0.0, 0.0, 0.0, 0.0])
            pv, load, grid = hist.pv[i] / 1000, hist.load[i] / 1000, hist.grid[i] / 1000
            b[0] += (pv if pv > 0 else 0.0) * dth
            b[1] += (grid if grid > 0 else 0.0) * dth
            b[2] += (-grid if grid < 0 else 0.0) * dth
            b[3] += (load if load > 0 else 0.0) * dth
        if not buckets:
            return 0
        merged = {d[0]: d for d in self.days if not (force and d[0] in buckets)}
        for dn, b in buckets.items():
            merged[dn] = [dn] + b
        self.days = [merged[k] for k in sorted(merged)][-RETENTION_DAYS:]
        self._save_days()
        self._recompute_cache()
        self._recompute_calendar()
        self._save_progress()
        self.app.log.info("monthly: backfilled %d day(s) from history" % len(buckets))
        self.rev += 1
        return len(buckets)

    def import_months(self, rows):
        """rows: [[year, month, solar, grid_import, grid_export, load]]; replaces the completed months."""
        rows = sorted(rows, key=lambda r: (r[0], r[1]))[-RETENTION_MONTHS:]
        self.month_list = [list(r) for r in rows]
        store.put("m_months", self.month_list)
        self.rev += 1
        return len(rows)

    def import_days(self, rows):
        """rows: [(year, month, day, solar, imp, exp, load)]; exact values overwrite whatever the day had (past days only)."""
        t = self._today()
        today = T.days_from_civil(*t) if t else 1 << 30
        merged = {d[0]: d for d in self.days}
        n = 0
        for y, m, d, solar, imp, exp, load in rows:
            dn = T.days_from_civil(y, m, d)
            if dn >= today:
                continue
            merged[dn] = [dn, solar, imp, exp, load]
            n += 1
        self.days = [merged[k] for k in sorted(merged)][-RETENTION_DAYS:]
        self._save_days()
        self._recompute_cache()
        self._recompute_calendar()
        self._save_progress()
        self.rev += 1
        return n

    def clear(self):
        self.progress = {"last_day": 0, "last": [0, 0, 0, 0], "cur": [0, 0], "acc": [0, 0, 0, 0]}
        self.month_list, self.days, self.cache = [], [], None
        for k in ("m_prog", "m_months", "m_days"):
            store.erase(k)
