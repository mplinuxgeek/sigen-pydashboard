"""Host-side tests (plain python3): the pure logic that does not need the board.
Run from py/:  python3 -m unittest discover tests"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# minimal stand-ins for the MicroPython modules the pure code imports
_settings = types.ModuleType("core.settings")
_store = {}
_settings.get = lambda k, d=None: _store.get(k, d)
_settings.set = lambda k, v: _store.__setitem__(k, v)
_settings.delete = lambda k: _store.pop(k, None)
sys.modules["core.settings"] = _settings
sys.modules["machine"] = types.ModuleType("machine")
import core  # noqa: E402
core.settings = _settings
from core import backlight as bl, timeutil as T, tz, modbus  # noqa: E402


class TimeTests(unittest.TestCase):
    def test_civil_roundtrip(self):
        for y, m, d in ((1970, 1, 1), (2026, 9, 30), (2024, 2, 29), (2100, 3, 1)):
            self.assertEqual(T.civil_from_days(T.days_from_civil(y, m, d)), (y, m, d))

    def test_weekday(self):
        self.assertEqual(T.civil(T.to_unix(2026, 9, 30))[6], 2)      # Wednesday, Mon=0


class TzTests(unittest.TestCase):
    SYD = "AEST-10AEDT,M10.1.0,M4.1.0/3"

    def test_dst_edges(self):
        off = lambda *a: tz.offset_for(self.SYD, T.to_unix(*a)) / 3600
        self.assertEqual(off(2026, 9, 30, 12), 10)
        self.assertEqual(off(2026, 10, 3, 15, 59), 10)
        self.assertEqual(off(2026, 10, 3, 16, 1), 11)                # DST starts 02:00 AEST first Sunday of October
        self.assertEqual(off(2026, 4, 4, 15, 59), 11)
        self.assertEqual(off(2026, 4, 4, 16, 1), 10)

    def test_fractional_and_named_offsets(self):
        self.assertEqual(tz.offset_for("ACST-9:30ACDT,M10.1.0,M4.1.0/3", T.to_unix(2026, 7, 1)) / 3600, 9.5)
        self.assertEqual(tz.offset_for("<+0845>-8:45", T.to_unix(2026, 7, 1)) / 3600, 8.75)
        self.assertEqual(tz.offset_for("EST5EDT,M3.2.0,M11.1.0", T.to_unix(2026, 7, 1)) / 3600, -4)

    def test_local_to_unix(self):
        _store["tz.posix"] = self.SYD
        self.assertEqual(T.civil(tz.local_to_unix(T.to_unix(2026, 7, 1, 12)))[3], 2)     # noon AEST = 02:00 UTC
        self.assertEqual(T.civil(tz.local_to_unix(T.to_unix(2026, 12, 1, 12)))[3], 1)    # noon AEDT = 01:00 UTC


class BacklightTests(unittest.TestCase):
    def test_curve(self):
        g = bl.PRESETS["gentle"]
        self.assertEqual(bl.curve_eval(g, 7 * 60), 50)
        self.assertEqual(bl.curve_eval(g, 9 * 60), 80)
        self.assertEqual(bl.curve_peak(g), 80)
        self.assertEqual(bl.curve_next(g, 8 * 60), 9 * 60)
        self.assertEqual(bl.curve_next(g, 23 * 60), 7 * 60)          # wraps to the first point of the day
        self.assertEqual(bl.curve_eval([], 0), 100)

    def test_validation(self):
        self.assertTrue(bl.curve_valid([(0, 10), (60, 20)]))
        self.assertFalse(bl.curve_valid([(60, 10), (60, 20)]))       # not strictly ascending
        self.assertFalse(bl.curve_valid([(0, 101)]))
        self.assertFalse(bl.curve_valid([(i, 1) for i in range(9)]))

    def test_manual_expiry(self):
        self.assertFalse(bl.manual_expired(100, 200, 150))
        self.assertTrue(bl.manual_expired(100, 200, 210))
        self.assertFalse(bl.manual_expired(100, 100, 300))           # single point: lasts a whole day

    def test_gpio_allowed(self):
        self.assertTrue(bl.gpio_allowed(6))
        self.assertFalse(bl.gpio_allowed(8))                         # I2C
        self.assertFalse(bl.gpio_allowed(3))                         # RGB VSYNC


class ModbusDecodeTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(modbus.u32([0x0001, 0x0000]), 65536)
        self.assertEqual(modbus.i32([0xFFFF, 0xFFFE]), -2)
        self.assertEqual(modbus.i16([0xFFFF]), -1)
        self.assertEqual(modbus.u64([0, 0, 1, 0]), 65536)

    def test_ascii(self):
        self.assertEqual(modbus.ascii_regs([0x4142, 0x4300]), "ABC")


if __name__ == "__main__":
    unittest.main()
