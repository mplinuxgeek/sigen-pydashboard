"""SNTP time sync: sets the RTC (UTC) when a network comes up, then every 6 hours.

    ntp = app.services["ntp"]; ntp.synced; ntp.status_text(); ntp.request()
Callbacks in ntp.callbacks run after every successful sync (history backfill, status icons)."""
import _thread
import asyncio
import time

import ntptime

HOSTS = ("pool.ntp.org", "time.google.com", "time.cloudflare.com")
RESYNC_S = 6 * 3600
RETRY_S = 30


class Ntp:
    def __init__(self, app):
        self.app = app
        self.synced = False
        self.last_ok = None
        self.last_err = None
        self.busy = False
        self.want = False
        self.online = False
        self.callbacks = []
        self._done = False
        self.server = None
        self.sync_count = 0

    def status_text(self):
        if self.synced:
            age = time.ticks_diff(time.ticks_ms(), self.last_ok) // 60000
            return "NTP synced %s" % ("just now" if age < 1 else "%d min ago" % age if age < 120 else "%d h ago" % (age // 60))
        if self.busy:
            return "syncing..."
        return "not synced" + (" (%s)" % self.last_err if self.last_err else "")

    def request(self):
        self.want = True

    def _sync(self):
        """Runs in a thread (network calls block)."""
        self.busy = True
        ok = False
        for host in HOSTS:
            try:
                ntptime.host = host
                ntptime.timeout = 4
                ntptime.settime()
                self.last_ok, self.last_err, self.server = time.ticks_ms(), None, host
                self.app.log.info("ntp: synced from %s" % host)
                ok = True
                break
            except Exception as e:
                self.last_err = repr(e)[:30]
        if not ok:
            self.app.log.warn("ntp: sync failed (%s)" % self.last_err)
        self._done = ok
        self.busy = False

    async def run(self):
        next_try = 0
        while True:
            now = time.ticks_ms()
            if self._done:
                self._done = False
                self.synced = True
                self.sync_count += 1
                for cb in self.callbacks:
                    try:
                        cb()
                    except Exception as e:
                        self.app.log.warn("ntp: callback failed: %r" % (e,))
            due = self.want or (self.online and (not self.synced or time.ticks_diff(now, self.last_ok) > RESYNC_S * 1000))
            if self.online and due and not self.busy and time.ticks_diff(now, next_try) >= 0:
                self.want = False
                next_try = time.ticks_add(now, RETRY_S * 1000)
                try:
                    _thread.start_new_thread(self._sync, ())
                except OSError:
                    pass
            await asyncio.sleep_ms(1000)
