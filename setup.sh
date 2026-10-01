#!/bin/bash
# One-time setup: fetch the pinned MicroPython and LVGL-binding sources and apply this project's patches.
#   ./setup.sh            (needs git, patch tools, network; about 500 MB of downloads)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/versions.env"
. "$HERE/scripts/common.sh"
load_idf

if [ -d "$HERE/micropython/ports/esp32" ]; then
    echo "micropython/ already present, leaving it alone"
else
    echo "== MicroPython $MICROPYTHON_TAG"
    git clone --quiet --depth 1 --branch "$MICROPYTHON_TAG" "$MICROPYTHON_REPO" "$HERE/micropython"
    got=$(git -C "$HERE/micropython" rev-parse HEAD)
    case $got in "$MICROPYTHON_COMMIT"*) ;; *) echo "unexpected MicroPython commit $got (wanted $MICROPYTHON_COMMIT)" >&2; exit 1;; esac
    git -C "$HERE/micropython" apply "$HERE/patches/micropython-esp32.patch"
fi
echo "== MicroPython submodules for the ESP32 port"
make -C "$HERE/micropython/ports/esp32" BOARD=ESP32_GENERIC_S3 submodules

if [ -d "$HERE/lv_binding_micropython/lvgl/src" ]; then
    echo "lv_binding_micropython/ already present, leaving it alone"
else
    echo "== lv_binding_micropython $LVB_COMMIT (+ LVGL, pycparser)"
    git clone --quiet --filter=blob:none "$LVB_REPO" "$HERE/lv_binding_micropython"
    git -C "$HERE/lv_binding_micropython" checkout --quiet "$LVB_COMMIT"
    git -C "$HERE/lv_binding_micropython" submodule update --init --depth 1 lvgl pycparser
    git -C "$HERE/lv_binding_micropython" apply "$HERE/patches/lv_binding-gen_mpy.patch"
fi
echo "setup done. Next: ./build.sh -j8"
