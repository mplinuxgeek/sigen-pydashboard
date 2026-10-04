"""Host tests for core/flows.py: the flow split must respect the measured totals in every situation."""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
if not hasattr(asyncio, "sleep_ms"):
    asyncio.sleep_ms = lambda ms: asyncio.sleep(ms / 1000)
from core import flows  # noqa: E402


def approx(d, **kw):
    for k, v in kw.items():
        assert abs(d[k] - v) < 1e-9, (k, d[k], v, d)
    return True


class SplitTests(unittest.TestCase):
    def test_solar_covers_home_and_exports(self):
        approx(flows.split(5, 2, 0, -3), sh=2, sg=3, sb=0, gh=0, bh=0)

    def test_solar_charges_battery_before_exporting(self):
        approx(flows.split(8, 2, 4, -2), sh=2, sb=4, sg=2)

    def test_battery_covers_the_rest_of_the_home(self):
        approx(flows.split(1, 4, -3, 0), sh=1, bh=3, gh=0)

    def test_grid_fills_the_gap(self):
        approx(flows.split(1, 5, -2, 2), sh=1, bh=2, gh=2)

    def test_grid_charging_the_battery(self):
        approx(flows.split(0, 1, 5, 6), gh=1, gb=5, sb=0)

    def test_battery_exporting(self):
        approx(flows.split(0, 1, -6, -5), bh=1, bg=5, sg=0)

    def test_night_idle(self):
        self.assertTrue(all(v == 0 for v in flows.split(0, 0, 0, 0).values()))

    def test_never_exceeds_measurements_or_goes_negative(self):
        import itertools
        vals = (-7, -2, -0.3, 0, 0.4, 3, 9)
        for pv, load, batt, grid in itertools.product((0, 0.5, 4, 12), (0, 1, 6), vals, vals):
            f = flows.split(pv, load, batt, grid)
            self.assertTrue(all(v >= -1e-9 for v in f.values()), (pv, load, batt, grid, f))
            self.assertLessEqual(f["sh"] + f["sb"] + f["sg"], pv + 1e-9)                  # solar out <= solar made
            self.assertLessEqual(f["sh"] + f["bh"] + f["gh"], max(load, 0) + 1e-9)        # home in <= home use
            self.assertLessEqual(f["gh"] + f["gb"], max(grid, 0) + 1e-9)                  # grid out <= import
            self.assertLessEqual(f["sg"] + f["bg"], max(-grid, 0) + 1e-9)                 # export <= measured export
            self.assertLessEqual(f["sb"] + f["gb"], max(batt, 0) + 1e-9)                  # charge <= measured charge
            self.assertLessEqual(f["bh"] + f["bg"], max(-batt, 0) + 1e-9)                 # discharge <= measured


class FakeHist:
    def __init__(self, rows):
        self.n = len(rows)
        self.ts = [r[0] for r in rows]
        self.pv = [r[1] for r in rows]
        self.load = [r[2] for r in rows]
        self.batt = [r[3] for r in rows]
        self.grid = [r[4] for r in rows]


class TotalsTests(unittest.TestCase):
    def test_one_hour_of_steady_flow(self):
        rows = [(1000 + i * 300, 4000, 1000, 2000, -1000) for i in range(12)]       # W, 12 samples = 1 h
        t = asyncio.run(flows.totals(FakeHist(rows), 0, 10 ** 9))
        self.assertAlmostEqual(t["solar"], 4.0)
        self.assertAlmostEqual(t["home"], 1.0)
        self.assertAlmostEqual(t["sh"], 1.0)
        self.assertAlmostEqual(t["sb"], 2.0)
        self.assertAlmostEqual(t["sg"], 1.0)
        self.assertAlmostEqual(t["g_out"], 1.0)
        self.assertEqual(t["samples"], 12)

    def test_time_window(self):
        rows = [(1000 + i * 300, 1000, 0, 0, -1000) for i in range(12)]
        t = asyncio.run(flows.totals(FakeHist(rows), 1000 + 6 * 300, 10 ** 9))
        self.assertEqual(t["samples"], 6)
        self.assertAlmostEqual(t["solar"], 0.5)


if __name__ == "__main__":
    unittest.main()
