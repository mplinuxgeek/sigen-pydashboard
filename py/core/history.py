"""5-minute history ring: SOC, battery, PV, grid and load power, 31 days (8928 samples).

Stored in the dedicated raw "history" partition as a circular log of fixed 32-byte records, one small direct write
per sample (each 4 KB sector is erased once per 31-day cycle), mirrored in RAM (PSRAM) for the graphs.
    record: seq u32 | unix ts u32 | soc int16 (0.1 %) | pad 2 | batt, pv, grid, load int32 (W) | pad 4
Power is signed the same way as the live readings: battery >0 charging, grid >0 importing.
"""
import asyncio
import struct
from array import array

import esp32
import micropython

from . import timeutil as T

INTERVAL_S = 300
CAPACITY = 31 * 24 * 3600 // INTERVAL_S          # 8928
SECTOR = 4096
REC = 32
PER_SECTOR = SECTOR // REC
MAGIC = 0x48495354
SEQ_ERASED = 0xFFFFFFFF
_FMT = "<IIhxx4i4x"


@micropython.viper
def _split(src: ptr32, seq: ptr32, ts: ptr32, soc: ptr16, batt: ptr32, pv: ptr32, grid: ptr32, load: ptr32,
           base: int, nrec: int):
    """De-interleave one sector of 32-byte records (8 words each) into the per-field arrays."""
    for i in range(nrec):
        w = i * 8
        j = base + i
        seq[j] = src[w]
        ts[j] = src[w + 1]
        soc[j] = int(src[w + 2]) & 0xFFFF
        batt[j] = src[w + 3]
        pv[j] = src[w + 4]
        grid[j] = src[w + 5]
        load[j] = src[w + 6]


@micropython.viper
def _scan(seq: ptr32, n: int, out: ptr32):
    """out[0] = number of written slots, out[1] = slot holding the highest sequence number, out[2] = that number."""
    cnt = 0
    head = 0
    top = 0
    for i in range(n):
        q = int(seq[i])
        if q != -1:                       # 0xFFFFFFFF = erased slot
            cnt += 1
            if q >= top and q >= 0:
                top = q
                head = i
    out[0] = cnt
    out[1] = head
    out[2] = top


class History:
    def __init__(self, app):
        self.app = app
        self.part = None
        self.n = 0
        self.ts = array("I")
        self.soc = array("h")
        self.batt = array("i")
        self.pv = array("i")
        self.grid = array("i")
        self.load = array("i")
        self.next_seq = 1
        self.write_slot = 0
        self.last = [0, 0, 0, 0, 0]            # carried-forward last known: soc(0.1%), batt, pv, grid, load (W)
        self.rev = 0                           # bumped on every change (UI caches)
        self.listeners = []                    # called after every appended sample
        self._find()
        if self.part:
            self._load()

    # ---- partition ------------------------------------------------------------------------------------
    def _find(self):
        found = esp32.Partition.find(esp32.Partition.TYPE_DATA, subtype=0x40, label="history")
        if not found:
            self.app.log.error("history: no 'history' partition (flash the new partition table)")
            return
        self.part = found[0]

    def _slot_off(self, slot):
        return SECTOR + slot * REC

    def _erase_sector(self, sector_idx):
        self.part.ioctl(6, sector_idx)         # block erase

    def _format(self):
        self._erase_sector(0)
        self.part.writeblocks(0, struct.pack("<I", MAGIC), 0)
        for s in range(1, 1 + (CAPACITY + PER_SECTOR - 1) // PER_SECTOR):
            self._erase_sector(s)
        self.next_seq, self.write_slot = 1, 0

    def _load(self):
        hdr = bytearray(4)
        self.part.readblocks(0, hdr, 0)
        if struct.unpack("<I", hdr)[0] != MAGIC:
            self.app.log.info("history: formatting the history partition")
            self._format()
            return
        buf = bytearray(SECTOR)
        zero = bytes(4 * CAPACITY)
        seq, ts, soc = array("I", zero), array("I", zero), array("h", bytes(2 * CAPACITY))
        batt, pv, grid, load = array("i", zero), array("i", zero), array("i", zero), array("i", zero)
        for s in range(1, 1 + (CAPACITY + PER_SECTOR - 1) // PER_SECTOR):
            self.part.readblocks(s, buf, 0)
            base = (s - 1) * PER_SECTOR
            _split(buf, seq, ts, soc, batt, pv, grid, load, base, min(PER_SECTOR, CAPACITY - base))
        res = array("i", [0, 0, 0])
        _scan(seq, CAPACITY, res)
        count, head, top = res[0], res[1], res[2] & 0xFFFFFFFF
        if count:
            # Slots are written in order and wrap. Rotate so the slot after the newest comes first: the erased gap (if
            # any) then sits at the front and the `count` valid records are the last `count` entries, oldest first.
            start = (head + 1) % CAPACITY
            out = []
            for a in (ts, soc, batt, pv, grid, load):
                b = a[start:CAPACITY]
                b.extend(a[:start])
                out.append(b[CAPACITY - count:] if count < CAPACITY else b)
            self.ts, self.soc, self.batt, self.pv, self.grid, self.load = out
            self.n = count
            self.next_seq = top + 1
            self.write_slot = (head + 1) % CAPACITY
            self.last = [self.soc[-1], self.batt[-1], self.pv[-1], self.grid[-1], self.load[-1]]
        self.app.log.info("history: loaded %d samples" % self.n)

    def _push(self, ts, soc, b, p, g, l):
        vals = (ts, soc, b, p, g, l)
        arrs = (self.ts, self.soc, self.batt, self.pv, self.grid, self.load)
        if self.n >= CAPACITY:                         # full: drop the oldest by shifting down one slot
            for a, v in zip(arrs, vals):
                a[:-1] = a[1:]
                a[-1] = v
            return
        for a, v in zip(arrs, vals):
            a.append(v)
        self.n += 1

    def _write_raw(self, ts, soc, b, p, g, l):
        if not self.part:
            return
        slot = self.write_slot
        if slot % PER_SECTOR == 0:
            self._erase_sector(1 + slot // PER_SECTOR)
        self.part.writeblocks(1 + slot // PER_SECTOR, struct.pack(_FMT, self.next_seq, ts, soc, b, p, g, l),
                              (slot % PER_SECTOR) * REC)
        self.next_seq += 1
        self.write_slot = (slot + 1) % CAPACITY

    def _rewrite_all(self):
        """Rewrite the whole log from the RAM records, one whole-sector write at a time (import / timestamp backfill)."""
        if not self.part:
            return
        self._erase_sector(0)
        self.part.writeblocks(0, struct.pack("<I", MAGIC), 0)
        n = self.n
        buf = bytearray(SECTOR)
        used = (n + PER_SECTOR - 1) // PER_SECTOR
        pack = struct.pack_into
        for sec in range(used):
            for i in range(len(buf)):
                buf[i] = 0xFF
            base = sec * PER_SECTOR
            for j in range(min(PER_SECTOR, n - base)):
                k = base + j
                pack(_FMT, buf, j * REC, k + 1, self.ts[k], self.soc[k], self.batt[k], self.pv[k], self.grid[k], self.load[k])
            self.part.writeblocks(1 + sec, buf)          # no offset: erases the sector, then writes it
        for sec in range(used, 1 + (CAPACITY + PER_SECTOR - 1) // PER_SECTOR - 1):
            self._erase_sector(1 + sec)
        self.next_seq = n + 1
        self.write_slot = n % CAPACITY

    # ---- sampling -------------------------------------------------------------------------------------
    def take_sample(self):
        s = self.app.services["state"]
        if s.cycles == 0:
            return False                              # nothing read yet: do not record zeros
        g = s.get
        last = self.last
        if s.valid("soc"):
            last[0] = int(round(g("soc") * 10))
        for i, k in ((1, "batt_power"), (2, "pv_power"), (3, "grid_power"), (4, "load_power")):
            if s.valid(k):
                last[i] = int(round(g(k) * 1000))
        ntp = self.app.services.get("ntp")
        ts = T.unix_now() if (ntp and ntp.synced) else 0
        self._push(ts, *last)
        self._write_raw(ts, *last)
        self.rev += 1
        self.app.log.info("history: sampled soc=%.1f%% batt=%.2f pv=%.2f grid=%.2f load=%.2f kW (%d/%d)" % (
            last[0] / 10, last[1] / 1000, last[2] / 1000, last[3] / 1000, last[4] / 1000, self.n, CAPACITY))
        for cb in self.listeners:
            try:
                cb()
            except Exception as e:
                self.app.log.warn("history: listener failed: %r" % (e,))
        return True

    async def run(self):
        state = self.app.services["state"]
        for _ in range(300):                       # first sample as soon as the first poll cycle has landed
            if state.cycles:
                break
            await asyncio.sleep(1)
        self.take_sample()
        while True:
            await asyncio.sleep(INTERVAL_S)
            self.take_sample()

    def on_time_synced(self):
        """Samples taken before the first NTP sync have ts=0: stamp them backwards from now at the sample cadence."""
        if self.n and self.ts[self.n - 1] == 0:
            now = T.unix_now()
            for i in range(self.n):
                self.ts[i] = now - (self.n - 1 - i) * INTERVAL_S
            self._rewrite_all()
            self.rev += 1
            self.app.log.info("history: backfilled timestamps for %d samples" % self.n)

    # ---- bulk ops ---------------------------------------------------------------------------------------
    def clear(self):
        self.ts, self.soc = array("I"), array("h")
        self.batt, self.pv, self.grid, self.load = array("i"), array("i"), array("i"), array("i")
        self.n = 0
        self.last = [0, 0, 0, 0, 0]
        if self.part:
            self._format()
        self.rev += 1
        self.app.log.info("history: cleared")

    def import_begin(self):
        """Start a bulk import: rows go straight into compact arrays (a list of float tuples would thrash the GC)."""
        return Import()

    def import_commit(self, imp):
        """Sort (if needed), keep the newest CAPACITY records, write everything back. Returns the record count."""
        n = len(imp.ts)
        order = None
        ts = imp.ts
        if any(ts[i] > ts[i + 1] for i in range(n - 1)):
            order = sorted(range(n), key=ts.__getitem__)
        lo = max(0, n - CAPACITY)
        arrays = (imp.ts, imp.soc, imp.batt, imp.pv, imp.grid, imp.load)
        out = []
        for a in arrays:
            if order is not None:
                b = array(a.typecode, (a[i] for i in order[lo:]))
            else:
                b = a[lo:] if lo else a
            out.append(b)
        self.ts, self.soc, self.batt, self.pv, self.grid, self.load = out
        self.n = len(self.ts)
        if self.n:
            self.last = [self.soc[-1], self.batt[-1], self.pv[-1], self.grid[-1], self.load[-1]]
        self._rewrite_all()
        self.rev += 1
        self.app.log.info("history: imported %d records" % self.n)
        return self.n

    def rows(self, t0=0, t1=0xFFFFFFFF):
        """Yield (ts, soc%, batt_kw, pv_kw, grid_kw, load_kw) for ts0 <= ts < t1, oldest first."""
        for i in range(self.n):
            t = self.ts[i]
            if t0 <= t < t1:
                yield t, self.soc[i] / 10, self.batt[i] / 1000, self.pv[i] / 1000, self.grid[i] / 1000, self.load[i] / 1000

    # ---- derived: today / billing cycle source split + peaks -------------------------------------------
    async def day_stats(self, mtd_start, today_start, now):
        """Solar/battery contribution to load (kWh) for today and since `mtd_start`, plus today's peaks.
        Per sample: solar covers min(load, pv); battery covers min(rest of load, discharge). Completed days are
        cached; runs as a coroutine (yields regularly) so the UI keeps drawing."""
        h = INTERVAL_S / 3600.0
        today = [0.0, 0.0, 0.0]
        mtd = [0.0, 0.0, 0.0]
        peaks = {"pv": 0.0, "load": 0.0, "batt_chg": 0.0, "batt_dis": 0.0, "grid_imp": 0.0, "grid_exp": 0.0}
        for i in range(self.n):
            if i & 511 == 511:
                await asyncio.sleep_ms(0)
            t = self.ts[i]
            if t < mtd_start or t >= now or t == 0:
                continue
            load = self.load[i] / 1000
            pv = self.pv[i] / 1000
            batt = self.batt[i] / 1000
            grid = self.grid[i] / 1000
            load = load if load > 0 else 0.0
            pv = pv if pv > 0 else 0.0
            dis = -batt if batt < 0 else 0.0
            solar = pv if pv < load else load
            rem = load - solar
            bat = dis if dis < rem else rem
            mtd[0] += solar * h
            mtd[1] += bat * h
            mtd[2] += load * h
            if t >= today_start:
                today[0] += solar * h
                today[1] += bat * h
                today[2] += load * h
                if pv > peaks["pv"]:
                    peaks["pv"] = pv
                if load > peaks["load"]:
                    peaks["load"] = load
                if batt > peaks["batt_chg"]:
                    peaks["batt_chg"] = batt
                if dis > peaks["batt_dis"]:
                    peaks["batt_dis"] = dis
                if grid > peaks["grid_imp"]:
                    peaks["grid_imp"] = grid
                if -grid > peaks["grid_exp"]:
                    peaks["grid_exp"] = -grid
        return {"today": tuple(today), "mtd": tuple(mtd), "peaks": peaks}


class Import:
    def __init__(self):
        self.ts, self.soc = array("I"), array("h")
        self.batt, self.pv, self.grid, self.load = array("i"), array("i"), array("i"), array("i")

    def add(self, ts, soc, batt, pv, grid, load):
        """Values as in the CSV: soc in %, powers in kW."""
        self.ts.append(int(ts))
        self.soc.append(int(soc * 10 + (0.5 if soc >= 0 else -0.5)))
        self.batt.append(int(batt * 1000 + (0.5 if batt >= 0 else -0.5)))
        self.pv.append(int(pv * 1000 + (0.5 if pv >= 0 else -0.5)))
        self.grid.append(int(grid * 1000 + (0.5 if grid >= 0 else -0.5)))
        self.load.append(int(load * 1000 + (0.5 if load >= 0 else -0.5)))
