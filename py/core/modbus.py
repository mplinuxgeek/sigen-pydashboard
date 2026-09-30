"""SigenStor Modbus TCP client + poll loop (port of modbus_client.c).

Plant-level registers answer at unit 247, device information (model/serial) at unit 1. Each request is paced
INTER_REQUEST_DELAY_MS apart (the inverter's own interaction-timeout rule), one poll cycle is committed atomically
into core.state, then POLL_CYCLE_GAP_MS of rest. 32/64-bit values are standard big-endian register order (verified
on the inverter: esp-modbus's "CDAB"/"GHEFCDAB" names in the ESP-IDF build describe this same wire order).
"""
import asyncio
import struct
import time

from . import state as st

PLANT_ADDR = 247
DEVICE_ADDR = 1
INTER_REQUEST_DELAY_MS = 1000
POLL_CYCLE_GAP_MS = 20000
RESPONSE_TIMEOUT_S = 1.5
CONNECT_TIMEOUT_S = 4

DEFAULT_IP = "192.168.1."
DEFAULT_PORT = 502


class ModbusError(Exception):
    pass


def u16(r):
    return r[0]


def i16(r):
    v = r[0]
    return v - 65536 if v & 0x8000 else v


def u32(r):
    return (r[0] << 16) | r[1]


def i32(r):
    v = (r[0] << 16) | r[1]
    return v - (1 << 32) if v & 0x80000000 else v


def u64(r):
    return (r[0] << 48) | (r[1] << 32) | (r[2] << 16) | r[3]


def ascii_regs(r):
    """Model/serial strings: pick the byte order that looks like text, trim padding."""
    raw = b"".join(struct.pack(">H", x) for x in r)
    swapped = b"".join(struct.pack("<H", x) for x in r)

    def score(b):
        s = 0
        for c in b:
            if c == 0:
                break
            s += 1 if 32 <= c < 127 else -4
        return s
    pick = swapped if score(swapped) > score(raw) else raw
    return pick.split(b"\x00")[0].decode("ascii", "ignore").strip()


# (state field, unit, register, count, decoder, gain)
REGS = (
    ("soc", PLANT_ADDR, 30014, 1, u16, 10.0),
    ("batt_power", PLANT_ADDR, 30037, 2, i32, 1000.0),
    ("batt_cap", PLANT_ADDR, 30083, 2, u32, 100.0),
    ("batt_temp", PLANT_ADDR, 30286, 1, i16, 10.0),
    ("pv_power", PLANT_ADDR, 30035, 2, i32, 1000.0),
    ("grid_power", PLANT_ADDR, 30005, 2, i32, 1000.0),
    ("load_power", PLANT_ADDR, 30284, 2, i32, 1000.0),
    ("pv_daily", PLANT_ADDR, 30272, 2, u32, 100.0),
    ("grid_status", PLANT_ADDR, 30009, 1, u16, 1.0),
    ("load_daily", PLANT_ADDR, 30092, 2, u32, 100.0),
    ("grid_import_total", PLANT_ADDR, 30216, 4, u64, 100.0),
    ("grid_export_total", PLANT_ADDR, 30220, 4, u64, 100.0),
)


class Client:
    def __init__(self, ip, port):
        self.ip, self.port = ip, port
        self.r = self.w = None
        self.tid = 0

    async def connect(self):
        self.close()
        self.r, self.w = await asyncio.wait_for(asyncio.open_connection(self.ip, self.port), CONNECT_TIMEOUT_S)

    def close(self):
        if self.w:
            try:
                self.w.close()
            except Exception:
                pass
        self.r = self.w = None

    async def read_input(self, unit, addr, count):
        """Function 0x04. Returns the list of 16-bit registers or raises ModbusError / OSError / TimeoutError."""
        if self.w is None:
            await self.connect()
        self.tid = (self.tid + 1) & 0xFFFF
        req = struct.pack(">HHHBBHH", self.tid, 0, 6, unit, 4, addr, count)
        try:
            self.w.write(req)
            await self.w.drain()
            head = await asyncio.wait_for(self.r.readexactly(7), RESPONSE_TIMEOUT_S)
            tid, _proto, length, _unit = struct.unpack(">HHHB", head)
            body = await asyncio.wait_for(self.r.readexactly(length - 1), RESPONSE_TIMEOUT_S)
        except Exception:
            self.close()                       # a desynchronised stream is unrecoverable: reconnect next time
            raise
        if body[0] & 0x80:
            raise ModbusError("exception %d" % (body[1] if len(body) > 1 else -1))
        if tid != self.tid or body[0] != 4 or body[1] != count * 2:
            self.close()
            raise ModbusError("bad response")
        return list(struct.unpack(">%dH" % count, body[2:2 + count * 2]))


class Poller:
    def __init__(self, app):
        self.app = app
        self.state = app.services["state"]
        self.client = None
        self.paused = False
        self.restart = False
        self.fail_streak = 0
        self.last_error = ""
        self.identity_ok = False

    # ---- config ---------------------------------------------------------------------------------
    def config(self):
        s = self.app.settings
        return s.get("modbus.ip", DEFAULT_IP), int(s.get("modbus.port", DEFAULT_PORT))

    def configured(self):
        ip, _ = self.config()
        parts = ip.split(".")
        return len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts) and ip != DEFAULT_IP

    def apply_config(self):
        """IP/port changed: drop the connection and start over (no reboot needed with a clean asyncio stack)."""
        self.restart = True
        if self.client:
            self.client.close()

    def pause(self, on=True):
        self.paused = on

    # ---- reads ----------------------------------------------------------------------------------
    async def _read(self, unit, addr, count):
        self.state.mark_activity()
        return await self.client.read_input(unit, addr, count)

    async def heartbeat(self):
        try:
            await self._read(PLANT_ADDR, 30000, 2)            # System_Time: value discarded
            self.fail_streak = 0
            self.last_error = ""
            self.state.set_alive(True)
            return True
        except Exception as e:
            self.fail_streak += 1
            self.last_error = repr(e)[:60]
            self.state.set_alive(False)
            if self.fail_streak in (1, 3) or self.fail_streak % 30 == 0:
                self.app.log.warn("modbus: heartbeat failed (%d): %s" % (self.fail_streak, self.last_error))
            return False

    async def identity(self):
        m = await self._read(DEVICE_ADDR, 30500, 15)
        await asyncio.sleep_ms(INTER_REQUEST_DELAY_MS)
        s = await self._read(DEVICE_ADDR, 30515, 10)
        model, serial = ascii_regs(m), ascii_regs(s)
        if model and serial:
            self.state.model, self.state.serial = model, serial
            self.identity_ok = True
            self.app.log.info("modbus: %s / %s" % (model, serial))

    async def cycle(self):
        batch = {}
        for name, unit, addr, count, dec, gain in REGS:
            if self.restart or self.paused:
                return None
            try:
                regs = await self._read(unit, addr, count)
                batch[name] = dec(regs) / gain
            except ModbusError as e:
                self.app.log.warn("modbus: %s @%d: %s" % (name, addr, e))
            except Exception as e:
                self.app.log.warn("modbus: %s @%d failed: %r" % (name, addr, e))
                if self.client.w is None:
                    break                                         # connection dropped: abandon the cycle
            await asyncio.sleep_ms(INTER_REQUEST_DELAY_MS)
        return batch

    def grid_daily(self, batch):
        """No daily register for grid: lifetime counters minus a midnight baseline (persisted)."""
        imp, exp = batch.get("grid_import_total"), batch.get("grid_export_total")
        ntp = self.app.services.get("ntp")
        if imp is None or exp is None or not (ntp and ntp.synced):
            return
        from . import tz
        t = tz.now()
        if t is None:
            return
        today = t[0] * 10000 + t[1] * 100 + t[2]
        s = self.app.settings
        base = s.get("grid.base")
        if not base or base[0] != today:
            base = [today, imp, exp]
            s.set("grid.base", base)
            self.app.log.info("modbus: grid baseline reset for %d: in=%.2f out=%.2f kWh" % (today, imp, exp))
        batch["grid_daily_import"] = max(0.0, imp - base[1])
        batch["grid_daily_export"] = max(0.0, exp - base[2])

    # ---- main loop ------------------------------------------------------------------------------
    async def run(self):
        while True:
            if not self.configured():
                await asyncio.sleep(2)
                continue
            net = self.app.network
            if not net.up():
                self.state.set_alive(False)
                await asyncio.sleep(1)
                continue
            self.restart = False
            ip, port = self.config()
            self.client = Client(ip, port)
            self.app.log.info("modbus: target %s:%d" % (ip, port))
            while not self.restart:
                if self.paused:
                    await asyncio.sleep(1)
                    continue
                ok = await self.heartbeat()
                await asyncio.sleep_ms(INTER_REQUEST_DELAY_MS)
                if ok and not self.restart:
                    try:
                        if not self.identity_ok:
                            await self.identity()
                            await asyncio.sleep_ms(INTER_REQUEST_DELAY_MS)
                        batch = await self.cycle()
                        if batch is not None:
                            self.grid_daily(batch)
                            self.state.commit(batch)
                    except Exception as e:
                        self.app.log.warn("modbus: cycle failed: %r" % (e,))
                # rest between cycles, but stay responsive to config changes
                for _ in range(POLL_CYCLE_GAP_MS // 500):
                    if self.restart or not ok:
                        break
                    await asyncio.sleep_ms(500)
                if not ok:
                    await asyncio.sleep(5)
            self.client.close()
