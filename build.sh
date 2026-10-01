#!/bin/bash
# Build custom MicroPython for the Waveshare ESP32-S3-Touch-LCD-7: LVGL, RGB LCD driver, WiFi. Code+rodata run from PSRAM.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/versions.env"
[ -d "$HERE/micropython/ports/esp32" ] && [ -d "$HERE/lv_binding_micropython/lvgl/src" ] || "$HERE/setup.sh"
# ESP-IDF: use the environment you already exported, else $IDF_PATH, else ~/esp/esp-idf-$IDF_VERSION
if ! command -v idf.py >/dev/null 2>&1; then
    IDF=${IDF_PATH:-$HOME/esp/esp-idf-v$IDF_VERSION}
    [ -f "$IDF/export.sh" ] || { echo "ESP-IDF $IDF_VERSION not found. Install it (https://docs.espressif.com/projects/esp-idf/) and run its install.sh esp32s3," >&2; echo "then either source export.sh or set IDF_PATH." >&2; exit 1; }
    . "$IDF/export.sh" >/dev/null
fi
[ -d "$HERE"/fonts ] && ls "$HERE"/fonts/lv_font_*.c >/dev/null 2>&1 && cp "$HERE"/fonts/lv_font_*.c "$HERE/lv_binding_micropython/lvgl/src/font/"
echo "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=\"$HERE/board_s3_7/partitions.csv\"" > "$HERE/board_s3_7/sdkconfig.paths"
B="$HERE/micropython/ports/esp32/build-ESP32_GENERIC_S3"
make -C "$HERE/micropython/mpy-cross" -j
cd "$HERE/micropython/ports/esp32"
run() {
    make BOARD=ESP32_GENERIC_S3 BOARD_DIR="$HERE/board_s3_7" \
         USER_C_MODULES="$HERE/usermod/micropython.cmake" "$@"
}
# The lv binding truncates lv_mp.c on every cmake (re)configure, so if that happened
# during the first pass, drop the empty generated file and build again.
[ -s "$B/lv_mp.c" ] || rm -f "$B"/lv_mp.c*
if ! run "$@"; then
    if [ ! -s "$B/lv_mp.c" ]; then
        rm -f "$B"/lv_mp.c* "$B/frozen_content.c"
        run "$@"
    else
        exit 1
    fi
fi
[ -s "$B/lv_mp.c" ] || { rm -f "$B"/lv_mp.c* "$B/frozen_content.c"; run "$@"; }
