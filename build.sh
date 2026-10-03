#!/bin/bash
# Build custom MicroPython for the Waveshare ESP32-S3-Touch-LCD-7: LVGL, RGB LCD driver, WiFi. Code+rodata run from PSRAM.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/versions.env"
. "$HERE/scripts/common.sh"
[ -f "$HERE/micropython/lib/micropython-lib/README.md" ] && [ -d "$HERE/lv_binding_micropython/lvgl/src" ] || "$HERE/setup.sh"
load_idf
[ -d "$HERE"/fonts ] && ls "$HERE"/fonts/lv_font_*.c >/dev/null 2>&1 && cp "$HERE"/fonts/lv_font_*.c "$HERE/lv_binding_micropython/lvgl/src/font/"
echo "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=\"$HERE/board_s3_7/partitions.csv\"" > "$HERE/board_s3_7/sdkconfig.paths"
B="$HERE/micropython/ports/esp32/build-ESP32_GENERIC_S3"
make -C "$HERE/micropython/mpy-cross" -j
cd "$HERE/micropython/ports/esp32"
run() {
    make BOARD=ESP32_GENERIC_S3 BOARD_DIR="$HERE/board_s3_7" \
         USER_C_MODULES="$HERE/usermod/micropython.cmake" "$@"
}
# The lv binding truncates lv_mp.c whenever cmake reconfigures, which makes that pass fail at link time (sometimes with a
# zero exit status). So: build, and unless the firmware really got linked (micropython.bin newer than lv_mp.c), drop the
# generated binding and build again.
for attempt in 1 2 3; do
    [ -s "$B/lv_mp.c" ] || rm -f "$B"/lv_mp.c* "$B/frozen_content.c"
    run "$@" || true
    if [ -s "$B/lv_mp.c" ] && [ "$B/micropython.bin" -nt "$B/lv_mp.c" ]; then
        exit 0
    fi
    echo "build: link did not complete (attempt $attempt), retrying" >&2
    rm -f "$B"/lv_mp.c* "$B/frozen_content.c"
done
echo "build failed" >&2
exit 1
