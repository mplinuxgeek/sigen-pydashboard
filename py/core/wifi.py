"""WiFi: station with automatic reconnect (1s..30s backoff), scan, and a provisioning access point.

Boot flow (like the ESP-IDF firmware): stored credentials -> try to join (15 s); nothing stored or the join failed
-> open AP "ESP32-Setup-XXXXXX" (192.168.4.1) + captive portal (core/portal.py) until credentials are saved.

    wifi = app.services["wifi"]
    wifi.connected / wifi.mode ("sta" | "ap" | "off") / wifi.ssid / wifi.ip / wifi.rssi() / wifi.mac
    await wifi.scan() -> [(ssid, rssi, secure)] strongest first, deduplicated
    wifi.connect(ssid, password)   save + connect live (no reboot)
    wifi.forget()                  clear credentials and reboot into AP mode
Events: net.up("wifi", ip), net.down("wifi").
"""
import asyncio
import binascii
import time

import network

CONNECT_TIMEOUT_S = 15
BACKOFF_MIN_S, BACKOFF_MAX_S = 1, 30
AP_IP = "192.168.4.1"


class WiFi:
    def __init__(self, app):
        self.app = app
        self.sta = network.WLAN(network.STA_IF)
        self.ap = network.WLAN(network.AP_IF)
        self.mode = "off"
        self.ap_ssid = ""
        self.ssid = ""             # SSID we are (or last tried to be) connected to
        self._was_up = False
        self._suppress = False     # a deliberate disconnect: do not auto-reconnect
        self._backoff = BACKOFF_MIN_S
        self._scanning = False
        self.last_status = None
        self.mac = binascii.hexlify(self.sta.config("mac"), ":").decode().upper()
        app.network.register("wifi", is_up=lambda: self.connected, ifconfig=self.sta.ifconfig, priority=20,
                             status=self._status)

    # ---- state ------------------------------------------------------------------------------
    @property
    def connected(self):
        try:
            return self.sta.active() and self.sta.isconnected()
        except OSError:
            return False

    @property
    def ip(self):
        return self.sta.ifconfig()[0] if self.connected else ""

    def rssi(self):
        try:
            return self.sta.status("rssi") if self.connected else None
        except (OSError, ValueError):
            return None

    def has_credentials(self):
        return bool(self.app.settings.get("wifi.ssid", ""))

    def _status(self):
        return {"SSID": self.ssid, "RSSI": "%s dBm" % self.rssi(), "MAC": self.mac}

    # ---- credentials ------------------------------------------------------------------------
    def save(self, ssid, password):
        self.app.settings.set("wifi.ssid", ssid)
        self.app.settings.set("wifi.pass", password or "")

    def connect(self, ssid, password):
        """Save and join live, without a reboot (the STA interface is already up, alone or next to the AP)."""
        self.save(ssid, password)
        self._suppress = False
        self._backoff = BACKOFF_MIN_S
        self._join(ssid, password)

    def _join(self, ssid, password):
        self.ssid = ssid
        self.sta.active(True)
        try:
            self.sta.disconnect()
        except OSError:
            pass
        self.sta.connect(ssid, password or "")

    def disconnect(self):
        """Deliberate disconnect: stays disconnected (no auto-reconnect)."""
        self._suppress = True
        try:
            self.sta.disconnect()
        except OSError:
            pass

    def forget(self):
        self.app.settings.delete("wifi.ssid")
        self.app.settings.delete("wifi.pass")
        self.app.log.info("wifi: credentials forgotten, restarting")
        import machine
        time.sleep_ms(300)
        machine.reset()

    # ---- scanning ---------------------------------------------------------------------------
    def _scan_blocking(self):
        self.sta.active(True)
        res = self.sta.scan()
        best = {}
        for r in res:
            try:
                name = r[0].decode()
            except UnicodeError:
                continue
            if not name:
                continue                              # hidden
            if name not in best or r[3] > best[name][1]:
                best[name] = (name, r[3], r[4] != 0)
        return sorted(best.values(), key=lambda t: -t[1])[:32]

    async def scan(self):
        """Blocking radio scan run in a thread so the UI keeps drawing. Returns [(ssid, rssi, secure)]."""
        import _thread
        if self._scanning:
            return []
        self._scanning = True
        box = []

        def work():
            try:
                box.append(self._scan_blocking())
            except Exception as e:
                self.app.log.warn("wifi: scan failed: %r" % (e,))
                box.append([])
        try:
            _thread.start_new_thread(work, ())
            while not box:
                await asyncio.sleep_ms(100)
        finally:
            self._scanning = False
        return box[0]

    # ---- access point -----------------------------------------------------------------------
    def start_ap(self):
        self.ap_ssid = "ESP32-Setup-%s" % binascii.hexlify(self.ap.config("mac")[3:]).decode().upper()
        self.ap.active(True)
        self.ap.config(essid=self.ap_ssid, authmode=network.AUTH_OPEN, channel=1)
        self.ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, AP_IP))
        self.mode = "ap"
        self.app.log.info("wifi: AP mode, SSID %s (open), %s" % (self.ap_ssid, AP_IP))
        self.app.emit("wifi.ap", self.ap_ssid)

    def stop_ap(self):
        self.ap.active(False)
        self.app.emit("wifi.ap_stopped")

    # ---- main loop --------------------------------------------------------------------------
    async def run(self):
        import network as n
        try:
            n.hostname("sigen-dashboard")
        except Exception:
            pass
        self.sta.active(True)
        ssid = self.app.settings.get("wifi.ssid", "")
        if ssid:
            self._join(ssid, self.app.settings.get("wifi.pass", ""))
            t0 = time.ticks_ms()
            while not self.connected and time.ticks_diff(time.ticks_ms(), t0) < CONNECT_TIMEOUT_S * 1000:
                await asyncio.sleep_ms(200)
        if self.connected:
            self.mode = "sta"
            self.app.log.info("wifi: connected to %s (%s)" % (self.ssid, self.ip))
        else:
            self.start_ap()                         # keep retrying the stored network while the AP is up
        await self._supervise()

    async def _supervise(self):
        retry_at = 0
        while True:
            up = self.connected
            if up and not self._was_up:
                self._was_up = True
                self._backoff = BACKOFF_MIN_S
                if self.mode == "off":
                    self.mode = "sta"
                self.app.log.info("wifi: up %s" % self.ip)
                self.app.emit("net.up", "wifi", self.ip)
            elif not up and self._was_up:
                self._was_up = False
                self.app.log.warn("wifi: link down")
                self.app.emit("net.down", "wifi")
                retry_at = time.ticks_add(time.ticks_ms(), self._backoff * 1000)
            elif not up and not self._suppress and self.has_credentials() and not self._scanning:
                now = time.ticks_ms()
                if retry_at == 0 or time.ticks_diff(now, retry_at) >= 0:
                    self._join(self.app.settings.get("wifi.ssid"), self.app.settings.get("wifi.pass", ""))
                    self._backoff = min(BACKOFF_MAX_S, self._backoff * 2)
                    retry_at = time.ticks_add(now, self._backoff * 1000)
            await asyncio.sleep_ms(500)
