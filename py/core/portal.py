"""Captive portal: while the AP is up, GET / serves the WiFi setup page, /scan lists networks, /save stores
the credentials and reboots into station mode, and every other path redirects to /."""
import asyncio
import json

from . import http

AP_URL = "http://192.168.4.1/"


def _page(name):
    with open("www/" + name) as f:
        return f.read()


class Portal:
    def __init__(self, app, server, wifi):
        self.app, self.server, self.wifi = app, server, wifi
        self.active = False

    def install(self):
        s = self.server
        s.route("GET", "/scan", self.scan)
        s.route("POST", "/save", self.save)
        s.route("GET", "/generate_204", self.redirect)         # Android
        s.route("GET", "/hotspot-detect.html", self.redirect)  # Apple
        s.route("GET", "/connecttest.txt", self.redirect)      # Windows
        s.fallback = self.fallback

    def setup_page(self, req=None):
        return 200, "text/html", _page("setup.html")

    def redirect(self, req):
        return http.redirect(AP_URL)

    def fallback(self, req):
        return self.redirect(req) if self.wifi.mode == "ap" else http.err(404, "not found")

    async def scan(self, req):
        nets = await self.wifi.scan()
        return [{"ssid": s, "rssi": r, "secure": sec} for s, r, sec in nets]

    async def save(self, req):
        f = req.form()
        ssid = f.get("ssid", "").strip()
        if not ssid:
            return http.err(400, "ssid required")
        self.wifi.save(ssid, f.get("password", ""))
        self.app.log.info("portal: saved credentials for %s, restarting" % ssid)

        async def later():
            await asyncio.sleep_ms(1500)
            import machine
            machine.reset()
        asyncio.create_task(later())
        return 200, "text/html", _page("saved.html")
