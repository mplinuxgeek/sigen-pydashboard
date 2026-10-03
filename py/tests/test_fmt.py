"""Host tests for core/fmt.py. Run from py/:  python3 -m unittest discover tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import fmt  # noqa: E402


class DurationTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(fmt.duration(0), "0s")
        self.assertEqual(fmt.duration(59), "59s")
        self.assertEqual(fmt.duration(60), "1m 0s")
        self.assertEqual(fmt.duration(200), "3m 20s")
        self.assertEqual(fmt.duration(3600), "1h 00m")
        self.assertEqual(fmt.duration(5 * 3600 + 7 * 60), "5h 07m")
        self.assertEqual(fmt.duration(86400), "1d 0h")
        self.assertEqual(fmt.duration(2 * 86400 + 4 * 3600 + 59), "2d 4h")

    def test_negative_is_zero(self):
        self.assertEqual(fmt.duration(-5), "0s")


class AgoTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(fmt.ago(3), "just now")
        self.assertEqual(fmt.ago(45), "45s ago")
        self.assertEqual(fmt.ago(180), "3m ago")
        self.assertEqual(fmt.ago(3 * 3600 + 59), "3h ago")
        self.assertEqual(fmt.ago(3 * 86400), "3d ago")


if __name__ == "__main__":
    unittest.main()
