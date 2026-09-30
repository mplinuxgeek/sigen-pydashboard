"""Sigen dashboard on MicroPython: boot, wire the services together, hand the loop to LVGL."""
import asyncio
import gc

import board
from core import api, errors, log, http, modbus, portal, wifi as wifi_mod
from core.app import App
from core.state import State
from core.dns import CaptiveDns

board.init()
errors.install()
log.restore()
log.info("boot: MicroPython on ESP32-S3, PSRAM heap free %d KB" % (gc.mem_free() // 1024))

app = App()
state = app.services["state"] = State()
wifi = app.services["wifi"] = wifi_mod.WiFi(app)
poller = app.services["poller"] = modbus.Poller(app)
server = app.services["http"] = http.Server(app)
portal_ = portal.Portal(app, server, wifi)
portal_.install()
api.register(app, server)

from ui.shell import Shell
from ui.dashboard import Dashboard
from ui.wifi_page import WifiPage
from ui import kit
import lvgl as lv


def _placeholder(name):
    def build(parent, shell):
        l = lv.label(parent)
        l.set_text(name)
        l.set_style_text_color(kit.rgb(kit.LABEL), 0)
        l.set_style_text_font(kit.font(24), 0)
        l.center()
    return build


def _dashboard(parent, shell):
    d = Dashboard(app, parent, on_wifi_icon=lambda: shell.go_name("WiFi"),
                  on_modbus_icon=lambda: shell.go_name("Settings"))
    app.services["dashboard"] = d
    state.data_cb.append(d.refresh)
    state.alive_cb.append(lambda a: d.active and d.paint_icons())
    app.on("net.up", lambda *a: d.active and d.paint_icons())
    app.on("net.down", lambda *a: d.active and d.paint_icons())
    return d


def _wifi_tab(parent, shell):
    return WifiPage(parent, app)


shell = app.services["shell"] = Shell(app, board, [
    ("Dashboard", _dashboard), ("Graph", _placeholder("Graph")), ("Monthly", _placeholder("Monthly")),
    ("Info", _placeholder("System info")), ("Settings", _placeholder("Settings")), ("WiFi", _wifi_tab)])


# ---- root page: setup portal while the AP is up, otherwise the landing page --------------------------------------
def _root(req):
    if wifi.mode == "ap":
        return portal_.setup_page()
    try:
        with open("www/index.html") as f:
            return 200, "text/html", f.read()
    except OSError:
        return 200, "text/plain", "Sigen dashboard %s" % api.VERSION


server.route("GET", "/", _root)
server.route("GET", "/index.html", _root)

dns = None
overlay_wifi = None


async def flow():
    """First-run flow: WiFi setup screen while the AP is up, then the Modbus IP prompt, then the dashboard."""
    global dns, overlay_wifi
    while wifi.mode == "off":
        await asyncio.sleep_ms(200)
    if wifi.mode == "ap":
        dns = CaptiveDns("192.168.4.1")
        dns.start()
        from ui import common as C
        ov = C.overlay()
        ov.set_style_bg_opa(lv.OPA.COVER, 0)
        ov.set_style_bg_color(kit.rgb(kit.SCREEN_BG), 0)
        done = []
        overlay_wifi = WifiPage(ov, app, on_connected=lambda: done.append(1))
        overlay_wifi.on_show()
        while not done:
            await asyncio.sleep_ms(500)
        log.info("setup: connected, shutting down the setup AP")
        dns.stop()
        wifi.stop_ap()
        wifi.mode = "sta"
        overlay_wifi.close()
        ov.delete()
        overlay_wifi = None
    while not wifi.connected:
        await asyncio.sleep_ms(500)
    if not poller.configured() and not app.settings.get("modbus.skipped"):
        from ui.modbus_setup import ModbusSetup
        fin = []
        ModbusSetup(app, lambda: fin.append(1))
        while not fin:
            await asyncio.sleep_ms(500)
        if not poller.configured():
            app.settings.set("modbus.skipped", True)


async def boot():
    app.spawn(wifi.run)
    app.spawn(server.start)
    app.spawn(poller.run)
    app.spawn(flow, restart=False)
    await app.start()


board.run(boot())
