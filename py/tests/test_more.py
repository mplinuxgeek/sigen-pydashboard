"""More host tests: time helpers, the settings store, the time zone table. Run from py/:  python3 -m unittest discover tests"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
from core import timeutil as T  # noqa: E402


def load_real_settings(path):
    """core.settings itself (test_core.py replaces it with a stub), pointed at a temp file."""
    spec = importlib.util.spec_from_file_location("real_settings", os.path.join(HERE, "..", "core", "settings.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.PATH = path
    return m


class BisectTests(unittest.TestCase):
    A = [10, 20, 20, 30, 40, 0, 0]          # only the first n=5 entries are valid

    def test_positions(self):
        self.assertEqual(T.bisect_left(self.A, 5, 5), 0)
        self.assertEqual(T.bisect_left(self.A, 5, 20), 1)
        self.assertEqual(T.bisect_left(self.A, 5, 25), 3)
        self.assertEqual(T.bisect_left(self.A, 5, 40), 4)
        self.assertEqual(T.bisect_left(self.A, 5, 99), 5)        # past the end: n, never into the unused tail

    def test_empty(self):
        self.assertEqual(T.bisect_left([], 0, 1), 0)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "settings.json")
        self.s = load_real_settings(self.path)

    def read(self):
        with open(self.path) as f:
            return json.load(f)

    def tearDown(self):
        self.dir.cleanup()

    def test_roundtrip_and_default(self):
        self.assertEqual(self.s.get("a", 5), 5)
        self.s.set("a", 7)
        self.assertEqual(self.read(), {"a": 7})
        fresh = load_real_settings(self.path)                      # a new process would read it back
        self.assertEqual(fresh.get("a"), 7)

    def test_unchanged_write_is_skipped(self):
        self.s.set("a", 1)
        before = os.stat(self.path).st_mtime_ns
        os.utime(self.path, ns=(before - 10 ** 9, before - 10 ** 9))
        stamp = os.stat(self.path).st_mtime_ns
        self.s.set("a", 1)
        self.assertEqual(os.stat(self.path).st_mtime_ns, stamp)    # file untouched

    def test_delete(self):
        self.s.set("a", 1)
        self.s.delete("a")
        self.s.delete("missing")
        self.assertEqual(self.read(), {})

    def test_corrupt_file_falls_back_to_empty(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(load_real_settings(self.path).get("a", "d"), "d")


class TzTableTests(unittest.TestCase):
    def test_tzdata_is_well_formed(self):
        with open(os.path.join(HERE, "..", "www", "tzdata.json")) as f:
            d = json.load(f)
        self.assertGreater(len(d), 200)
        for code, c in d.items():
            self.assertEqual(len(code), 2)
            self.assertTrue(c["name"])
            self.assertTrue(c["zones"])
            for z in c["zones"]:
                self.assertTrue(z["z"] and z["p"] and z["l"])

    def test_every_posix_string_evaluates(self):
        from core import tz
        with open(os.path.join(HERE, "..", "www", "tzdata.json")) as f:
            d = json.load(f)
        t = T.to_unix(2026, 7, 1, 12)
        for c in d.values():
            for z in c["zones"]:
                off = tz.offset_for(z["p"], t)
                self.assertTrue(-14 * 3600 <= off <= 14 * 3600, z["z"])


if __name__ == "__main__":
    unittest.main()
