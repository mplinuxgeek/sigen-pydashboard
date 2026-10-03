"""Host tests for the GitHub updater's pure parts. Run from py/:  python3 -m unittest discover tests"""
import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for name in ("machine", "esp32"):
    sys.modules.setdefault(name, types.ModuleType(name))
if not hasattr(asyncio, "sleep_ms"):                                   # MicroPython-only
    asyncio.sleep_ms = lambda ms: asyncio.sleep(ms / 1000)
from core import updater  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("0.10"), (0, 10, 0))
        self.assertEqual(updater.parse_version("2.0.0-rc1"), (2, 0, 0))
        self.assertEqual(updater.parse_version("junk"), (0, 0, 0))

    def test_ordering_is_numeric_not_textual(self):
        self.assertGreater(updater.parse_version("0.10.0"), updater.parse_version("0.9.9"))
        self.assertGreater(updater.parse_version("1.0.0"), updater.parse_version("0.99.99"))
        self.assertFalse(updater.parse_version("0.2.0") > updater.parse_version("0.2.0"))

    def test_firmware_api_line(self):
        self.assertEqual(updater.needs_firmware_api('VERSION = "1"\nNEEDS_FW_API = 3\n'), 3)
        self.assertEqual(updater.needs_firmware_api("NEEDS_FW_API = 2  # new blit\n"), 2)
        self.assertEqual(updater.needs_firmware_api('VERSION = "1"\n'), 0)


class UrlTests(unittest.TestCase):
    def test_split(self):
        self.assertEqual(updater._split("https://api.github.com/repos/a/b"), ("https", "api.github.com", 443, "/repos/a/b", "api.github.com"))
        self.assertEqual(updater._split("http://10.0.0.5:8099/x"), ("http", "10.0.0.5", 8099, "/x", "10.0.0.5:8099"))
        self.assertEqual(updater._split("https://host")[3], "/")


class FakeReader:
    def __init__(self, data):
        self.data = data

    async def readline(self):
        i = self.data.find(b"\n") + 1
        line, self.data = self.data[:i], self.data[i:]
        return line

    async def read(self, n):
        out, self.data = self.data[:n], self.data[n:]
        return out


class BodyTests(unittest.TestCase):
    def read_all(self, data, headers, n=7):
        async def go():
            b = updater._Body(FakeReader(data), headers)
            out = b""
            while True:
                chunk = await b.read(n)
                if not chunk:
                    return out
                out += chunk
        return asyncio.run(go())

    def test_content_length(self):
        self.assertEqual(self.read_all(b"hello world!!EXTRA", {"content-length": "12"}), b"hello world!")

    def test_chunked(self):
        data = b"5\r\nhello\r\n6;ext=1\r\n world\r\n0\r\n\r\n"
        self.assertEqual(self.read_all(data, {"transfer-encoding": "chunked"}), b"hello world")

    def test_until_close(self):
        self.assertEqual(self.read_all(b"abc", {}), b"abc")

    def test_truncated_download_is_an_error(self):
        with self.assertRaises(OSError):
            self.read_all(b"abc", {"content-length": "10"})


if __name__ == "__main__":
    unittest.main()
