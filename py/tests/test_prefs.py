"""Host tests for core/prefs.py (formats, the dashboard summary sentence)."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_store = {}
_settings = types.ModuleType("core.settings")
_settings.get = lambda k, d=None: _store.get(k, d)
sys.modules["core.settings"] = _settings
import core  # noqa: E402
core.settings = _settings
from core import prefs as P  # noqa: E402


class FormatTests(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(P.fmt_clock(15, 5, True), "15:05")
        self.assertEqual(P.fmt_clock(15, 5, False), "3:05 PM")
        self.assertEqual(P.fmt_clock(0, 7, False), "12:07 AM")
        self.assertEqual(P.fmt_clock(12, 0, False), "12:00 PM")

    def test_date(self):
        self.assertEqual(P.fmt_date(5, 4, 10, 2026, "dmy"), "Sat 4 Oct")
        self.assertEqual(P.fmt_date(5, 4, 10, 2026, "mdy"), "Sat Oct 4")
        self.assertEqual(P.fmt_date(5, 4, 10, 2026, "iso"), "2026-10-04")

    def test_kw(self):
        self.assertEqual(P.fmt_kw(12.866, 1), "12.9 kW")
        self.assertEqual(P.fmt_kw(12.866, 2), "12.87 kW")


class PrefTests(unittest.TestCase):
    def tearDown(self):
        _store.clear()

    def test_defaults(self):
        self.assertTrue(P.clock24())
        self.assertEqual(P.date_fmt(), "dmy")
        self.assertEqual(P.kw_decimals(), 2)
        self.assertFalse(P.high_contrast())
        _store["ui.date_fmt"] = "bogus"
        self.assertEqual(P.date_fmt(), "dmy")


class SummaryTests(unittest.TestCase):
    def s(self, **kw):
        a = dict(alive=True, age_s=10, soc=50, batt_kw=0, pv_kw=0, load_kw=1, grid_kw=0, grid_on=True, self_pct=None)
        a.update(kw)
        return P.summary(a["alive"], a["age_s"], a["soc"], a["batt_kw"], a["pv_kw"], a["load_kw"], a["grid_kw"], a["grid_on"], a["self_pct"])

    def test_waiting(self):
        self.assertEqual(self.s(age_s=None)[1], "idle")

    def test_stale_or_down(self):
        text, tone = self.s(age_s=300)
        self.assertEqual(tone, "warn")
        self.assertIn("5m ago", text)
        self.assertEqual(self.s(alive=False)[1], "warn")

    def test_off_grid(self):
        self.assertEqual(self.s(grid_on=False)[1], "bad")

    def test_import_charging(self):
        text, tone = self.s(grid_kw=13.4, batt_kw=18.3)
        self.assertEqual((text, tone), ("Importing 13.4 kW + charging battery", "ok"))

    def test_export_and_idle_cases(self):
        self.assertTrue(self.s(grid_kw=-2.0)[0].startswith("Exporting 2.0 kW to the grid"))
        self.assertEqual(self.s(grid_kw=-2.0, batt_kw=5)[0], "Exporting 2.0 kW + charging battery")
        self.assertEqual(self.s(batt_kw=-3)[0], "Running on battery")
        self.assertEqual(self.s(pv_kw=2)[0], "Running on solar")
        self.assertEqual(self.s()[0], "Idle")

    def test_tiny_flows_are_noise(self):
        self.assertEqual(self.s(grid_kw=0.09, pv_kw=2.1)[0], "Running on solar")
        self.assertEqual(self.s(grid_kw=-0.1, batt_kw=0.1)[0], "Idle")

    def test_self_powered_only_when_it_fits(self):
        self.assertIn("100% self-powered today", self.s(batt_kw=-3, self_pct=100)[0])
        self.assertNotIn("self-powered", self.s(grid_kw=13.4, batt_kw=18.3, self_pct=100)[0])


if __name__ == "__main__":
    unittest.main()
