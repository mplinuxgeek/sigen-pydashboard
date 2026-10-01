#!/usr/bin/env python3
"""Build a littlefs image of the Python app (py/) for the board's `vfs` partition (0x5F0000, 0x210000 bytes).

    pip install littlefs-python
    python3 scripts/make_fs_image.py OUT.bin [--settings settings.json]

Used by the release workflow to make a single factory image that boots straight into the app. The block size and size must
match board_s3_7/partitions.csv.
"""
import argparse
import os
import sys

from littlefs import LittleFS

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py")
FILES = ("board.py", "main.py", "boot.py")
DIRS = ("core", "ui", "www")
BLOCK, SIZE = 4096, 0x210000


def add_tree(fs, src, dst):
    fs.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        if name == "__pycache__":
            continue
        s, d = os.path.join(src, name), dst.rstrip("/") + "/" + name
        if os.path.isdir(s):
            add_tree(fs, s, d)
        else:
            with open(s, "rb") as f, fs.open(d, "wb") as o:
                o.write(f.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--settings", help="optional settings.json to preload (e.g. WiFi and inverter address)")
    a = ap.parse_args()
    fs = LittleFS(block_size=BLOCK, block_count=SIZE // BLOCK)
    for n in FILES:
        with open(os.path.join(ROOT, n), "rb") as f, fs.open("/" + n, "wb") as o:
            o.write(f.read())
    for d in DIRS:
        add_tree(fs, os.path.join(ROOT, d), "/" + d)
    if a.settings:
        with open(a.settings, "rb") as f, fs.open("/settings.json", "wb") as o:
            o.write(f.read())
    with open(a.out, "wb") as f:
        f.write(bytes(fs.context.buffer))
    print("wrote %s (%d KB, %d files)" % (a.out, SIZE // 1024, sum(len(fl) for _r, _d, fl in os.walk(ROOT) if "tests" not in _r)))


if __name__ == "__main__":
    sys.exit(main())
