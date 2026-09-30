"""Latest plant readings (like modbus_client.c's mutex-protected cache), committed one poll cycle at a time.

A field that failed to read this cycle keeps its last good value (a transient blip must not blank the display);
valid() says whether a field has *ever* been read. Units: kW / kWh / % / degC."""
import time

FIELDS = ("soc", "batt_power", "batt_cap", "batt_temp", "pv_power", "grid_power", "load_power", "pv_daily",
          "load_daily", "grid_import_total", "grid_export_total", "grid_daily_import", "grid_daily_export",
          "grid_status")

GRID_ON, GRID_OFF_AUTO, GRID_OFF_MANUAL = 0, 1, 2
ACTIVITY_WINDOW_MS = 1500


class State:
    def __init__(self):
        self.v = {}
        self.alive = False              # heartbeat (System_Time read) succeeded most recently
        self.model = ""
        self.serial = ""
        self.cycles = 0
        self.last_commit_ms = None
        self._activity = 0
        self.data_cb = []               # called after every committed cycle (no args)
        self.alive_cb = []              # called when alive flips (alive)

    def get(self, name, default=None):
        return self.v.get(name, default)

    def valid(self, name):
        return name in self.v

    def mark_activity(self):
        self._activity = time.ticks_ms()

    def is_active(self):
        return time.ticks_diff(time.ticks_ms(), self._activity) < ACTIVITY_WINDOW_MS

    def set_alive(self, alive):
        if alive != self.alive:
            self.alive = alive
            for cb in self.alive_cb:
                cb(alive)

    def commit(self, batch):
        for k, val in batch.items():
            if val is not None:
                self.v[k] = val
        self.cycles += 1
        self.last_commit_ms = time.ticks_ms()
        for cb in self.data_cb:
            cb()

    def snapshot(self):
        d = {}
        for k in FIELDS:
            d[k] = self.v.get(k)
        return d
